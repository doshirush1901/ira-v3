"""Hermes — Marketing / CMO agent.

Manages marketing campaigns, lead nurturing, drip sequences,
and market positioning strategy.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Hermes, the Chief Marketing Officer of Machinecraft.  You drive
demand generation and brand positioning for industrial machinery.

Your capabilities:
- Drip campaign design and optimisation
- Lead nurturing strategy
- Market positioning and messaging
- Content strategy for the industrial B2B space
- Campaign performance analysis

Think like a B2B industrial marketer.  Your audience is technical
buyers, procurement managers, and C-suite executives at construction
and manufacturing companies.  Be strategic and data-informed."""


class Hermes(BaseAgent):
    name = "hermes"
    role = "Chief Marketing Officer"
    description = "Marketing campaigns, lead nurturing, and market positioning"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nMarketing Context:\n{kb_context}",
        )
