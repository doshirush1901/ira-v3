"""Learning hub — feedback processing, gap analysis, and procedure suggestion.

Closes the feedback loop for the Ira system.  After every interaction the
LearningHub can:

* Record and analyse user feedback (scores + optional corrections).
* Identify skill or knowledge gaps from poorly-rated interactions.
* Suggest new procedures for ProceduralMemory based on successful or
  corrected interactions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ira.config import LLMConfig, get_settings
from ira.data.crm import CRMDatabase
from ira.memory.procedural import Procedure, ProceduralMemory
from ira.skills import SKILL_MATRIX

logger = logging.getLogger(__name__)

_FEEDBACK_THRESHOLD_POOR = 3
_FEEDBACK_THRESHOLD_GOOD = 7

_GAP_ANALYSIS_PROMPT = """\
You are a skill-gap analyst for an AI assistant called Ira that serves an
industrial machinery company (Machinecraft).

Given the interaction below (query, response, and feedback), determine
whether the poor rating was caused by:

1. A MISSING SKILL — Ira lacks a capability she should have.
2. A KNOWLEDGE GAP — Ira had the skill but lacked the data / context.
3. A QUALITY ISSUE — Ira had the skill and data but the output was poor.

Return ONLY valid JSON (no markdown fences):
{
  "gap_type": "MISSING_SKILL" | "KNOWLEDGE_GAP" | "QUALITY_ISSUE",
  "description": "<one-sentence explanation>",
  "suggested_skill_name": "<snake_case name or null>",
  "suggested_skill_description": "<what the skill should do, or null>",
  "suggested_knowledge_source": "<where to find the missing data, or null>"
}"""

_CORRECTION_ANALYSIS_PROMPT = """\
You are a correction analyst for an AI assistant called Ira.

Compare the ORIGINAL response with the USER CORRECTION and produce a
concise diff summary explaining what was wrong and what the correct
behaviour should be.

Return ONLY valid JSON (no markdown fences):
{
  "error_category": "FACTUAL" | "TONE" | "FORMATTING" | "INCOMPLETE" | "WRONG_AGENT",
  "what_was_wrong": "<one sentence>",
  "correct_behaviour": "<one sentence describing the ideal response>"
}"""

_PROCEDURE_EXTRACTION_PROMPT = """\
You are a procedure extraction engine for an AI assistant called Ira.

Given a successful interaction (query + response), extract a reusable
step-by-step procedure that Ira should follow for similar future requests.

Return ONLY a JSON array of step strings (no markdown fences):
["Step 1: ...", "Step 2: ...", ...]"""


@dataclass
class FeedbackRecord:
    interaction_id: str
    feedback_score: int
    correction: str | None = None
    correction_analysis: dict[str, Any] = field(default_factory=dict)
    gap_analysis: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LearningHub:
    """Processes feedback, identifies gaps, and suggests procedures."""

    def __init__(
        self,
        crm: CRMDatabase,
        procedural_memory: ProceduralMemory,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._crm = crm
        self._procedural = procedural_memory

        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model

        self._recent_feedback: list[FeedbackRecord] = []

    # ── public API ────────────────────────────────────────────────────────

    async def process_feedback(
        self,
        interaction_id: str,
        feedback_score: int,
        correction: str | None = None,
    ) -> FeedbackRecord:
        """Log feedback against an interaction and analyse any correction.

        Parameters
        ----------
        interaction_id:
            UUID of the CRM interaction to annotate.
        feedback_score:
            1-10 rating (1 = terrible, 10 = perfect).
        correction:
            Optional free-text showing what the response *should* have been.

        Returns
        -------
        FeedbackRecord with analysis results attached.
        """
        interaction = await self._crm.get_interaction(interaction_id)
        if interaction is None:
            logger.warning("Interaction %s not found in CRM", interaction_id)

        record = FeedbackRecord(
            interaction_id=interaction_id,
            feedback_score=feedback_score,
            correction=correction,
        )

        original_content = (
            interaction.content if interaction is not None else None
        )

        if correction and original_content:
            record.correction_analysis = await self._analyse_correction(
                original_content, correction,
            )

        if feedback_score <= _FEEDBACK_THRESHOLD_POOR:
            query = interaction.subject if interaction else "(unknown query)"
            response = original_content or "(no response recorded)"
            record.gap_analysis = await self._analyse_gap(
                query, response, feedback_score, correction,
            )
            await self._procedural.record_failure(
                query if isinstance(query, str) else str(query),
            )

        self._recent_feedback.append(record)
        logger.info(
            "Feedback recorded: interaction=%s score=%d has_correction=%s",
            interaction_id,
            feedback_score,
            correction is not None,
        )
        return record

    async def identify_skill_gap(
        self,
        interaction_id: str,
    ) -> dict[str, Any]:
        """Analyse a poorly-rated interaction and suggest a new skill or procedure.

        Returns a dict with ``gap_type``, ``description``, and either a
        ``suggested_skill_name`` or ``suggested_knowledge_source``.
        """
        interaction = await self._crm.get_interaction(interaction_id)
        if interaction is None:
            return {"error": f"Interaction {interaction_id} not found"}

        query = interaction.subject or "(unknown query)"
        response = interaction.content or "(no response recorded)"

        gap = await self._analyse_gap(query, response, feedback_score=1)

        skill_name = gap.get("suggested_skill_name")
        if skill_name and skill_name in SKILL_MATRIX:
            gap["skill_already_exists"] = True
            gap["existing_description"] = SKILL_MATRIX[skill_name]

        return gap

    async def suggest_procedure(
        self,
        interaction_id: str,
    ) -> Procedure | None:
        """Create a new ProceduralMemory entry from a successful interaction.

        Works for both organically successful interactions and corrected
        ones (where the correction becomes the canonical response path).
        """
        interaction = await self._crm.get_interaction(interaction_id)
        if interaction is None:
            logger.warning(
                "Cannot suggest procedure — interaction %s not found",
                interaction_id,
            )
            return None

        query = interaction.subject or "(unknown query)"
        response = interaction.content or ""

        corrected = self._find_correction_for(interaction_id)
        if corrected and corrected.correction:
            response = corrected.correction

        steps = await self._extract_procedure_steps(str(query), response)
        if not steps:
            return None

        procedure = await self._procedural.learn_procedure(
            str(query), steps,
        )
        logger.info(
            "Procedure suggested from interaction %s: pattern='%s' (%d steps)",
            interaction_id,
            procedure.trigger_pattern,
            len(procedure.steps),
        )
        return procedure

    def get_weak_areas(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most problematic areas based on recent feedback.

        Each entry contains the interaction_id, score, gap_analysis, and
        correction_analysis from a poorly-rated interaction.  Results are
        sorted worst-first.
        """
        poor = [
            r for r in self._recent_feedback
            if r.feedback_score <= _FEEDBACK_THRESHOLD_POOR
        ]
        poor.sort(key=lambda r: r.feedback_score)
        return [
            {
                "interaction_id": r.interaction_id,
                "score": r.feedback_score,
                "gap_analysis": r.gap_analysis,
                "correction_analysis": r.correction_analysis,
            }
            for r in poor[:limit]
        ]

    def get_all_feedback(self) -> list[FeedbackRecord]:
        """Return all recorded feedback (most recent last)."""
        return list(self._recent_feedback)

    # ── internal helpers ──────────────────────────────────────────────────

    def _find_correction_for(self, interaction_id: str) -> FeedbackRecord | None:
        for record in reversed(self._recent_feedback):
            if record.interaction_id == interaction_id and record.correction:
                return record
        return None

    async def _analyse_correction(
        self,
        original: str,
        correction: str,
    ) -> dict[str, Any]:
        prompt = (
            f"ORIGINAL RESPONSE:\n{original[:4000]}\n\n"
            f"USER CORRECTION:\n{correction[:4000]}"
        )
        raw = await self._llm_call(_CORRECTION_ANALYSIS_PROMPT, prompt)
        return self._safe_parse_json(raw)

    async def _analyse_gap(
        self,
        query: str,
        response: str,
        feedback_score: int,
        correction: str | None = None,
    ) -> dict[str, Any]:
        parts = [
            f"QUERY: {query[:2000]}",
            f"RESPONSE: {response[:4000]}",
            f"FEEDBACK SCORE: {feedback_score}/10",
        ]
        if correction:
            parts.append(f"USER CORRECTION: {correction[:2000]}")
        prompt = "\n\n".join(parts)
        raw = await self._llm_call(_GAP_ANALYSIS_PROMPT, prompt)
        return self._safe_parse_json(raw)

    async def _extract_procedure_steps(
        self,
        query: str,
        response: str,
    ) -> list[str]:
        prompt = f"QUERY: {query[:2000]}\n\nRESPONSE: {response[:6000]}"
        raw = await self._llm_call(_PROCEDURE_EXTRACTION_PROMPT, prompt)
        parsed = self._safe_parse_json(raw)
        if isinstance(parsed, list):
            return [str(s) for s in parsed]
        return []

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return "(No OpenAI key configured)"

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
                    headers={
                        "Authorization": f"Bearer {self._openai_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError):
            logger.exception("LLM call failed in LearningHub")
            return "(LLM call failed)"

    @staticmethod
    def _safe_parse_json(raw: str) -> Any:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return {"raw_response": raw}
