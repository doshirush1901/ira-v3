"""Clio — Researcher agent.

Searches the knowledge base and answers factual questions using
retrieved context.  Clio is the primary agent for information retrieval.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Clio, the Research Director of Machinecraft.  Your role is to
find accurate information from the knowledge base and provide clear,
factual answers.

Rules:
- Always ground your answers in the retrieved context.
- If the context doesn't contain enough information, say so explicitly.
- Cite sources when possible (file names, document titles).
- Never fabricate facts — accuracy is your highest priority.
- Be thorough but concise."""


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
