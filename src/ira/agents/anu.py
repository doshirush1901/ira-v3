"""Anu — AI Recruiter Agent.

Resume ingestion (PDF → structured profile), candidate scoring,
mentor-style chat, and profile export (summary → PDF).
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from datetime import datetime, timezone

from ira.agents.base_agent import BaseAgent
from ira.data.recruitment_scoring import get_dimensions
from ira.prompt_loader import load_prompt
from ira.schemas.anu_outputs import (
    ApplicantScore,
    CandidateScore,
    ParsedCandidate,
    ScoringDimension,
)

logger = logging.getLogger(__name__)


def _pdf_bytes_to_text(data: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    try:
        reader = PdfReader(BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return ""


class Anu(BaseAgent):
    name = "anu"
    role = "AI Recruiter"
    description = "Resume parsing, candidate scoring, career mentor chat, and profile export"
    knowledge_categories = ["hr data", "company_internal"]

    def _register_tools(self) -> None:
        # Anu is primarily used via API (parse, score, chat, export); no ReAct tools required for MVP
        pass

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Handle a natural-language query about recruitment (e.g. 'score this candidate')."""
        return await self.run(query, context or {})

    async def get_hr_recruitment_context(self, max_chars: int = 4000) -> str:
        """Pull context from 22_HR Data / HR docs (org structure, recruitment strategy, role requirements) for scoring and export."""
        queries = [
            "recruitment strategy CAD design engineer Machinecraft requirements",
            "org structure Machinecraft Technologies roles",
            "HR Machinecraft salary mock test evaluation",
        ]
        combined: list[str] = []
        seen: set[str] = set()
        for q in queries:
            try:
                results = await self.search_knowledge(q, limit=4)
                for r in results:
                    text = (r.get("text") or r.get("content") or "").strip()
                    if text and text[:80] not in seen:
                        seen.add(text[:80])
                        combined.append(text[:1500])
            except Exception as e:
                logger.debug("Anu get_hr_recruitment_context search failed for %r: %s", q, e)
        out = "\n\n".join(combined)[:max_chars]
        return out

    # ── Resume ingestion ───────────────────────────────────────────────────

    async def parse_resume_from_pdf_bytes(self, pdf_bytes: bytes) -> ParsedCandidate:
        """Extract text from PDF and parse into structured candidate profile."""
        text = _pdf_bytes_to_text(pdf_bytes)
        if not text.strip():
            return ParsedCandidate()

        prompt = load_prompt("anu_parse_resume").format(resume_text=text[:15000])
        try:
            out = await self._llm.generate_structured(
                system="You extract structured candidate information from resume text. Output valid JSON only.",
                user=prompt,
                response_model=ParsedCandidate,
                max_tokens=1500,
                name="anu_parse_resume",
            )
            return out
        except Exception as e:
            logger.exception("Anu parse_resume failed: %s", e)
            return ParsedCandidate()

    async def parse_resume_from_text(self, resume_text: str) -> ParsedCandidate:
        """Parse plain resume text into structured profile."""
        if not resume_text.strip():
            return ParsedCandidate()
        prompt = load_prompt("anu_parse_resume").format(resume_text=resume_text[:15000])
        try:
            return await self._llm.generate_structured(
                system="You extract structured candidate information from resume text. Output valid JSON only.",
                user=prompt,
                response_model=ParsedCandidate,
                max_tokens=1500,
                name="anu_parse_resume",
            )
        except Exception as e:
            logger.exception("Anu parse_resume failed: %s", e)
            return ParsedCandidate()

    # ── Candidate scoring ───────────────────────────────────────────────────

    async def score_candidate(
        self,
        candidate_profile: dict[str, Any] | ParsedCandidate,
        job_description: str = "",
        company_context: str | None = None,
    ) -> CandidateScore:
        """Score candidate fit (1-5) with optional job description and company context from 22_HR Data."""
        if isinstance(candidate_profile, ParsedCandidate):
            profile_str = candidate_profile.model_dump_json(indent=2)
        else:
            profile_str = json.dumps(candidate_profile, indent=2)

        if company_context is None:
            company_context = await self.get_hr_recruitment_context()
        prompt_text = load_prompt("anu_score").format(
            candidate_profile=profile_str,
            job_description=job_description or "(No job description provided — rate general employability.)",
            company_context=company_context or "(No company context retrieved.)",
        )
        try:
            return await self._llm.generate_structured(
                system="You are Anu, an AI recruiter. Output only the requested structured score and rationale.",
                user=prompt_text,
                response_model=CandidateScore,
                max_tokens=800,
                name="anu_score_candidate",
            )
        except Exception as e:
            logger.exception("Anu score_candidate failed: %s", e)
            return CandidateScore(score=0.0, label="Error", rationale=str(e))

    async def score_candidate_by_dimensions(
        self,
        candidate_profile: dict[str, Any] | ParsedCandidate,
        role_applied: str = "Procurement",
        stage2_response_text: str = "",
        dimensions: list[ScoringDimension] | None = None,
    ) -> ApplicantScore:
        """Score candidate on each dimension (from recruitment_scoring_system), then weighted overall. Saves scored_at."""
        if dimensions is None:
            dimensions = get_dimensions()
        if isinstance(candidate_profile, ParsedCandidate):
            profile_str = candidate_profile.model_dump_json(indent=2)
        else:
            profile_str = json.dumps(candidate_profile, indent=2)
        dimensions_text = "\n".join(
            f"- id: {d.id}, name: {d.name}, description: {d.description}, weight: {d.weight}"
            for d in dimensions
        )
        prompt_text = load_prompt("anu_score_dimensions").format(
            candidate_profile=profile_str,
            role_applied=role_applied or "Procurement",
            stage2_response_text=stage2_response_text or "(No Stage 2 response provided.)",
            dimensions_text=dimensions_text,
        )
        try:
            result = await self._llm.generate_structured(
                system="You are Anu, an AI recruiter. Output only the requested structured score (overall_score, label, rationale, strengths, gaps, dimension_scores with dimension_id, score, rationale for each).",
                user=prompt_text,
                response_model=ApplicantScore,
                max_tokens=1200,
                name="anu_score_dimensions",
            )
            result.scored_at = datetime.now(timezone.utc).isoformat()
            result.role_applied = role_applied or None
            return result
        except Exception as e:
            logger.exception("Anu score_candidate_by_dimensions failed: %s", e)
            return ApplicantScore(
                overall_score=1.0,
                label="Error",
                rationale=str(e),
                dimension_scores=[],
                scored_at=datetime.now(timezone.utc).isoformat(),
                role_applied=role_applied or None,
            )

    # ── Mentor chat ────────────────────────────────────────────────────────

    async def mentor_reply(
        self,
        candidate_profile: dict[str, Any] | ParsedCandidate,
        message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate a mentor-style reply given candidate profile and chat history."""
        if isinstance(candidate_profile, ParsedCandidate):
            profile_str = candidate_profile.model_dump_json(indent=2)
        else:
            profile_str = json.dumps(candidate_profile, indent=2)

        system = load_prompt("anu_mentor_system").format(candidate_profile=profile_str)

        history = conversation_history or []
        # Build user content: previous turns + current message
        parts = []
        for turn in history[-10:]:  # last 10 turns
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            else:
                parts.append(f"Anu: {content}")
        parts.append(f"User: {message}")

        user_content = "\n\n".join(parts)
        try:
            return await self._llm.generate_text(
                system=system,
                user=user_content,
                max_tokens=800,
                name="anu_mentor_chat",
            )
        except Exception as e:
            logger.exception("Anu mentor_reply failed: %s", e)
            return f"I couldn't generate a reply right now: {e}"

    # ── Profile export (summary text) ───────────────────────────────────────

    async def generate_profile_summary(
        self,
        candidate_profile: dict[str, Any] | ParsedCandidate,
        scoring: dict[str, Any] | CandidateScore | None = None,
    ) -> str:
        """Generate recruiter-ready summary text for PDF or display."""
        if isinstance(candidate_profile, ParsedCandidate):
            profile_str = candidate_profile.model_dump_json(indent=2)
        else:
            profile_str = json.dumps(candidate_profile, indent=2)

        if isinstance(scoring, CandidateScore):
            scoring_str = scoring.model_dump_json(indent=2)
        elif scoring:
            scoring_str = json.dumps(scoring, indent=2)
        else:
            scoring_str = "(No scoring data)"

        company_context = await self.get_hr_recruitment_context()
        prompt_text = load_prompt("anu_export_summary").format(
            candidate_profile=profile_str,
            scoring_context=scoring_str,
            company_context=company_context or "(None)",
        )
        try:
            return await self._llm.generate_text(
                system="You are Anu. Generate a concise, professional profile summary for hiring managers.",
                user=prompt_text,
                max_tokens=600,
                name="anu_export_summary",
            )
        except Exception as e:
            logger.exception("Anu generate_profile_summary failed: %s", e)
            return f"Summary generation failed: {e}"

    async def draft_recruitment_stage2(
        self,
        candidate_name: str,
        role: str,
        case_study_text: str,
        dice_questions: str,
        skills_questions: str,
        company_intro_short: str,
        job_description_or_context: str = "",
    ) -> dict[str, str]:
        """Generate Stage 2 recruitment email (subject + body) from prompt and inputs."""
        prompt_text = load_prompt("anu_recruitment_stage2_draft").format(
            candidate_name=candidate_name or "Candidate",
            role=role or "the role you applied for",
            case_study_text=case_study_text or "(No case study provided.)",
            dice_questions=dice_questions or "(No DICE questions provided.)",
            skills_questions=skills_questions or "(No skills questions provided.)",
            company_intro_short=company_intro_short or "Machinecraft Technologies (Umargam) is recruiting.",
            job_description_or_context=job_description_or_context or "(None provided — use the role name and general Umargam context above.)",
        )
        try:
            raw = await self._llm.generate_text(
                system="You are Anu. Output only the requested email: first line SUBJECT: <subject>, then blank line, then body. No preamble.",
                user=prompt_text,
                max_tokens=2500,
                name="anu_recruitment_stage2_draft",
            )
        except Exception as e:
            logger.exception("Anu draft_recruitment_stage2 failed: %s", e)
            return {"subject": "Re: Your application", "body": f"(Draft failed: {e})"}

        subject = "Re: Your application"
        body = raw
        if raw.strip().upper().startswith("SUBJECT:"):
            first_line, _, rest = raw.strip().partition("\n")
            subject = first_line[8:].strip()  # after "SUBJECT:"
            body = rest.lstrip() if rest else ""
        return {"subject": subject, "body": body}
