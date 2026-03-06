"""Tyche — Pipeline Forecaster agent.

Analyses the sales pipeline to provide revenue forecasts,
win/loss predictions, and trend analysis.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("tyche_system")


class Tyche(BaseAgent):
    name = "tyche"
    role = "Pipeline Forecaster"
    description = "Revenue forecasting, win/loss prediction, and pipeline analysis"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        pipeline_data = ""
        if context and "pipeline" in context:
            pipeline_data = f"\n\nPipeline Data:\n{context['pipeline']}"

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nHistorical Context:\n{kb_context}{pipeline_data}",
        )
