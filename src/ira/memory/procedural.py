"""Procedural memory — learned response patterns for recurring request types."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx
from pydantic import BaseModel

from ira.config import LLMConfig, get_settings

logger = logging.getLogger(__name__)

_PATTERN_SYSTEM_PROMPT = (
    "You are a pattern extraction engine. Given a specific user query, extract a "
    "generalized trigger pattern that would match similar future queries. Replace "
    "specific entity names with placeholders like {company}, {machine}, {person}, "
    "{region}, {amount}. Return ONLY the pattern string, no explanation."
)


class Procedure(BaseModel):
    id: int | None = None
    trigger_pattern: str
    steps: list[str]
    success_rate: float = 1.0
    times_used: int = 1
    last_used: datetime | None = None


class ProceduralMemory:
    def __init__(
        self,
        db_path: str = "conversations.db",
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._db_path = db_path
        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model
        self._db: aiosqlite.Connection | None = None
        self._cache: list[Procedure] = []
        self._cache_time: float = 0.0

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS procedures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_pattern TEXT NOT NULL,
                steps TEXT NOT NULL,
                success_rate REAL NOT NULL DEFAULT 1.0,
                times_used INTEGER NOT NULL DEFAULT 1,
                last_used TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_procedures_pattern ON procedures(trigger_pattern)"
        )
        await self._db.commit()

    def _jaccard_similarity(self, a: str, b: str) -> float:
        def tokenize(s: str) -> set[str]:
            tokens = set(re.findall(r"\w+", s.lower()))
            return {t for t in tokens if not re.match(r"^\{.*\}$", t)}

        set_a = tokenize(a)
        set_b = tokenize(b)
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)

    async def _load_cache(self) -> list[Procedure]:
        if time.monotonic() - self._cache_time < 60:
            return self._cache
        assert self._db is not None
        cursor = await self._db.execute("SELECT * FROM procedures")
        rows = await cursor.fetchall()
        await cursor.close()
        self._cache = []
        for row in rows:
            self._cache.append(
                Procedure(
                    id=row[0],
                    trigger_pattern=row[1],
                    steps=json.loads(row[2]),
                    success_rate=row[3],
                    times_used=row[4],
                    last_used=(
                        datetime.fromisoformat(row[5].replace("Z", "+00:00"))
                        if row[5]
                        else None
                    ),
                )
            )
        self._cache_time = time.monotonic()
        return self._cache

    async def learn_procedure(
        self,
        query: str,
        successful_response_path: list[str],
    ) -> Procedure:
        raw = await self._llm_call(_PATTERN_SYSTEM_PROMPT, query)
        if raw in ("(LLM call failed)", "(No OpenAI key configured)") or not raw or not raw.strip():
            trigger_pattern = query.lower()
        else:
            trigger_pattern = raw.strip()

        procedures = await self._load_cache()
        best_match: Procedure | None = None
        best_sim = 0.0
        for p in procedures:
            sim = self._jaccard_similarity(trigger_pattern, p.trigger_pattern)
            if sim > 0.6 and sim > best_sim:
                best_sim = sim
                best_match = p

        now = datetime.now(timezone.utc).isoformat()
        assert self._db is not None

        if best_match is not None and best_match.id is not None:
            new_rate = 0.9 * best_match.success_rate + 0.1 * 1.0
            if best_match.times_used < 3:
                await self._db.execute(
                    """
                    UPDATE procedures
                    SET times_used = times_used + 1, last_used = ?, success_rate = ?, steps = ?
                    WHERE id = ?
                    """,
                    (now, new_rate, json.dumps(successful_response_path), best_match.id),
                )
            else:
                await self._db.execute(
                    """
                    UPDATE procedures
                    SET times_used = times_used + 1, last_used = ?, success_rate = ?
                    WHERE id = ?
                    """,
                    (now, new_rate, best_match.id),
                )
            await self._db.commit()
            self._cache_time = 0.0
            return Procedure(
                id=best_match.id,
                trigger_pattern=best_match.trigger_pattern,
                steps=successful_response_path if best_match.times_used < 3 else best_match.steps,
                success_rate=new_rate,
                times_used=best_match.times_used + 1,
                last_used=datetime.now(timezone.utc),
            )

        await self._db.execute(
            """
            INSERT INTO procedures (trigger_pattern, steps, success_rate, times_used, last_used)
            VALUES (?, ?, 1.0, 1, ?)
            """,
            (trigger_pattern, json.dumps(successful_response_path), now),
        )
        await self._db.commit()
        cursor = await self._db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        await cursor.close()
        rid = row[0] if row else None
        self._cache_time = 0.0
        return Procedure(
            id=rid,
            trigger_pattern=trigger_pattern,
            steps=successful_response_path,
            success_rate=1.0,
            times_used=1,
            last_used=datetime.now(timezone.utc),
        )

    async def find_procedure(self, query: str) -> Procedure | None:
        procedures = await self._load_cache()
        best: Procedure | None = None
        best_sim = 0.0
        for p in procedures:
            if p.success_rate < 0.7 or p.times_used < 3:
                continue
            sim = self._jaccard_similarity(query, p.trigger_pattern)
            if sim >= 0.5 and sim > best_sim:
                best_sim = sim
                best = p
        return best

    async def get_top_procedures(self, limit: int = 10) -> list[Procedure]:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            SELECT * FROM procedures
            ORDER BY (success_rate * times_used) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            Procedure(
                id=row[0],
                trigger_pattern=row[1],
                steps=json.loads(row[2]),
                success_rate=row[3],
                times_used=row[4],
                last_used=(
                    datetime.fromisoformat(row[5].replace("Z", "+00:00"))
                    if row[5]
                    else None
                ),
            )
            for row in rows
        ]

    async def record_failure(self, query: str) -> None:
        procedures = await self._load_cache()
        best_match: Procedure | None = None
        best_sim = 0.0
        for p in procedures:
            sim = self._jaccard_similarity(query, p.trigger_pattern)
            if sim > best_sim:
                best_sim = sim
                best_match = p

        if best_match is None or best_match.id is None:
            return

        new_rate = 0.9 * best_match.success_rate + 0.1 * 0.0
        assert self._db is not None
        if new_rate < 0.3:
            await self._db.execute("DELETE FROM procedures WHERE id = ?", (best_match.id,))
        else:
            await self._db.execute(
                "UPDATE procedures SET success_rate = ? WHERE id = ?",
                (new_rate, best_match.id),
            )
        await self._db.commit()
        self._cache_time = 0.0

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return "(No OpenAI key configured)"

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("LLM call failed in ProceduralMemory")
            return "(LLM call failed)"

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> ProceduralMemory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
