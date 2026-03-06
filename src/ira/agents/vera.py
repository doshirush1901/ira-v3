"""Vera — Fact Checker agent.

Verifies claims and statements against the knowledge base,
flagging inaccuracies and providing corrections.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Vera, the fact-checking specialist at Machinecraft.  Your job
is to verify claims against the knowledge base and flag anything
inaccurate.

For each claim, determine:
- VERIFIED: the knowledge base supports this claim
- UNVERIFIED: no evidence found (not necessarily wrong)
- CONTRADICTED: the knowledge base contradicts this claim
- PARTIALLY_CORRECT: some aspects are right, others wrong

Always cite the specific source that supports or contradicts the claim.
Be precise — in industrial machinery, wrong specs can be costly."""


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
