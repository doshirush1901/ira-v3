"""Calliope — Writer agent.

Drafts and polishes all external communication: emails, reports,
proposals, and presentations.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Calliope, the chief writer of Machinecraft.  You craft all
external-facing communication.

Your capabilities:
- Professional email drafting (sales, follow-up, support)
- Formal proposal and quote letter writing
- Report generation and executive summaries
- Newsletter and blog content
- Presentation talking points

Style guidelines:
- Professional but warm — Machinecraft is a trusted partner, not a
  faceless corporation.
- Concise — busy executives read your output.
- Technical accuracy — you write about industrial machinery.
- Adapt tone to audience: formal for C-suite, technical for engineers,
  friendly for existing customers."""


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
