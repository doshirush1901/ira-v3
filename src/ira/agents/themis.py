"""Themis — HR / CHRO agent.

Manages employee data, HR policies, headcount reporting,
and organisational questions.  Uses skills for employee lookup
and org chart generation.  Equipped with ReAct tools for
employee lookup, HR policy search, and org chart generation.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("themis_system")


class Themis(BaseAgent):
    name = "themis"
    role = "Chief Human Resources Officer"
    description = "Employee data, HR policies, and organisational management"
    knowledge_categories = [
        "hr data",
        "company_internal",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="lookup_employee",
            description="Look up employee information by name.",
            parameters={"name": "Employee name to look up"},
            handler=self._tool_lookup_employee,
        ))
        self.register_tool(AgentTool(
            name="search_hr_policies",
            description="Search internal HR policies and company documents.",
            parameters={"query": "Search query about HR policies"},
            handler=self._tool_search_hr_policies,
        ))
        self.register_tool(AgentTool(
            name="generate_org_chart",
            description="Generate an organisational chart, optionally for a specific department.",
            parameters={"department": "Department name (optional, empty for full org)"},
            handler=self._tool_generate_org_chart,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_lookup_employee(self, name: str) -> str:
        return await self.use_skill("lookup_employee", name=name)

    async def _tool_search_hr_policies(self, query: str) -> str:
        results = await self.search_category(query, "company_internal")
        if not results:
            return "No HR policy results found."
        return "\n".join(
            f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}"
            for r in results
        )

    async def _tool_generate_org_chart(self, department: str = "") -> str:
        return await self.use_skill("generate_org_chart", department=department)

    # ── handle ───────────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "lookup_employee":
            return await self.use_skill(
                "lookup_employee",
                name=ctx.get("name", query),
            )

        if action == "org_chart":
            return await self.use_skill(
                "generate_org_chart",
                department=ctx.get("department", ""),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)
