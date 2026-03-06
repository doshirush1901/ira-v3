"""Calliope — Writer agent.

Drafts and polishes all external communication: emails, reports,
proposals, and presentations.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("calliope_system")


class Calliope(BaseAgent):
    name = "calliope"
    role = "Chief Writer"
    description = "Drafts emails, reports, proposals, and all external communication"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
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
