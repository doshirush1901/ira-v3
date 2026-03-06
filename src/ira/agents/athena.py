"""Athena — CEO / Orchestrator agent.

Routes complex queries to the appropriate specialist agents, synthesises
multi-agent responses, and makes final decisions when agents disagree.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("athena_system")


class Athena(BaseAgent):
    name = "athena"
    role = "CEO / Orchestrator"
    description = "Routes queries and synthesises multi-agent responses"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if "agent_responses" in ctx:
            return await self._synthesise(query, ctx["agent_responses"])

        return await self._route(query, ctx)

    async def _route(self, query: str, context: dict[str, Any]) -> str:
        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\nContext: {context}",
        )

    async def _synthesise(self, query: str, responses: dict[str, str]) -> str:
        formatted = "\n\n".join(
            f"**{agent}**: {resp}" for agent, resp in responses.items()
        )
        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Original query: {query}\n\nAgent responses:\n{formatted}\n\n"
            "Synthesise these into a single coherent answer.",
        )
