"""Hephaestus — Production / CPO agent.

The technical authority on Machinecraft's machines.  Knows specs,
production processes, lead times, and installation requirements.
Uses skills for machine spec lookup and production time estimation.
Equipped with ReAct tools for manual search, spec lookup,
production estimation, and cross-agent delegation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("hephaestus_system")


class Hephaestus(BaseAgent):
    name = "hephaestus"
    role = "Chief Production Officer"
    description = "Machine specifications, production processes, and technical details"
    knowledge_categories = [
        "machine_manuals_and_specs",
        "production",
        "product_catalogues",
        "orders_and_pos",
        "current machine orders",
        "industry_knowledge",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="lookup_machine_spec",
            description="Look up the full specification sheet for a machine model.",
            parameters={"model": "Machine model name or identifier"},
            handler=self._tool_lookup_machine_spec,
        ))
        self.register_tool(AgentTool(
            name="estimate_production_time",
            description="Estimate production/lead time for a machine order.",
            parameters={
                "model": "Machine model name",
                "quantity": "Number of units (default 1)",
            },
            handler=self._tool_estimate_production_time,
        ))
        self.register_tool(AgentTool(
            name="search_manuals",
            description="Search machine manuals and technical specifications.",
            parameters={"query": "Search query"},
            handler=self._tool_search_manuals,
        ))
        self.register_tool(AgentTool(
            name="ask_asclepius",
            description="Delegate a question to Asclepius, the quality/punch-list agent.",
            parameters={"query": "Question for Asclepius"},
            handler=self._tool_ask_asclepius,
        ))
        self.register_tool(AgentTool(
            name="ask_atlas",
            description="Delegate a question to Atlas, the project manager agent.",
            parameters={"query": "Question for Atlas"},
            handler=self._tool_ask_atlas,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_lookup_machine_spec(self, model: str) -> str:
        return await self.use_skill("lookup_machine_spec", machine_model=model)

    async def _tool_estimate_production_time(
        self, model: str, quantity: str = "1",
    ) -> str:
        return await self.use_skill(
            "estimate_production_time",
            machine_model=model,
            quantity=int(quantity),
        )

    async def _tool_search_manuals(self, query: str) -> str:
        results = await self.search_category(query, "machine_manuals_and_specs")
        if not results:
            return "No manual/spec results found."
        return "\n".join(
            f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}"
            for r in results
        )

    async def _tool_ask_asclepius(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("asclepius")
        if agent is None:
            return "Asclepius agent not found."
        try:
            return await agent.handle(query)
        except Exception as exc:
            return f"Asclepius error: {exc}"

    async def _tool_ask_atlas(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("atlas")
        if agent is None:
            return "Atlas agent not found."
        try:
            return await agent.handle(query)
        except Exception as exc:
            return f"Atlas error: {exc}"

    # ── handle ───────────────────────────────────────────────────────────

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

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)
