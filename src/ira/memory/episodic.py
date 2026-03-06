"""Episodic memory — narrative summaries of significant interactions."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from ira.config import LLMConfig, get_settings
from ira.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

_CONSOLIDATE_SYSTEM_PROMPT = (
    "You are an analyst. Analyze the following conversation transcript and return "
    "ONLY valid JSON with no other text. Required keys: "
    '"narrative" (2-3 sentence summary), '
    '"key_topics" (list of strings), '
    '"decisions_made" (list of strings), '
    '"commitments" (list of strings), '
    '"emotional_tone" (string), '
    '"relationship_impact" (one of: strengthened, maintained, strained, new_contact).'
)

_WEAVE_SYSTEM_PROMPT = (
    "You are a relationship historian. Given a series of episode summaries for "
    "interactions with a customer, weave them into a single coherent narrative "
    "that tells the story of this relationship. Focus on how the relationship "
    "evolved, key turning points, and the current state."
)


class EpisodicMemory:
    def __init__(
        self,
        long_term: LongTermMemory,
        db_path: str = "conversations.db",
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._long_term = long_term
        self._db_path = db_path
        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                narrative TEXT NOT NULL,
                key_topics TEXT NOT NULL,
                decisions TEXT NOT NULL,
                commitments TEXT NOT NULL,
                emotional_tone TEXT NOT NULL,
                relationship_impact TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_user ON episodes(user_id)"
        )
        await self._db.commit()

    async def consolidate_episode(self, conversation: list[dict], user_id: str) -> dict:
        transcript = "".join(
            f"[{m.get('role', 'unknown')}] {m.get('content', '')}\n"
            for m in conversation
        )
        raw = await self._llm_call(_CONSOLIDATE_SYSTEM_PROMPT, transcript)
        fallback = {
            "narrative": "(Consolidation failed)",
            "key_topics": [],
            "decisions_made": [],
            "commitments": [],
            "emotional_tone": "unknown",
            "relationship_impact": "unknown",
        }
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                episode = {
                    "narrative": parsed.get("narrative", fallback["narrative"]),
                    "key_topics": parsed.get("key_topics", []),
                    "decisions_made": parsed.get("decisions_made", []),
                    "commitments": parsed.get("commitments", []),
                    "emotional_tone": parsed.get("emotional_tone", fallback["emotional_tone"]),
                    "relationship_impact": parsed.get(
                        "relationship_impact", fallback["relationship_impact"]
                    ),
                }
            else:
                episode = fallback
        except (json.JSONDecodeError, TypeError):
            episode = fallback

        now = datetime.now(timezone.utc).isoformat()

        async def _write_sqlite() -> int:
            assert self._db is not None
            cursor = await self._db.execute(
                """
                INSERT INTO episodes (
                    user_id, narrative, key_topics, decisions, commitments,
                    emotional_tone, relationship_impact, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    episode["narrative"],
                    json.dumps(episode["key_topics"]),
                    json.dumps(episode["decisions_made"]),
                    json.dumps(episode["commitments"]),
                    episode["emotional_tone"],
                    episode["relationship_impact"],
                    now,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

        if episode != fallback:
            mem0_task = self._long_term.store(
                episode["narrative"],
                user_id,
                metadata={
                    "type": "episode",
                    "key_topics": json.dumps(episode["key_topics"]),
                    "emotional_tone": episode["emotional_tone"],
                },
            )
            ep_id, _ = await asyncio.gather(_write_sqlite(), mem0_task)
        else:
            ep_id = await _write_sqlite()

        return {
            "id": ep_id,
            "user_id": user_id,
            **episode,
            "created_at": now,
        }

    async def weave_episodes(self, user_id: str, topic: str | None = None) -> str:
        assert self._db is not None
        if topic:
            cursor = await self._db.execute(
                """
                SELECT id, narrative, created_at FROM episodes
                WHERE user_id = ? AND key_topics LIKE ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (user_id, f"%{topic}%"),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT id, narrative, created_at FROM episodes
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (user_id,),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        if not rows:
            return "No episodes found for this user."

        formatted = "\n".join(
            f"{i+1}. [{r[2]}] {r[1]}" for i, r in enumerate(rows)
        )
        raw = await self._llm_call(_WEAVE_SYSTEM_PROMPT, formatted)
        if raw in ("(LLM call failed)", "(No OpenAI key configured)") or not raw.strip():
            return "(Narrative weaving failed)"
        return raw.strip()

    async def surface_relevant_episodes(
        self, query: str, user_id: str
    ) -> list[dict]:
        mem0_results = await self._long_term.search(query, user_id, limit=5)
        mem0_episodes = [
            r for r in mem0_results
            if r.get("metadata", {}).get("type") == "episode"
        ]

        keywords = query.lower().strip().split()[:3]
        sqlite_episodes: list[dict] = []
        if keywords and self._db is not None:
            conditions = " OR ".join(
                ["(narrative LIKE ? OR key_topics LIKE ?)"] * len(keywords)
            )
            params: list[Any] = [user_id]
            for kw in keywords:
                pattern = f"%{kw}%"
                params.extend([pattern, pattern])
            cursor = await self._db.execute(
                f"""
                SELECT id, narrative, key_topics, emotional_tone,
                       relationship_impact, created_at
                FROM episodes
                WHERE user_id = ? AND ({conditions})
                ORDER BY created_at DESC
                LIMIT 10
                """,
                params,
            )
            rows = await cursor.fetchall()
            await cursor.close()
            sqlite_episodes = [
                {
                    "id": r[0],
                    "narrative": r[1],
                    "key_topics": r[2],
                    "emotional_tone": r[3],
                    "relationship_impact": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ]

        seen: set[str] = set()
        merged: list[dict] = []
        for r in mem0_episodes:
            narrative = r.get("memory", "")
            sig = narrative[:100] if narrative else ""
            if sig and sig not in seen:
                seen.add(sig)
                merged.append({
                    "id": r.get("id", ""),
                    "narrative": narrative,
                    "key_topics": r.get("metadata", {}).get("key_topics", "[]"),
                    "emotional_tone": r.get("metadata", {}).get("emotional_tone", ""),
                    "relationship_impact": "",
                    "created_at": r.get("created_at", ""),
                })
        for r in sqlite_episodes:
            narrative = r.get("narrative", "")
            sig = narrative[:100] if narrative else ""
            if sig and sig not in seen:
                seen.add(sig)
                merged.append(r)
        return merged[:5]

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
            logger.exception("LLM call failed in EpisodicMemory")
            return "(LLM call failed)"

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> EpisodicMemory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
