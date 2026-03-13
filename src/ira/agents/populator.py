"""Populator — CRM Populator agent.

Hunts for leads and customers across all data sources (imports, 07_Leads,
Neo4j, KB, Gmail), classifies them (client vs non-client), enriches via
web scraping and other agents (e.g. Iris), and adds them to the CRM with
as much detail as possible.

Injected services (same as other agents via pipeline): CRM, PANTHEON (ask_agent),
LONG_TERM_MEMORY (recall_memory, store_memory), EPISODIC_MEMORY (recall_episodes),
CONVERSATION_MEMORY, RELATIONSHIP_MEMORY, GOAL_MANAGER, EMAIL_PROCESSOR (search_emails).
Populator delegates to Delphi (classification), Iris (web/scrape), Artemis (mailbox),
Alexandros (archive), and Clio (KB) via ask_agent when needed.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("populator_system")


class Populator(BaseAgent):
    name = "populator"
    role = "CRM Populator"
    description = (
        "Hunts for leads and customers across all data sources (imports, "
        "lead spreadsheets, Neo4j, KB, Gmail), identifies them as client "
        "or non-client, enriches via web scraping and other agents, and "
        "adds them to the CRM with full detail (company notes, machines, "
        "thermoforming application)."
    )
    knowledge_categories = [
        "sales_and_crm",
        "leads_and_contacts",
        "orders_and_pos",
    ]

    @property
    def _crm(self) -> Any | None:
        return self._services.get(SK.CRM)

    def _register_tools(self) -> None:
        super()._register_tools()

        self.register_tool(AgentTool(
            name="run_crm_populate",
            description=(
                "Run the CRM population pipeline: extract contacts from the "
                "given sources, classify them (client/lead/etc.), and insert "
                "into the CRM. sources = comma-separated: imports, imports_07, "
                "neo4j, kb, gmail. Use dry_run=true to see what would be added "
                "without writing. Returns stats (inserted, skipped, errors)."
            ),
            parameters={
                "sources": "Comma-separated: imports, imports_07, neo4j, kb, gmail",
                "dry_run": "If true, classify but do not insert (default false)",
            },
            handler=self._tool_run_crm_populate,
        ))

        self.register_tool(AgentTool(
            name="enrich_company_website",
            description=(
                "Scrape a company website URL and produce a short summary "
                "focused on thermoforming, vacuum forming, machines they have "
                "or need, and application. Use the result to update company notes."
            ),
            parameters={
                "company_name": "Company name (for context)",
                "website_url": "Full URL of the company website to scrape",
            },
            handler=self._tool_enrich_company_website,
        ))

        self.register_tool(AgentTool(
            name="update_company_notes",
            description=(
                "Set or append notes for a company in the CRM. Finds company "
                "by name (case-insensitive) and updates its notes field."
            ),
            parameters={
                "company_name": "Exact or partial company name in CRM",
                "notes": "Notes to set (replaces existing) or append if you pass append=true in notes",
            },
            handler=self._tool_update_company_notes,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context or {}, system_prompt=_SYSTEM_PROMPT)

    async def _tool_run_crm_populate(self, sources: str, dry_run: str = "false") -> str:
        crm = self._crm
        if not crm:
            return "CRM not available."
        source_list = [s.strip().lower() for s in sources.split(",") if s.strip()]
        if not source_list:
            return "Provide at least one source: imports, imports_07, neo4j, kb, gmail."
        dry = dry_run.strip().lower() in ("true", "1", "yes")

        try:
            from ira.message_bus import MessageBus
            from ira.agents.delphi import Delphi
            from ira.systems.crm_populator import CRMPopulator

            await crm.create_tables()
            bus = getattr(self, "_bus", None) or MessageBus()
            delphi = Delphi(retriever=self._retriever, bus=bus)
            populator = CRMPopulator(delphi=delphi, crm=crm, dry_run=dry)
            result = await populator.populate(source_list)
        except Exception as e:
            logger.exception("run_crm_populate failed")
            return f"Population failed: {e!s}"

        stats = result.get("stats", {})
        return (
            f"Population complete (dry_run={dry}). "
            f"Inserted: {stats.get('inserted', 0)}, "
            f"Skipped duplicate: {stats.get('skipped_duplicate', 0)}, "
            f"Skipped rejected: {stats.get('skipped_rejected', 0)}, "
            f"Skipped no email: {stats.get('skipped_no_email', 0)}, "
            f"Errors: {stats.get('errors', 0)}."
        )

    async def _tool_enrich_company_website(self, company_name: str, website_url: str) -> str:
        if not website_url.startswith("http"):
            website_url = "https://" + website_url
        try:
            content = await self.scrape_url(website_url, max_chars=12000)
        except Exception as e:
            return f"Failed to scrape {website_url}: {e!s}"
        if not content or len(content.strip()) < 100:
            return "Scrape returned too little content to summarize."

        system = (
            "You summarize company websites for B2B machine sales (thermoforming/vacuum forming). "
            "Given raw page content, output a short paragraph (3–5 sentences) covering: "
            "what the company does; whether they use thermoforming/vacuum forming or related processes; "
            "what machines or equipment they might have or need; and application/industry (e.g. automotive, packaging). "
            "Use only information clearly stated on the page. If nothing relevant, say so. Output only the summary."
        )
        try:
            summary = await self._llm.generate_text(
                system=system,
                user=f"Company: {company_name}\n\nURL: {website_url}\n\nPage content:\n{content[:8000]}",
                temperature=0.2,
                max_tokens=500,
                name="enrich_company_website",
            )
            return (summary or "").strip() or "No summary generated."
        except Exception as e:
            logger.warning("LLM summarize failed: %s", e)
            return f"Summary failed: {e!s}. Raw content length: {len(content)} chars."

    async def _tool_update_company_notes(self, company_name: str, notes: str) -> str:
        crm = self._crm
        if not crm:
            return "CRM not available."
        companies = await crm.list_companies()
        name_lower = (company_name or "").strip().lower()
        match = next((c for c in companies if (c.name or "").lower() == name_lower), None)
        if not match:
            partial = next((c for c in companies if name_lower in (c.name or "").lower()), None)
            if partial:
                match = partial
        if not match:
            return f"No company found with name '{company_name}'."
        await crm.update_company(str(match.id), notes=(notes or "").strip())
        return f"Updated notes for company '{match.name}' (id={match.id})."
