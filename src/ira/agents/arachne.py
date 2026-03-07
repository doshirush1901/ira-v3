"""Arachne — Newsletter / Content agent.

Generates newsletter content, blog posts, industry roundups,
and other long-form marketing content.
Now operates via the ReAct loop with category-search, drafting,
and cross-agent delegation tools.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import ToolExecutionError
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("arachne_system")


class Arachne(BaseAgent):
    name = "arachne"
    role = "Newsletter / Content Creator"
    description = "Generates newsletters, blog posts, and long-form content"
    knowledge_categories = [
        "linkedin data",
        "presentations",
        "market_research_and_analysis",
    ]

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="search_linkedin_data",
            description="Search LinkedIn data for posts, engagement metrics, and social content.",
            parameters={"query": "Search query for LinkedIn data"},
            handler=self._tool_search_linkedin_data,
        ))

        self.register_tool(AgentTool(
            name="search_presentations",
            description="Search past presentations and slide decks for reference material.",
            parameters={"query": "Search query for presentations"},
            handler=self._tool_search_presentations,
        ))

        self.register_tool(AgentTool(
            name="search_market_research",
            description="Search market research and analysis reports.",
            parameters={"query": "Search query for market research"},
            handler=self._tool_search_market_research,
        ))

        self.register_tool(AgentTool(
            name="draft_newsletter",
            description="Draft a newsletter section or full newsletter on a given topic for a target audience.",
            parameters={
                "topic": "The newsletter topic",
                "audience": "Target audience (default 'industrial buyers')",
            },
            handler=self._tool_draft_newsletter,
        ))

        self.register_tool(AgentTool(
            name="ask_cadmus",
            description="Delegate to Cadmus for case-study material, LinkedIn post drafts, or content strategy.",
            parameters={"query": "The question or request for Cadmus"},
            handler=self._tool_ask_cadmus,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def _tool_search_linkedin_data(self, query: str) -> str:
        results = await self.search_category(query, "linkedin data")
        return self._format_context(results)

    async def _tool_search_presentations(self, query: str) -> str:
        results = await self.search_category(query, "presentations")
        return self._format_context(results)

    async def _tool_search_market_research(self, query: str) -> str:
        results = await self.search_category(query, "market_research_and_analysis")
        return self._format_context(results)

    async def _tool_draft_newsletter(self, topic: str, audience: str = "industrial buyers") -> str:
        return await self.call_llm(
            (
                "You are a professional newsletter writer for Machinecraft, "
                "a company that builds industrial machinery. "
                "Write engaging, informative content tailored to the target audience."
            ),
            (
                f"Draft a newsletter section about: {topic}\n"
                f"Target audience: {audience}\n\n"
                "Include a compelling headline, 2-3 paragraphs of content, "
                "and a clear call-to-action."
            ),
        )

    async def _tool_ask_cadmus(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if pantheon is None:
            return "Pantheon not available — cannot reach Cadmus."
        cadmus = pantheon.get_agent("cadmus")
        if cadmus is None:
            return "Cadmus agent not found."
        try:
            return await cadmus.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Cadmus error: {exc}"
