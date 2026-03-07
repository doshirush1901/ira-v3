"""Tyche — Pipeline Forecaster agent.

Analyses the sales pipeline to provide revenue forecasts,
win/loss predictions, and trend analysis.  Uses skills for
pipeline forecasting and revenue analysis.  Equipped with ReAct
tools for pipeline data retrieval, revenue analysis, and
cross-agent delegation to Prometheus.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("tyche_system")


class Tyche(BaseAgent):
    name = "tyche"
    role = "Pipeline Forecaster"
    description = "Revenue forecasting, win/loss prediction, and pipeline analysis"
    knowledge_categories = [
        "sales_and_crm",
        "tally_exports",
        "machinecraft finance",
        "orders_and_pos",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="get_pipeline_data",
            description="Retrieve the current live sales pipeline forecast data.",
            parameters={},
            handler=self._tool_get_pipeline_data,
        ))
        self.register_tool(AgentTool(
            name="get_revenue_data",
            description="Retrieve revenue analysis data, optionally with filters.",
            parameters={"filters": "Optional filter criteria (e.g. date range, region)"},
            handler=self._tool_get_revenue_data,
        ))
        self.register_tool(AgentTool(
            name="search_forecast_knowledge",
            description="Search the knowledge base for financial data, tally exports, orders, and sales data useful for forecasting. Use this when CRM skills return sparse data.",
            parameters={"query": "Search query about revenue, orders, pipeline, finances"},
            handler=self._tool_search_forecast_knowledge,
        ))
        self.register_tool(AgentTool(
            name="ask_prometheus",
            description="Delegate a question to Prometheus, the CRM/sales pipeline agent.",
            parameters={"query": "Question for Prometheus"},
            handler=self._tool_ask_prometheus,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_get_pipeline_data(self) -> str:
        try:
            return await self.use_skill("forecast_pipeline")
        except Exception as exc:
            return f"Pipeline skill error: {exc}"

    async def _tool_get_revenue_data(self, filters: str = "") -> str:
        try:
            return await self.use_skill(
                "analyze_revenue",
                filters=filters if filters else None,
            )
        except Exception as exc:
            return f"Revenue skill error: {exc}"

    async def _tool_search_forecast_knowledge(self, query: str) -> str:
        results = await self.search_domain_knowledge(query, limit=10)
        if not results:
            return "No forecast-relevant data found in knowledge base."
        return self._format_context(results)

    async def _tool_ask_prometheus(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("prometheus")
        if agent is None:
            return "Prometheus agent not found."
        try:
            return await agent.handle(query)
        except Exception as exc:
            return f"Prometheus error: {exc}"

    # ── handle ───────────────────────────────────────────────────────────

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

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)
