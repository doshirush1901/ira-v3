"""Iris — External Intelligence agent.

Gathers real-time information from the web, news APIs, and external
sources to enrich internal knowledge.
"""

from __future__ import annotations

from typing import Any

import httpx

from ira.agents.base_agent import BaseAgent
from ira.config import get_settings
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("iris_system")


class Iris(BaseAgent):
    name = "iris"
    role = "External Intelligence"
    description = "Web search, news monitoring, and external research"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._newsdata_key = get_settings().external_apis.api_key.get_secret_value()

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=5)
        news = await self._fetch_news(query)

        combined = self._format_context(kb_results)
        if news:
            combined += "\n\nRecent News:\n" + "\n".join(f"- {n}" for n in news)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Intelligence request: {query}\n\nContext:\n{combined}",
        )

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
