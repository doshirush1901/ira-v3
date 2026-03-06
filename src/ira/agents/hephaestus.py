"""Hephaestus — Production / CPO agent.

The technical authority on Machinecraft's machines.  Knows specs,
production processes, lead times, and installation requirements.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("hephaestus_system")


class Hephaestus(BaseAgent):
    name = "hephaestus"
    role = "Chief Production Officer"
    description = "Machine specifications, production processes, and technical details"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_category(
            query, category="machine_manuals_and_specs", limit=8,
        )
        general_results = await self.search_knowledge(query, limit=5)
        all_context = self._format_context(kb_results + general_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nTechnical Context:\n{all_context}",
        )
