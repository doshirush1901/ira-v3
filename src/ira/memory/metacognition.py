"""Meta-cognition — self-awareness about knowledge quality and gaps."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from ira.config import LLMConfig, get_settings
from ira.data.models import KnowledgeState

logger = logging.getLogger(__name__)

_ASSESS_SYSTEM_PROMPT = """You are a knowledge quality assessor for an industrial machinery company. Given a user query and a set of retrieved context chunks, analyze the quality of the available information.

Return ONLY valid JSON:
{
  "state": "KNOW_VERIFIED|KNOW_UNVERIFIED|PARTIAL|UNCERTAIN|CONFLICTING|UNKNOWN",
  "confidence": 0.0,
  "conflicts": ["description of conflict 1"],
  "gaps": ["what information is missing 1"]
}

Consider: Are the sources authoritative (machine manuals vs. casual notes)? Is the information recent? Do multiple sources agree or contradict? Does the context fully answer the query or only partially?"""


class Metacognition:
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

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                state TEXT NOT NULL,
                gaps TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_date ON knowledge_gaps(created_at)"
        )
        await self._db.commit()

    async def assess_knowledge(self, query: str, retrieved_context: list[dict]) -> dict:
        has_results = len(retrieved_context) > 0
        if not has_results:
            return {
                "state": KnowledgeState.UNKNOWN,
                "confidence": 0.0,
                "sources": [],
                "conflicts": [],
                "gaps": [],
            }

        avg_score = sum(r.get("score", 0) for r in retrieved_context) / len(
            retrieved_context
        )
        has_high_confidence = any(r.get("score", 0) >= 0.7 for r in retrieved_context)
        sources = [
            {
                "source": r.get("source", ""),
                "source_type": r.get("source_type", ""),
                "score": r.get("score", 0),
            }
            for r in retrieved_context
        ]

        context_lines = []
        for i, r in enumerate(retrieved_context, 1):
            content = r.get("content", r.get("text", r.get("snippet", "")))
            context_lines.append(
                f"Chunk {i}: source={r.get('source', '')}, score={r.get('score', 0)}\n{content}"
            )
        user_msg = f"Query: {query}\n\nContext:\n" + "\n\n".join(context_lines)

        raw = await self._llm_call(_ASSESS_SYSTEM_PROMPT, user_msg)

        try:
            data = json.loads(raw)
            state_str = data.get("state", "UNKNOWN")
            confidence = float(data.get("confidence", 0.0))
            conflicts = data.get("conflicts", [])
            if not isinstance(conflicts, list):
                conflicts = []
            gaps = data.get("gaps", [])
            if not isinstance(gaps, list):
                gaps = []
        except (json.JSONDecodeError, ValueError, TypeError):
            if avg_score >= 0.7 and has_high_confidence:
                state_str = "KNOW_UNVERIFIED"
                confidence = avg_score
            elif avg_score >= 0.4:
                state_str = "PARTIAL"
                confidence = avg_score
            else:
                state_str = "UNCERTAIN"
                confidence = avg_score
            conflicts = []
            gaps = []

        try:
            state = KnowledgeState(state_str)
        except ValueError:
            state = KnowledgeState.UNCERTAIN

        confidence = max(0.0, min(1.0, confidence))

        return {
            "state": state,
            "confidence": confidence,
            "sources": sources,
            "conflicts": conflicts,
            "gaps": gaps,
        }

    def generate_confidence_prefix(self, state: KnowledgeState, confidence: float) -> str:
        if state == KnowledgeState.KNOW_VERIFIED:
            if confidence >= 0.8:
                return "Based on our verified documentation, "
            return "According to our records, "
        if state == KnowledgeState.KNOW_UNVERIFIED:
            return "Based on available information (not yet independently verified), "
        if state == KnowledgeState.PARTIAL:
            return "I have partial information on this. "
        if state == KnowledgeState.UNCERTAIN:
            return "I'm not entirely certain, but based on what I've found, "
        if state == KnowledgeState.CONFLICTING:
            return "I found conflicting information on this topic. "
        if state == KnowledgeState.UNKNOWN:
            return "I don't have reliable information on this. I'd recommend checking with the relevant team. "
        return ""

    async def log_knowledge_gap(
        self,
        query: str,
        state: KnowledgeState,
        gaps: list[str] | None = None,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO knowledge_gaps (query, state, gaps, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                query,
                state.value,
                json.dumps(gaps or []),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._db.commit()

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return "{}"

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
            logger.exception("LLM call failed in Metacognition")
            return "{}"

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> Metacognition:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
