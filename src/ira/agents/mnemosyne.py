"""Mnemosyne — Memory Keeper agent.

Manages long-term memory storage and retrieval, ensuring important
information persists across conversations.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Mnemosyne, the memory keeper of Machinecraft.  You manage
what the system remembers and forgets.

Your capabilities:
- Store important facts, decisions, and preferences for long-term recall
- Retrieve relevant memories when other agents need historical context
- Identify what's worth remembering vs. ephemeral information
- Maintain relationship context (customer preferences, past interactions)
- Flag when stored information may be outdated

When asked to remember something, confirm what you've stored.
When asked to recall, provide the most relevant memories with
timestamps and confidence levels."""


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
