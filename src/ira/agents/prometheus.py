"""Prometheus — Sales / CRO agent.

Manages the sales pipeline, tracks deals, analyses conversion rates,
and provides strategic sales advice.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Prometheus, the Chief Revenue Officer of Machinecraft.  You own
the sales pipeline and are responsible for revenue growth.

Your capabilities:
- Pipeline analysis: deal stages, conversion rates, bottlenecks
- Lead qualification and prioritisation
- Sales strategy and next-best-action recommendations
- Win/loss analysis and competitive positioning
- CRM data interpretation

Always be data-driven.  When discussing deals, reference specific
numbers and stages.  Suggest concrete next steps."""


class Prometheus(BaseAgent):
    name = "prometheus"
    role = "Chief Revenue Officer"
    description = "Sales pipeline management, deal tracking, and revenue strategy"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(
            query, limit=8, sources=["qdrant", "neo4j"],
        )
        kb_context = self._format_context(kb_results)

        crm_context = ""
        if context and "crm_data" in context:
            crm_context = f"\n\nCRM Data:\n{context['crm_data']}"

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nKnowledge Base:\n{kb_context}{crm_context}",
        )
