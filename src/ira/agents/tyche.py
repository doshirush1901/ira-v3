"""Tyche — Pipeline Forecaster agent.

Analyses the sales pipeline to provide revenue forecasts,
win/loss predictions, and trend analysis.  Uses skills for
pipeline forecasting and revenue analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("tyche_system")


class Tyche(BaseAgent):
    name = "tyche"
    role = "Pipeline Forecaster"
    description = "Revenue forecasting, win/loss prediction, and pipeline analysis"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "forecast":
            pipeline_data = await self.use_skill("forecast_pipeline")
            return await self.call_llm(
                _SYSTEM_PROMPT,
                f"Query: {query}\n\nLive Pipeline Data:\n{pipeline_data}",
            )

        if action == "revenue":
            revenue_data = await self.use_skill(
                "analyze_revenue", filters=ctx.get("filters"),
            )
            return await self.call_llm(
                _SYSTEM_PROMPT,
                f"Query: {query}\n\nRevenue Data:\n{revenue_data}",
            )

        live_data = ""
        try:
            live_data = await self.use_skill("forecast_pipeline")
        except Exception:
            logger.debug("Pipeline skill unavailable, falling back to KB")

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        pipeline_data = ""
        if ctx.get("pipeline"):
            pipeline_data = f"\n\nPipeline Data (from context):\n{ctx['pipeline']}"

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\n"
            f"Live Pipeline Intelligence:\n{live_data or '(not available)'}\n\n"
            f"Historical Context:\n{kb_context}{pipeline_data}",
        )
