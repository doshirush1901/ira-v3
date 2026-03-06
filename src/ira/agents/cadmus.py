"""Cadmus -- CMO / Case Study agent.

Searches the knowledge base for relevant case studies, builds new
case studies from project data (with NDA-safe redaction), and drafts
LinkedIn posts grounded in Machinecraft's domain expertise.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("cadmus_system")


class Cadmus(BaseAgent):
    name = "cadmus"
    role = "CMO / Case Studies"
    description = "Case study creation, LinkedIn content, and marketing storytelling"

    async def find_case_studies(self, query: str) -> str:
        results = await self.search_knowledge(query, limit=10)
        if not results:
            return "No case studies found matching that query."

        lines = [f"Found {len(results)} relevant knowledge-base entries:\n"]
        for r in results:
            source = r.get("source", "unknown")
            content = r.get("content", "")[:600]
            lines.append(f"- [{source}] {content}")
        return "\n".join(lines)

    async def build_case_study(self, project_name: str, context: dict) -> str:
        kb_results = await self.search_knowledge(project_name, limit=12)
        kb_context = self._format_context(kb_results)

        nda_safe = context.get("nda_safe", False)
        nda_instruction = (
            "IMPORTANT: This case study must be NDA-safe. Replace the actual "
            "customer name with a generic descriptor (e.g. 'a leading Middle-Eastern "
            "construction firm'). Remove any proprietary pricing, contract values, "
            "or confidential technical details."
            if nda_safe
            else "You may use the full customer and project name."
        )

        prompt = (
            f"Build a professional case study for project: {project_name}\n\n"
            f"{nda_instruction}\n\n"
            "Structure the case study with these sections:\n"
            "1. Challenge — what problem the customer faced\n"
            "2. Solution — what Machinecraft delivered\n"
            "3. Results — measurable outcomes and benefits\n"
            "4. Key machines / technology used\n\n"
            f"Knowledge Base Context:\n{kb_context}"
        )
        return await self.call_llm(_SYSTEM_PROMPT, prompt)

    async def draft_linkedin_post(self, topic: str) -> str:
        kb_results = await self.search_knowledge(topic, limit=8)
        kb_context = self._format_context(kb_results)

        prompt = (
            f"Draft a LinkedIn post about: {topic}\n\n"
            "Guidelines:\n"
            "- Professional but engaging tone suitable for LinkedIn\n"
            "- 150-250 words\n"
            "- Include a hook in the first line\n"
            "- End with a call to action or thought-provoking question\n"
            "- Use line breaks for readability\n"
            "- No hashtag spam — 3-5 relevant hashtags maximum\n\n"
            f"Knowledge Base Context:\n{kb_context}"
        )
        return await self.call_llm(_SYSTEM_PROMPT, prompt, temperature=0.6)

    # ── BaseAgent interface ───────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if ctx.get("task") == "case_study":
            return await self.build_case_study(
                project_name=ctx.get("project_name", query),
                context=ctx,
            )
        if ctx.get("task") == "linkedin":
            return await self.use_skill(
                "generate_social_post",
                topic=ctx.get("topic", query),
                platform="linkedin",
            )
        if ctx.get("task") == "social_post":
            return await self.use_skill(
                "generate_social_post",
                topic=ctx.get("topic", query),
                platform=ctx.get("platform", "linkedin"),
            )

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nKnowledge Base:\n{kb_context}",
        )
