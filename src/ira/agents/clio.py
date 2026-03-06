"""Clio — Researcher agent.

Searches the knowledge base and answers factual questions using
retrieved context.  Uses skills for document summarization, fact
extraction, and document comparison.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("clio_system")


class Clio(BaseAgent):
    name = "clio"
    role = "Research Director"
    description = "Searches the knowledge base and answers factual questions"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", "")

        if task == "summarize":
            return await self.use_skill(
                "summarize_document",
                text=ctx.get("text", query),
            )

        if task == "extract_facts":
            return await self.use_skill(
                "extract_key_facts",
                text=ctx.get("text", query),
            )

        if task == "compare":
            return await self.use_skill(
                "compare_documents",
                documents=ctx.get("documents", []),
            )

        if task == "search":
            return await self.use_skill(
                "search_knowledge_base",
                query=query,
                category=ctx.get("category"),
                limit=ctx.get("limit", 10),
            )

        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nKnowledge Base Context:\n{kb_context}",
        )
