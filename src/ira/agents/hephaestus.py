"""Hephaestus — Production / CPO agent.

The technical authority on Machinecraft's machines.  Knows specs,
production processes, lead times, and installation requirements.
Uses skills for machine spec lookup and production time estimation.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("hephaestus_system")


class Hephaestus(BaseAgent):
    name = "hephaestus"
    role = "Chief Production Officer"
    description = "Machine specifications, production processes, and technical details"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "machine_spec" or ctx.get("machine_model"):
            return await self.use_skill(
                "lookup_machine_spec",
                machine_model=ctx.get("machine_model", query),
            )

        if action == "production_time":
            return await self.use_skill(
                "estimate_production_time",
                machine_model=ctx.get("machine_model", ""),
                configuration=ctx.get("configuration", {}),
                quantity=ctx.get("quantity", 1),
            )

        kb_results = await self.search_category(
            query, category="machine_manuals_and_specs", limit=8,
        )
        general_results = await self.search_knowledge(query, limit=5)
        all_context = self._format_context(kb_results + general_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nTechnical Context:\n{all_context}",
        )
