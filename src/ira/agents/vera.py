"""Vera — Fact Checker agent.

Verifies claims and statements against the knowledge base,
flagging inaccuracies and providing corrections.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("vera_system")


class Vera(BaseAgent):
    name = "vera"
    role = "Fact Checker"
    description = "Verifies claims against the knowledge base"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Claim to verify:\n{query}\n\nKnowledge Base Evidence:\n{kb_context}",
        )
