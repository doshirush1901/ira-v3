"""Themis — HR / CHRO agent.

Manages employee data, HR policies, headcount reporting,
and organisational questions.  Uses skills for employee lookup
and org chart generation.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("themis_system")


class Themis(BaseAgent):
    name = "themis"
    role = "Chief Human Resources Officer"
    description = "Employee data, HR policies, and organisational management"

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

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nHR Context:\n{kb_context}",
        )
