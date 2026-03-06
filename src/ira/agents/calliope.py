"""Calliope — Writer agent.

Drafts and polishes all external communication: emails, reports,
proposals, and presentations.  Uses skills for polishing, translation,
and proposal generation.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("calliope_system")


class Calliope(BaseAgent):
    name = "calliope"
    role = "Chief Writer"
    description = "Drafts emails, reports, proposals, and all external communication"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", ctx.get("draft_type", ""))

        if task == "proposal":
            return await self.use_skill(
                "draft_proposal",
                customer=ctx.get("recipient", ctx.get("customer", "")),
                machine_model=ctx.get("machine_model", ""),
                context=query,
            )

        if task == "polish":
            return await self.use_skill(
                "polish_text",
                text=query,
                tone=ctx.get("tone", "professional"),
            )

        if task == "translate":
            return await self.use_skill(
                "translate_text",
                text=query,
                language=ctx.get("language", ctx.get("target_language", "")),
            )

        if task == "meeting_notes":
            return await self.use_skill(
                "generate_meeting_notes",
                transcript=query,
                attendees=ctx.get("attendees", []),
            )

        extra = ""
        if "draft_type" in ctx:
            extra = f"\nDocument type: {ctx['draft_type']}"
        if "recipient" in ctx:
            extra += f"\nRecipient: {ctx['recipient']}"
        if "tone" in ctx:
            extra += f"\nTone: {ctx['tone']}"

        kb_results = await self.search_knowledge(query, limit=5)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Writing request: {query}{extra}\n\nReference material:\n{kb_context}",
        )
