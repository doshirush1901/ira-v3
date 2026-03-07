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

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("prometheus_system")


class Prometheus(BaseAgent):
    name = "prometheus"
    role = "Chief Revenue Officer"
    description = "Sales pipeline management, deal tracking, and revenue strategy"
    knowledge_categories = [
        "sales_and_crm",
        "orders_and_pos",
        "leads_and_contacts",
        "quotes_and_proposals",
        "current machine orders",
        "webcall transcripts",
    ]

    @property
    def _crm(self) -> Any | None:
        return self._services.get("crm")

    @property
    def _quotes(self) -> Any | None:
        return self._services.get("quotes")

    # ── tool registration ─────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="search_sales_knowledge",
            description="Search the knowledge base across all sales categories: quotes, orders, leads, contacts, webcall transcripts. This is your RICHEST data source.",
            parameters={"query": "Search query about leads, deals, companies, contacts"},
            handler=self._tool_search_sales_knowledge,
        ))

        if self._crm:
            self.register_tool(AgentTool(
                name="search_contacts",
                description="Search CRM contacts by name, email, or company.",
                parameters={"query": "Search term (name, email, company)"},
                handler=self._tool_search_contacts,
            ))
            self.register_tool(AgentTool(
                name="get_deal",
                description="Get full details for a specific deal by ID.",
                parameters={"deal_id": "The deal identifier"},
                handler=self._tool_get_deal,
            ))
            self.register_tool(AgentTool(
                name="get_pipeline_summary",
                description="Get an overview of the current sales pipeline (stages, counts, values).",
                parameters={},
                handler=self._tool_get_pipeline_summary,
            ))
            self.register_tool(AgentTool(
                name="get_stale_leads",
                description="List leads with no activity in the given number of days.",
                parameters={"days": "Inactivity threshold in days (default 14)"},
                handler=self._tool_get_stale_leads,
            ))
            self.register_tool(AgentTool(
                name="get_warm_contacts",
                description="List all WARM and TRUSTED contacts from the CRM — these are high-value existing relationships.",
                parameters={"limit": "Max contacts to return (default 20)"},
                handler=self._tool_get_warm_contacts,
            ))
            self.register_tool(AgentTool(
                name="get_active_leads",
                description="List contacts classified as LEAD_WITH_INTERACTIONS — these are the active sales opportunities that need follow-up (e.g. Minini Plastic Italy, Extalon Germany, RAD Global, Durotherm, etc.). THIS IS YOUR MOST IMPORTANT TOOL. There are 200+ active leads.",
                parameters={"limit": "Max leads to return (default 50)"},
                handler=self._tool_get_active_leads,
            ))

        if self._quotes:
            self.register_tool(AgentTool(
                name="get_quote_analytics",
                description="Get analytics on quotes (totals, conversion rates, follow-ups due).",
                parameters={},
                handler=self._tool_get_quote_analytics,
            ))

        if self._services.get("pantheon"):
            self.register_tool(AgentTool(
                name="ask_quotebuilder",
                description="Delegate a quoting question to the Quotebuilder agent.",
                parameters={"query": "The quoting question or request"},
                handler=self._tool_ask_quotebuilder,
            ))

    # ── tool handlers ─────────────────────────────────────────────────────

    async def _tool_search_sales_knowledge(self, query: str) -> str:
        """Search across sales categories AND the full KB for maximum coverage."""
        domain_results = await self.search_domain_knowledge(query, limit=8)
        general_results = await self.search_knowledge(query, limit=5)

        seen: set[str] = set()
        merged: list[dict] = []
        for r in domain_results + general_results:
            key = r.get("content", "")[:100]
            if key not in seen:
                seen.add(key)
                merged.append(r)

        if not merged:
            return "No results found in sales knowledge base."
        return self._format_context(merged[:12])

    async def _tool_search_contacts(self, query: str) -> str:
        results = await self._crm.search_contacts(query)
        return json.dumps(results, default=str) if results else "No contacts found."

    async def _tool_get_deal(self, deal_id: str) -> str:
        deal = await self._crm.get_deal(deal_id)
        return json.dumps(deal, default=str) if deal else f"Deal '{deal_id}' not found."

    async def _tool_get_pipeline_summary(self) -> str:
        summary = await self._crm.get_pipeline_summary()
        return json.dumps(summary, default=str)

    async def _tool_get_stale_leads(self, days: str = "14") -> str:
        leads = await self._crm.get_stale_leads(days=int(days))
        return json.dumps(leads, default=str) if leads else "No stale leads found."

    async def _tool_get_warm_contacts(self, limit: str = "20") -> str:
        from sqlalchemy import text
        async with self._crm.session_factory() as session:
            result = await session.execute(text(
                "SELECT c.name, c.email, co.name as company, c.lead_score, "
                "c.warmth_level, c.contact_type "
                "FROM contacts c LEFT JOIN companies co ON c.company_id = co.id "
                "WHERE c.warmth_level IN ('WARM', 'TRUSTED') "
                "ORDER BY c.lead_score DESC LIMIT :lim"
            ), {"lim": int(limit)})
            rows = result.fetchall()
        if not rows:
            return "No warm/trusted contacts found."
        lines = []
        for r in rows:
            lines.append(f"- {r[0]} ({r[1]}) | Company: {r[2] or '?'} | Score: {r[3]} | {r[4]} | {r[5]}")
        return "\n".join(lines)

    async def _tool_get_active_leads(self, limit: str = "50") -> str:
        """List contacts classified as active leads — these are the sales opportunities."""
        from sqlalchemy import text
        async with self._crm.session_factory() as session:
            result = await session.execute(text(
                "SELECT c.name, c.email, co.name as company, c.lead_score, "
                "c.warmth_level, c.contact_type "
                "FROM contacts c LEFT JOIN companies co ON c.company_id = co.id "
                "WHERE c.contact_type IN ('LEAD_WITH_INTERACTIONS', 'ACTIVE_LEAD', 'PROSPECT') "
                "ORDER BY c.lead_score DESC, c.updated_at DESC LIMIT :lim"
            ), {"lim": int(limit)})
            rows = result.fetchall()
        if not rows:
            return "No active leads found."
        lines = []
        for r in rows:
            lines.append(f"- {r[0]} ({r[1]}) | Company: {r[2] or '?'} | Score: {r[3]} | {r[4]} | {r[5]}")
        return "\n".join(lines)

    async def _tool_get_quote_analytics(self) -> str:
        analytics = await self._quotes.get_quote_analytics()
        return json.dumps(analytics, default=str)

    async def _tool_ask_quotebuilder(self, query: str) -> str:
        pantheon = self._services["pantheon"]
        agent = pantheon.get_agent("quotebuilder")
        if agent is None:
            return "Quotebuilder agent not available."
        try:
            return await agent.handle(query)
        except Exception as exc:
            return f"Quotebuilder error: {exc}"

    # ── main handler ──────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", "")

        if task == "qualify_lead":
            return await self.use_skill(
                "qualify_lead",
                email=ctx.get("email", ""),
                company=ctx.get("company", ""),
            )
        if task == "deal_summary":
            return await self.use_skill(
                "generate_deal_summary",
                deal_id=ctx.get("deal_id", ""),
            )
        if task == "update_crm":
            return await self.use_skill(
                "update_crm_record",
                record_id=ctx.get("record_id", ""),
                updates=ctx.get("updates", {}),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    # ── private helpers (kept for backward compat) ────────────────────────

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
                            machine = d.get("machine_model", "")
                            company_name = contact.get("company_name", "") or contact.get("company", "")
                            if machine and company_name:
                                await self.report_relationship(
                                    "Company", company_name,
                                    "INTERESTED_IN",
                                    "Machine", machine,
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
