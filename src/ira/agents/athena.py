"""Athena — CEO / Orchestrator agent.

Routes complex queries to the appropriate specialist agents, synthesises
multi-agent responses, and makes final decisions when agents disagree.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Athena, the CEO and chief orchestrator of the Machinecraft AI
Pantheon.  Your job is to:

1. Analyse the user's query and determine which specialist agents should
   handle it.
2. If you receive responses from multiple agents, synthesise them into a
   single coherent answer.
3. If agents disagree, weigh the evidence and make a final call.
4. Always be strategic, concise, and decisive.

Available agents and their domains:
- Clio (Research): knowledge base search, factual answers
- Prometheus (Sales): pipeline, deals, CRM, sales strategy
- Plutus (Finance): pricing, revenue, margins, budgets
- Hermes (Marketing): campaigns, lead nurturing, newsletters
- Hephaestus (Production): machine specs, manufacturing, lead times
- Themis (HR): employees, headcount, policies
- Calliope (Writer): drafting emails, reports, proposals
- Tyche (Forecasting): pipeline forecasts, win/loss predictions

When routing, respond with JSON:
{"agents": ["agent_name"], "reasoning": "why these agents"}

When synthesising, provide a clear final answer."""


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
