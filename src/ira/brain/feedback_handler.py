"""Real-time feedback processing for all Ira interfaces.

Detects positive, negative, and ambiguous feedback in user messages,
tracks per-agent success/failure scores, stores corrections in the
:class:`~ira.brain.correction_store.CorrectionStore`, and notifies the
:class:`~ira.systems.learning_hub.LearningHub` to trigger micro-learning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from ira.config import get_settings
from ira.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_SCORES_PATH = Path("data/brain/agent_scores.json")

_POSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bthanks?\b", re.IGNORECASE),
    re.compile(r"\bperfect\b", re.IGNORECASE),
    re.compile(r"\bexactly\b", re.IGNORECASE),
    re.compile(r"\bgreat\b", re.IGNORECASE),
    re.compile(r"\bcorrect\b", re.IGNORECASE),
    re.compile(r"\bgood\s+job\b", re.IGNORECASE),
    re.compile(r"\bwell\s+done\b", re.IGNORECASE),
    re.compile(r"\U0001F44D"),  # thumbs up
]

_NEGATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bthat'?s\s+not\s+right\b", re.IGNORECASE),
    re.compile(r"\bactually\s+it'?s\b", re.IGNORECASE),
    re.compile(r"\bthat'?s\s+incorrect\b", re.IGNORECASE),
    re.compile(r"\bnot\s+correct\b", re.IGNORECASE),
    re.compile(r"\bincorrect\b", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"^no[.,!?\s]", re.IGNORECASE),
    re.compile(r"^no$", re.IGNORECASE),
]

_DISAMBIGUATION_SYSTEM = (
    "You are a feedback-classification assistant. Given a user message, the "
    "previous query, and the previous response, determine whether the user is "
    "giving positive feedback, negative feedback (a correction), or something "
    "neutral (unrelated to feedback). Respond with ONLY a JSON object: "
    '{"polarity": "positive"|"negative"|"neutral", "confidence": 0.0-1.0, '
    '"extracted_correction": "<correction text or null>"}.'
)


class FeedbackHandler:
    """Detects and processes user feedback on agent responses."""

    def __init__(
        self,
        learning_hub: Any | None = None,
        correction_store: Any | None = None,
        mem0_client: Any | None = None,
        procedural_memory: Any | None = None,
    ) -> None:
        self._learning_hub = learning_hub
        self._correction_store = correction_store
        self._mem0_client = mem0_client
        self._procedural_memory = procedural_memory
        self._agent_scores: dict[str, dict[str, int]] = {}

    # ── public API ───────────────────────────────────────────────────────

    async def detect_feedback(
        self,
        message: str,
        previous_query: str,
        previous_response: str,
    ) -> dict[str, Any]:
        """Classify *message* as positive, negative, neutral, or ambiguous.

        Returns a dict with keys ``polarity``, ``confidence``, and
        ``extracted_correction``.
        """
        pos_hits = sum(1 for p in _POSITIVE_PATTERNS if p.search(message))
        neg_hits = sum(1 for p in _NEGATIVE_PATTERNS if p.search(message))

        if neg_hits > 0 and pos_hits == 0:
            correction = self._extract_correction(message)
            return {
                "polarity": "negative",
                "confidence": min(0.6 + neg_hits * 0.1, 1.0),
                "extracted_correction": correction,
            }

        if pos_hits > 0 and neg_hits == 0:
            return {
                "polarity": "positive",
                "confidence": min(0.6 + pos_hits * 0.1, 1.0),
                "extracted_correction": None,
            }

        if pos_hits > 0 and neg_hits > 0:
            return await self._disambiguate_with_llm(
                message, previous_query, previous_response
            )

        if self._looks_like_feedback(message):
            return await self._disambiguate_with_llm(
                message, previous_query, previous_response
            )

        return {
            "polarity": "neutral",
            "confidence": 0.8,
            "extracted_correction": None,
        }

    async def load_scores(self) -> None:
        """Public wrapper for loading persisted agent scores."""
        await self._load_scores()

    async def process_feedback(
        self,
        message: str,
        previous_query: str,
        previous_response: str,
        agents_used: list[str],
        *,
        user_id: str = "global",
    ) -> dict[str, Any]:
        """Full feedback pipeline: detect, score agents, store corrections, trigger learning."""
        result = await self.detect_feedback(message, previous_query, previous_response)
        polarity = result["polarity"]

        for agent in agents_used:
            self._update_agent_score(agent, polarity)

        if polarity == "negative" and result.get("extracted_correction"):
            correction_text = result["extracted_correction"]

            if self._correction_store is not None:
                try:
                    from ira.brain.correction_store import CorrectionSeverity
                    correction_id = await self._correction_store.add_correction(
                        entity=previous_query[:200],
                        new_value=correction_text,
                        severity=CorrectionSeverity.HIGH,
                        old_value=previous_response[:500],
                        source=f"feedback:{user_id}",
                    )
                    result["correction_id"] = correction_id
                except (DatabaseError, Exception):
                    logger.exception("Correction store failed")

            if self._mem0_client is not None:
                try:
                    self._mem0_client.add(
                        [
                            {
                                "role": "user",
                                "content": (
                                    f"Correction: {correction_text} "
                                    f"(original query: {previous_query})"
                                ),
                            }
                        ],
                        user_id=user_id or "global",
                    )
                except (DatabaseError, Exception):
                    logger.exception("Mem0 correction storage failed")

            if self._procedural_memory is not None:
                try:
                    await self._procedural_memory.record_failure(previous_query)
                except (DatabaseError, Exception):
                    logger.exception("ProceduralMemory failure recording failed")

            if self._learning_hub is not None:
                try:
                    await self._learning_hub.trigger_micro_learning_cycle()
                    result["micro_learning_triggered"] = True
                except (DatabaseError, Exception):
                    logger.exception("Micro-learning trigger failed")

        elif polarity == "positive":
            if self._procedural_memory is not None and agents_used:
                try:
                    await self._procedural_memory.learn_procedure(
                        previous_query, agents_used,
                    )
                    result["procedure_reinforced"] = True
                except (DatabaseError, Exception):
                    logger.exception("ProceduralMemory reinforcement failed")

        await self._persist_scores()
        return result

    def get_agent_scores(self) -> dict[str, dict[str, int]]:
        return dict(self._agent_scores)

    # ── pattern helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_correction(message: str) -> str | None:
        for pattern in (
            r"actually\s+it'?s\s+(.+)",
            r"no[,.]?\s+(?:it'?s|the answer is)\s+(.+)",
            r"that'?s\s+not\s+right[,.]?\s+(.+)",
        ):
            m = re.search(pattern, message, re.IGNORECASE)
            if m:
                return m.group(1).strip().rstrip(".")
        return message

    @staticmethod
    def _looks_like_feedback(message: str) -> bool:
        """Heuristic: short messages after a response are likely feedback."""
        return len(message.split()) <= 12

    # ── LLM disambiguation ───────────────────────────────────────────────

    async def _disambiguate_with_llm(
        self,
        message: str,
        previous_query: str,
        previous_response: str,
    ) -> dict[str, Any]:
        settings = get_settings()
        api_key = settings.llm.openai_api_key.get_secret_value()
        if not api_key:
            return {
                "polarity": "ambiguous",
                "confidence": 0.3,
                "extracted_correction": None,
            }

        user_content = (
            f"Previous query: {previous_query}\n"
            f"Previous response: {previous_response[:2000]}\n"
            f"User message: {message}"
        )
        payload = {
            "model": settings.llm.openai_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": _DISAMBIGUATION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                return json.loads(raw)
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError):
            logger.exception("LLM disambiguation failed")
            return {
                "polarity": "ambiguous",
                "confidence": 0.3,
                "extracted_correction": None,
            }

    # ── agent scoring ────────────────────────────────────────────────────

    def _update_agent_score(self, agent: str, polarity: str) -> None:
        if agent not in self._agent_scores:
            self._agent_scores[agent] = {"success": 0, "failure": 0}
        if polarity == "positive":
            self._agent_scores[agent]["success"] += 1
        elif polarity == "negative":
            self._agent_scores[agent]["failure"] += 1

    # ── persistence ──────────────────────────────────────────────────────

    async def _load_scores(self) -> None:
        if _SCORES_PATH.exists():
            try:
                raw = await asyncio.to_thread(_SCORES_PATH.read_text)
                self._agent_scores = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not load agent scores; starting fresh")
                self._agent_scores = {}

    async def _persist_scores(self) -> None:
        try:
            _SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._agent_scores, indent=2)
            await asyncio.to_thread(_SCORES_PATH.write_text, payload)
        except OSError:
            logger.exception("Failed to persist agent scores")
