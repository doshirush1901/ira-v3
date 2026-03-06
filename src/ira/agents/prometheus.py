"""Prometheus — Sales / CRO agent.

Manages the sales pipeline, tracks deals, analyses conversion rates,
and provides strategic sales advice.  When the CRM is available
(injected via ``services``), Prometheus queries live deal, contact, and
interaction data.  Otherwise falls back to knowledge-base search.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("prometheus_system")


class Prometheus(BaseAgent):
    name = "prometheus"
    role = "Chief Revenue Officer"
    description = "Sales pipeline management, deal tracking, and revenue strategy"

    @property
    def _crm(self) -> Any | None:
        return self._services.get("crm")

    @property
    def _quotes(self) -> Any | None:
        return self._services.get("quotes")

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        kb_results = await self.search_knowledge(
            query, limit=8, sources=["qdrant", "neo4j"],
        )
        kb_context = self._format_context(kb_results)

        crm_context = ""
        if self._crm:
            crm_context = await self._build_crm_context(query, ctx)

        quote_context = ""
        if self._quotes:
            quote_context = await self._build_quote_context(query, ctx)

        sales_intel_context = await self._build_sales_intel_context(query, ctx)

        sections = [f"Query: {query}"]
        if crm_context:
            sections.append(f"CRM Data:\n{crm_context}")
        if quote_context:
            sections.append(f"Quote Pipeline:\n{quote_context}")
        if sales_intel_context:
            sections.append(f"Sales Intelligence:\n{sales_intel_context}")
        sections.append(f"Knowledge Base:\n{kb_context}")

        return await self.call_llm(_SYSTEM_PROMPT, "\n\n".join(sections))

    async def _build_sales_intel_context(self, query: str, ctx: dict[str, Any]) -> str:
        try:
            from ira.brain.sales_intelligence import SalesIntelligence
            si = SalesIntelligence(
                retriever=self._retriever,
                crm=self._crm,
                pricing_engine=self._services.get("pricing_engine"),
            )
            contact_email = ctx.get("perception", {}).get("resolved_contact", {}).get("email")
            if contact_email:
                health = await si.assess_customer_health(contact_email)
                if health:
                    return f"Customer health: {health}"
            return ""
        except Exception:
            logger.debug("SalesIntelligence not available")
            return ""

    async def _build_crm_context(self, query: str, ctx: dict[str, Any]) -> str:
        try:
            parts: list[str] = []

            contact_email = ctx.get("perception", {}).get("resolved_contact", {}).get("email")
            if contact_email:
                contacts = await self._crm.search_contacts(contact_email)
                if contacts:
                    contact = contacts[0]
                    parts.append(f"Contact: {contact.get('name')} ({contact.get('email')})")
                    parts.append(f"  Company: {contact.get('company_id', 'N/A')}")
                    parts.append(f"  Lead score: {contact.get('lead_score', 0)}")
                    parts.append(f"  Warmth: {contact.get('warmth_level', 'N/A')}")

                    deals = await self._crm.get_deals_for_contact(contact["id"])
                    if deals:
                        parts.append(f"  Active deals ({len(deals)}):")
                        for d in deals[:5]:
                            parts.append(
                                f"    - {d.get('title')} | {d.get('stage')} | "
                                f"{d.get('currency', 'USD')} {d.get('value', 0):,.2f}"
                            )

                    interactions = await self._crm.get_interactions_for_contact(contact["id"])
                    if interactions:
                        parts.append(f"  Recent interactions ({len(interactions)}):")
                        for i in interactions[:3]:
                            parts.append(
                                f"    - [{i.get('channel')}] {i.get('subject', 'N/A')[:80]} "
                                f"({i.get('created_at', '?')})"
                            )

            summary = await self._crm.get_pipeline_summary()
            if summary.get("total_count", 0) > 0:
                parts.append(f"\nPipeline overview: {json.dumps(summary, default=str)}")

            stale = await self._crm.get_stale_leads(days=14)
            if stale:
                parts.append(f"\nStale leads (>14 days): {len(stale)}")
                for s in stale[:3]:
                    parts.append(f"  - {s.get('name')} ({s.get('email')})")

            return "\n".join(parts) if parts else "(No CRM data found)"
        except Exception:
            logger.exception("CRM context build failed in Prometheus")
            return "(CRM query failed)"

    async def _build_quote_context(self, query: str, ctx: dict[str, Any]) -> str:
        try:
            analytics = await self._quotes.get_quote_analytics()
            followups = await self._quotes.get_quotes_due_for_followup()

            parts: list[str] = []
            if analytics.get("total_quotes", 0) > 0:
                parts.append(f"Quote analytics: {json.dumps(analytics, default=str)}")
            if followups:
                parts.append(f"Quotes due for follow-up: {len(followups)}")
                for q in followups[:3]:
                    parts.append(
                        f"  - {q.company_name or 'N/A'} | {q.machine_model or 'N/A'} | "
                        f"Status: {q.status.value if hasattr(q.status, 'value') else q.status}"
                    )

            return "\n".join(parts) if parts else ""
        except Exception:
            logger.exception("Quote context build failed in Prometheus")
            return ""
