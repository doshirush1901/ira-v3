"""Iris — External Intelligence agent.

Gathers real-time information from the web, news APIs, and external
sources to enrich internal knowledge.
Now operates via the ReAct loop with web-search, news-fetch, scrape,
and internal-knowledge tools.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.config import get_settings
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("iris_system")


class Iris(BaseAgent):
    name = "iris"
    role = "External Intelligence"
    description = "Web search, news monitoring, and external research"
    knowledge_categories = [
        "market_research_and_analysis",
        "industry_knowledge",
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._newsdata_key = get_settings().external_apis.api_key.get_secret_value()

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="fetch_news",
            description="Fetch recent news articles related to a topic via the NewsData API.",
            parameters={"query": "News search query"},
            handler=self._tool_fetch_news,
        ))

        self.register_tool(AgentTool(
            name="search_internal_knowledge",
            description="Search Iris's domain knowledge categories (market research, industry knowledge).",
            parameters={"query": "Internal knowledge search query"},
            handler=self._tool_search_internal_knowledge,
        ))
        self.register_tool(AgentTool(
            name="search_knowledge_base_skill",
            description="Search the broader internal knowledge base through canonical skill routing.",
            parameters={"query": "Search query"},
            handler=self._tool_search_knowledge_base_skill,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def _tool_fetch_news(self, query: str) -> str:
        articles = await self._fetch_news(query)
        if not articles:
            if not self._newsdata_key:
                return "News unavailable — NEWSDATA_API_KEY not configured."
            return "No news articles found."
        return "\n".join(f"- {a}" for a in articles)

    async def _tool_search_internal_knowledge(self, query: str) -> str:
        results = await self.search_domain_knowledge(query)
        return self._format_context(results)

    async def _tool_search_knowledge_base_skill(self, query: str) -> str:
        return await self.use_skill("search_knowledge_base", query=query)

    async def _fetch_news(self, query: str) -> list[str]:
        if not self._newsdata_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://newsdata.io/api/1/news",
                    params={"apikey": self._newsdata_key, "q": query, "language": "en"},
                )
                resp.raise_for_status()
                return [
                    f"{a['title']} — {a.get('source_id', '')}"
                    for a in resp.json().get("results", [])
                    if a.get("title")
                ]
        except (httpx.HTTPError, KeyError):
            return []
