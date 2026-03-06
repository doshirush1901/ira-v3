"""Clio — Researcher agent.

Searches the knowledge base and answers factual questions using
retrieved context.  Clio is the primary agent for information retrieval.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("clio_system")


class Clio(BaseAgent):
    name = "clio"
    role = "Research Director"
    description = "Searches the knowledge base and answers factual questions"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nKnowledge Base Context:\n{kb_context}",
        )
