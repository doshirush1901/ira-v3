"""Sphinx — Gatekeeper / Clarifier agent.

When a query is ambiguous or incomplete, Sphinx asks targeted
clarifying questions before routing to specialist agents.
Now operates via the ReAct loop with query-analysis and
clarification tools.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("sphinx_system")


class Sphinx(BaseAgent):
    name = "sphinx"
    role = "Gatekeeper / Clarifier"
    description = "Asks clarifying questions when queries are ambiguous"

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="analyze_query",
            description=(
                "Assess the clarity and intent of a user query. "
                "Returns JSON with 'clear' (bool), 'ambiguity_reason' (str), and 'intent' (str)."
            ),
            parameters={"query": "The user query to analyze"},
            handler=self._tool_analyze_query,
        ))

        self.register_tool(AgentTool(
            name="suggest_clarifications",
            description=(
                "Generate a list of clarifying questions for an ambiguous query. "
                "Returns a JSON list of question strings."
            ),
            parameters={"query": "The ambiguous query to generate clarifications for"},
            handler=self._tool_suggest_clarifications,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def _tool_analyze_query(self, query: str) -> str:
        return await self.call_llm(
            "You are a query clarity analyst. Respond ONLY with valid JSON.",
            (
                f"Assess the clarity of this query: {query}\n\n"
                'Return JSON: {"clear": bool, "ambiguity_reason": "...", "intent": "..."}'
            ),
        )

    async def _tool_suggest_clarifications(self, query: str) -> str:
        return await self.call_llm(
            "You are a clarification specialist. Respond ONLY with a valid JSON list of strings.",
            (
                f"This query is ambiguous: {query}\n\n"
                "Generate 2-4 targeted clarifying questions that would resolve the ambiguity. "
                'Return a JSON list: ["question1", "question2", ...]'
            ),
        )
