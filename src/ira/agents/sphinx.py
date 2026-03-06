"""Sphinx — Gatekeeper / Clarifier agent.

When a query is ambiguous or incomplete, Sphinx asks targeted
clarifying questions before routing to specialist agents.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("sphinx_system")


class Sphinx(BaseAgent):
    name = "sphinx"
    role = "Gatekeeper / Clarifier"
    description = "Asks clarifying questions when queries are ambiguous"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Evaluate this query:\n{query}",
        )
