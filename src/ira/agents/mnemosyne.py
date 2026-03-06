"""Mnemosyne — Memory Keeper agent.

Manages long-term memory storage and retrieval, ensuring important
information persists across conversations.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("mnemosyne_system")


class Mnemosyne(BaseAgent):
    name = "mnemosyne"
    role = "Memory Keeper"
    description = "Manages long-term memory storage and retrieval"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10, sources=["mem0"])
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Memory request: {query}\n\nStored Memories:\n{kb_context}",
        )
