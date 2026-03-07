"""Vera — Fact Checker agent.

Verifies claims and statements against the knowledge base,
flagging inaccuracies and providing corrections.
Now operates via the ReAct loop with knowledge-search and
external-verification tools.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import ToolExecutionError
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("vera_system")


class Vera(BaseAgent):
    name = "vera"
    role = "Fact Checker"
    description = "Verifies claims against the knowledge base"

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="search_qdrant",
            description=(
                "Search the internal knowledge base for evidence to verify a claim. "
                "Optionally filter by category."
            ),
            parameters={
                "query": "Search query for verification evidence",
                "category": "Optional knowledge category to filter by (leave empty for all)",
            },
            handler=self._tool_search_qdrant,
        ))

        self.register_tool(AgentTool(
            name="ask_iris",
            description="Delegate to Iris for external web/news verification of a claim.",
            parameters={"query": "The claim or question to verify externally"},
            handler=self._tool_ask_iris,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def _tool_search_qdrant(self, query: str, category: str = "") -> str:
        if category.strip():
            results = await self._retriever.search_by_category(query, category.strip())
        else:
            results = await self._retriever.search(query)
        return self._format_context(results)

    async def _tool_ask_iris(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if pantheon is None:
            return "Pantheon not available — cannot reach Iris."
        iris = pantheon.get_agent("iris")
        if iris is None:
            return "Iris agent not found."
        try:
            return await iris.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Iris error: {exc}"
