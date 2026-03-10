"""Plutus — Finance / CFO agent.

Handles financial analysis, pricing review, margin calculations,
quote generation, and budget oversight.  When the PricingEngine and CRM
are available (injected via ``services``), Plutus can generate structured
price estimates and pull real deal history.  Otherwise falls back to
knowledge-base search.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import DatabaseError, LLMError, ToolExecutionError
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("plutus_system")


class Plutus(BaseAgent):
    name = "plutus"
    role = "Chief Financial Officer"
    description = "Financial analysis, pricing, quote generation, and budget oversight"
    knowledge_categories = [
        "quotes_and_proposals",
        "tally_exports",
        "machinecraft finance",
        "contracts_and_legal",
        "business plans",
    ]

    @property
    def _pricing_engine(self) -> Any | None:
        return self._services.get("pricing_engine")

    @property
    def _crm(self) -> Any | None:
        return self._services.get("crm")

    @property
    def _quotes(self) -> Any | None:
        return self._services.get("quotes")

    # ── tool registration ─────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        if self._pricing_engine:
            self.register_tool(AgentTool(
                name="estimate_price",
                description="Estimate the price for a machine model with optional features.",
                parameters={
                    "machine_model": "Machine model identifier (e.g. PF1-500)",
                    "features": "Comma-separated optional features (default empty)",
                },
                handler=self._tool_estimate_price,
            ))

        if self._quotes:
            self.register_tool(AgentTool(
                name="get_quote",
                description="Retrieve a specific quote by its ID.",
                parameters={"quote_id": "The quote identifier"},
                handler=self._tool_get_quote,
            ))

        self.register_tool(AgentTool(
            name="search_financial_docs",
            description="Search the financial knowledge base for documents, contracts, and reports.",
            parameters={"query": "Search query"},
            handler=self._tool_search_financial_docs,
        ))

        if self._crm:
            self.register_tool(AgentTool(
                name="get_deal_financials",
                description="Get financial details for a specific deal by ID.",
                parameters={"deal_id": "The deal identifier"},
                handler=self._tool_get_deal_financials,
            ))

        self.register_tool(AgentTool(
            name="generate_invoice",
            description="Generate an invoice for a customer, optionally from a quote.",
            parameters={
                "customer": "Customer name or identifier",
                "quote_id": "Optional quote ID to base the invoice on",
                "items": "Optional comma-separated line items",
            },
            handler=self._tool_generate_invoice,
        ))
        self.register_tool(AgentTool(
            name="calculate_quote_skill",
            description="Calculate quote values via canonical pricing skill.",
            parameters={
                "machine_model": "Machine model identifier",
                "configuration": "Optional JSON configuration",
            },
            handler=self._tool_calculate_quote_skill,
        ))
        self.register_tool(AgentTool(
            name="analyze_revenue_skill",
            description="Analyze revenue and pipeline velocity via canonical skill.",
            parameters={"filters": "Optional JSON filters"},
            handler=self._tool_analyze_revenue_skill,
        ))

        if self._services.get("pantheon"):
            self.register_tool(AgentTool(
                name="ask_prometheus",
                description="Delegate a sales/CRM question to the Prometheus (CRO) agent.",
                parameters={"query": "The sales or CRM question"},
                handler=self._tool_ask_prometheus,
            ))

    # ── tool handlers ─────────────────────────────────────────────────────

    async def _tool_estimate_price(self, machine_model: str, features: str = "") -> str:
        config = {"features": features} if features else {}
        estimate = await self._pricing_engine.estimate_price(machine_model, config)
        return json.dumps(estimate, default=str)

    async def _tool_get_quote(self, quote_id: str) -> str:
        quote = await self._quotes.get_quote(quote_id)
        return json.dumps(quote, default=str) if quote else f"Quote '{quote_id}' not found."

    async def _tool_search_financial_docs(self, query: str) -> str:
        results = await self.search_domain_knowledge(query)
        return self._format_context(results)

    async def _tool_get_deal_financials(self, deal_id: str) -> str:
        deal = await self._crm.get_deal(deal_id)
        return json.dumps(deal, default=str) if deal else f"Deal '{deal_id}' not found."

    async def _tool_generate_invoice(self, customer: str, quote_id: str = "", items: str = "") -> str:
        return await self.use_skill(
            "generate_invoice", customer=customer, quote_id=quote_id,
        )

    async def _tool_calculate_quote_skill(self, machine_model: str, configuration: str = "") -> str:
        parsed_config: Any = {}
        if configuration:
            try:
                parsed_config = json.loads(configuration)
            except json.JSONDecodeError:
                parsed_config = {"raw_configuration": configuration}
        return await self.use_skill(
            "calculate_quote",
            machine_model=machine_model,
            configuration=parsed_config,
        )

    async def _tool_analyze_revenue_skill(self, filters: str = "") -> str:
        parsed_filters: Any = None
        if filters:
            try:
                parsed_filters = json.loads(filters)
            except json.JSONDecodeError:
                parsed_filters = {"raw_filters": filters}
        return await self.use_skill("analyze_revenue", filters=parsed_filters)

    async def _tool_ask_prometheus(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("prometheus")
        if agent is None:
            return "Prometheus agent not available."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Prometheus error: {exc}"

    # ── main handler ──────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", "")

        if task == "generate_invoice":
            return await self.use_skill(
                "generate_invoice",
                customer=ctx.get("customer", ""),
                quote_id=ctx.get("quote_id", ""),
                items=ctx.get("items", []),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    # ── private helpers (kept for backward compat) ────────────────────────

    def _should_estimate_price(self, query: str, ctx: dict[str, Any]) -> bool:
        price_keywords = {"quote", "price", "cost", "estimate", "pricing", "budget", "value"}
        return bool(price_keywords & set(query.lower().split())) or "machine_model" in ctx

    def _should_pull_crm(self, query: str, ctx: dict[str, Any]) -> bool:
        crm_keywords = {"deal", "pipeline", "history", "revenue", "analytics", "forecast", "win"}
        return bool(crm_keywords & set(query.lower().split())) or "contact_id" in ctx

    async def _get_pricing_context(self, query: str, ctx: dict[str, Any]) -> str:
        try:
            machine_model = ctx.get("machine_model", "")
            configuration = ctx.get("configuration", {})

            if not machine_model:
                machine_model = self._extract_machine_from_query(query)

            if not machine_model:
                return "Error: No machine model identified in the query. Ask for a specific model (e.g. PF1-500) or use the estimate_price tool with a machine_model parameter."

            estimate = await self._pricing_engine.estimate_price(
                machine_model, configuration,
            )

            lines = []
            ep = estimate.get("estimated_price", {})
            if ep:
                lines.append(
                    f"Estimated price: {ep.get('currency', 'USD')} "
                    f"{ep.get('low', '?')} – {ep.get('high', '?')} "
                    f"(mid: {ep.get('mid', '?')})"
                )
            lines.append(f"Confidence: {estimate.get('confidence', 'unknown')}")
            if estimate.get("reasoning"):
                lines.append(f"Reasoning: {estimate['reasoning']}")

            similar = estimate.get("similar_quotes", [])
            if similar:
                lines.append("Similar historical quotes:")
                for sq in similar[:3]:
                    lines.append(f"  - {sq.get('content', '')[:200]}")

            return "\n".join(lines)
        except (LLMError, Exception):
            logger.exception("PricingEngine call failed in Plutus")
            return "(Pricing engine unavailable)"

    async def _get_crm_context(self, query: str, ctx: dict[str, Any]) -> str:
        try:
            filters = {}
            if "machine_model" in ctx:
                filters["machine_model"] = ctx["machine_model"]
            if "contact_id" in ctx:
                filters["contact_id"] = ctx["contact_id"]

            deals = await self._crm.get_deals_by_filter(filters)
            if not deals:
                summary = await self._crm.get_pipeline_summary(filters or None)
                return f"Pipeline summary: {json.dumps(summary, default=str)}"

            lines = [f"Found {len(deals)} matching deals:"]
            for d in deals[:5]:
                lines.append(
                    f"  - {d.get('title', 'Untitled')} | "
                    f"{d.get('stage', '?')} | "
                    f"{d.get('currency', 'USD')} {d.get('value', 0):,.2f} | "
                    f"Machine: {d.get('machine_model', 'N/A')}"
                )
            return "\n".join(lines)
        except (DatabaseError, Exception):
            logger.exception("CRM query failed in Plutus")
            return "(CRM data unavailable)"

    @staticmethod
    def _extract_machine_from_query(query: str) -> str:
        tokens = query.upper().split()
        for token in tokens:
            if token.startswith("PF") or token.startswith("AM-") or token.startswith("RF-") or token.startswith("SL-"):
                return token
        for i, token in enumerate(tokens):
            if token in ("PF1", "PF2") and i + 1 < len(tokens):
                return f"{token}-{tokens[i + 1]}"
        return ""
