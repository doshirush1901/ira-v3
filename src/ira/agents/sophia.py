"""Sophia — Reflector / Learner agent.

Reviews past decisions and interactions to identify patterns,
suggest improvements, and surface lessons learned.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("sophia_system")


class Sophia(BaseAgent):
    name = "sophia"
    role = "Reflector / Learner"
    description = "Reviews past decisions and suggests improvements"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Reflection request: {query}\n\nHistorical Context:\n{kb_context}",
        )
