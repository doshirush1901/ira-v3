"""Hermes — Marketing / CMO agent.

Manages marketing campaigns, lead nurturing, drip sequences,
and market positioning strategy.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("hermes_system")


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
