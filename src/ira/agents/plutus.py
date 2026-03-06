"""Plutus — Finance / CFO agent.

Handles financial analysis, pricing review, margin calculations,
and budget oversight.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("plutus_system")


class Plutus(BaseAgent):
    name = "plutus"
    role = "Chief Financial Officer"
    description = "Financial analysis, pricing review, and budget oversight"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_category(
            query, category="quotes_and_proposals", limit=8,
        )
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nFinancial Context:\n{kb_context}",
        )
