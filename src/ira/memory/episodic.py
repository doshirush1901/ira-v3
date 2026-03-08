"""Episodic memory — narrative summaries of significant interactions."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from langfuse.decorators import observe

from ira.memory.long_term import LongTermMemory
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import EpisodeConsolidation
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_CONSOLIDATE_SYSTEM_PROMPT = load_prompt("consolidate_episode")

_WEAVE_SYSTEM_PROMPT = load_prompt("weave_episodes")


class EpisodicMemory:
    def __init__(
        self,
        long_term: LongTermMemory,
        db_path: str = "data/conversations.db",
    ) -> None:
        self._long_term = long_term
        self._db_path = db_path
        self._llm = get_llm_client()
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

    @observe()
    async def consolidate_episode(self, conversation: list[dict], user_id: str) -> dict:
        transcript = "".join(
            f"[{m.get('role', 'unknown')}] {m.get('content', '')}\n"
            for m in conversation
        )
        fallback = {
            "narrative": "(Consolidation failed)",
            "key_topics": [],
            "decisions_made": [],
            "commitments": [],
            "emotional_tone": "unknown",
            "relationship_impact": "unknown",
        }
        try:
            result = await self._llm.generate_structured(
                _CONSOLIDATE_SYSTEM_PROMPT, transcript, EpisodeConsolidation,
                name="episodic.consolidate",
            )
            episode = {
                "narrative": result.narrative or fallback["narrative"],
                "key_topics": result.key_topics,
                "decisions_made": result.decisions_made,
                "commitments": result.commitments,
                "emotional_tone": result.emotional_tone or fallback["emotional_tone"],
                "relationship_impact": result.relationship_impact or fallback["relationship_impact"],
            }
        except Exception:
            logger.exception("Structured LLM call failed in EpisodicMemory.consolidate_episode")
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
        try:
            raw = await self._llm.generate_text(
                _WEAVE_SYSTEM_PROMPT, formatted,
                name="episodic.weave",
            )
        except Exception:
            logger.exception("Text LLM call failed in EpisodicMemory.weave_episodes")
            return "(Narrative weaving failed)"
        if not raw or not raw.strip():
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

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> EpisodicMemory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
