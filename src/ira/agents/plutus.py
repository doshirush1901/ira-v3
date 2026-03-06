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

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("plutus_system")


class Plutus(BaseAgent):
    name = "plutus"
    role = "Chief Financial Officer"
    description = "Financial analysis, pricing, quote generation, and budget oversight"

    @property
    def _pricing_engine(self) -> Any | None:
        return self._services.get("pricing_engine")

    @property
    def _crm(self) -> Any | None:
        return self._services.get("crm")

    @property
    def _quotes(self) -> Any | None:
        return self._services.get("quotes")

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        pricing_context = ""
        if self._pricing_engine and self._should_estimate_price(query, ctx):
            pricing_context = await self._get_pricing_context(query, ctx)

        crm_context = ""
        if self._crm and self._should_pull_crm(query, ctx):
            crm_context = await self._get_crm_context(query, ctx)

        kb_results = await self.search_category(
            query, category="quotes_and_proposals", limit=8,
        )
        kb_context = self._format_context(kb_results)

        sections = [f"Query: {query}"]
        if pricing_context:
            sections.append(f"Pricing Intelligence:\n{pricing_context}")
        if crm_context:
            sections.append(f"CRM Deal Data:\n{crm_context}")
        sections.append(f"Historical Quotes (Knowledge Base):\n{kb_context}")

        return await self.call_llm(_SYSTEM_PROMPT, "\n\n".join(sections))

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
                return ""

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
        except Exception:
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
        except Exception:
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
