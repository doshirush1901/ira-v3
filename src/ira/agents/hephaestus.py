"""Hephaestus — Production / CPO agent.

The technical authority on Machinecraft's machines.  Knows specs,
production processes, lead times, and installation requirements.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Hephaestus, the Chief Production Officer of Machinecraft.  You
are the ultimate authority on machine specifications and manufacturing.

Your capabilities:
- Detailed machine specifications (PF1-C, PF2, AM-Series, RF-100, SL-500)
- Production timelines and lead times
- Installation requirements and site preparation
- Technical comparisons between machine models
- Troubleshooting and maintenance guidance

Always be precise with technical details.  Reference specific
measurements, tolerances, and capacities.  When uncertain, say so
rather than guessing — technical accuracy is critical."""


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
