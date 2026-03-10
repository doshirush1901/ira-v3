"""Hermes — Marketing / CMO agent.

Manages marketing campaigns, lead nurturing, drip sequences,
and market positioning strategy.  Uses skills for email drafting,
drip design, and social content generation.  Equipped with ReAct
tools for market research, LinkedIn data, email drafting, drip
sequences, and cross-agent delegation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import ToolExecutionError
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("hermes_system")


class Hermes(BaseAgent):
    name = "hermes"
    role = "Chief Marketing Officer"
    description = "Marketing campaigns, lead nurturing, and market positioning"
    knowledge_categories = [
        "market_research_and_analysis",
        "leads_and_contacts",
        "presentations",
        "product_catalogues",
        "linkedin data",
    ]

    _DRIP_STAGES: dict[str, dict[str, Any]] = {
        "INTRO": {
            "description": "Initial outreach establishing who Machinecraft is and why we are reaching out",
            "delay_days": 0,
        },
        "VALUE": {
            "description": "Highlight a specific pain point we solve with concrete ROI data",
            "delay_days": 3,
        },
        "TECHNICAL": {
            "description": "Share technical specs, case study, or whitepaper relevant to their use case",
            "delay_days": 5,
        },
        "SOCIAL_PROOF": {
            "description": "Customer testimonial, reference story, or installation showcase",
            "delay_days": 7,
        },
        "EVENT": {
            "description": "Invite to a demo, factory visit, webinar, or trade show meeting",
            "delay_days": 10,
        },
        "BREAKUP": {
            "description": "Friendly last-touch email acknowledging they may not be ready now",
            "delay_days": 14,
        },
        "RE_ENGAGE": {
            "description": "Dormant re-engagement with new product news or market insight",
            "delay_days": 45,
        },
    }

    _REGIONAL_TONE: dict[str, str] = {
        "germany": "formal, precise, engineering-focused",
        "netherlands": "direct, practical",
        "india": "warm, relationship-first",
        "middle_east": "respectful, relationship-building",
        "usa": "professional, results-oriented",
    }

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="search_market_research",
            description="Search market research and analysis documents.",
            parameters={"query": "Search query"},
            handler=self._tool_search_market_research,
        ))
        self.register_tool(AgentTool(
            name="search_linkedin_data",
            description="Search LinkedIn data for contacts, companies, and professional context.",
            parameters={"query": "Search query"},
            handler=self._tool_search_linkedin_data,
        ))
        self.register_tool(AgentTool(
            name="draft_email",
            description="Draft an outreach email for a recipient.",
            parameters={
                "recipient_name": "Name or email of the recipient",
                "purpose": "Purpose/context for the email",
                "tone": "Tone of the email (default: professional)",
            },
            handler=self._tool_draft_email,
        ))
        self.register_tool(AgentTool(
            name="create_drip_sequence",
            description="Create a multi-stage drip email campaign for a target.",
            parameters={
                "campaign_name": "Company or campaign name",
                "target_email": "Target contact email",
                "region": "Region for tone adaptation (optional)",
            },
            handler=self._tool_create_drip_sequence,
        ))
        self.register_tool(AgentTool(
            name="ask_cadmus",
            description="Delegate a question to Cadmus, the case study / content agent.",
            parameters={"query": "Question for Cadmus"},
            handler=self._tool_ask_cadmus,
        ))
        self.register_tool(AgentTool(
            name="ask_arachne",
            description="Delegate a question to Arachne, the content scheduler.",
            parameters={"query": "Question for Arachne"},
            handler=self._tool_ask_arachne,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_search_market_research(self, query: str) -> str:
        results = await self.search_category(query, "market_research_and_analysis")
        if not results:
            return "No market research results found."
        return "\n".join(
            f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}"
            for r in results
        )

    async def _tool_search_linkedin_data(self, query: str) -> str:
        results = await self.search_category(query, "linkedin data")
        if not results:
            return "No LinkedIn data found."
        return "\n".join(
            f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}"
            for r in results
        )

    async def _tool_draft_email(
        self, recipient_name: str, purpose: str, tone: str = "professional",
    ) -> str:
        return await self.use_skill(
            "draft_outreach_email",
            email=recipient_name,
            context=purpose,
            region="",
        )

    async def _tool_create_drip_sequence(
        self, campaign_name: str, target_email: str, region: str = "",
    ) -> str:
        return await self.use_skill(
            "create_drip_sequence",
            email=target_email,
            company=campaign_name,
            region=region,
        )

    async def _tool_ask_cadmus(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("cadmus")
        if agent is None:
            return "Cadmus agent not found."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Cadmus error: {exc}"

    async def _tool_ask_arachne(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("arachne")
        if agent is None:
            return "Arachne agent not found."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Arachne error: {exc}"

    # ── handle ───────────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "drip_campaign":
            return await self._skill_drip_campaign(ctx)

        if action == "outreach":
            return await self._skill_outreach(ctx)

        if action == "social_post":
            return await self.use_skill(
                "generate_social_post",
                topic=ctx.get("topic", query),
                platform=ctx.get("platform", "linkedin"),
            )

        if action == "lead_report":
            return await self.use_skill(
                "build_lead_report",
                days=int(ctx.get("days", 14)),
            )

        if action == "schedule_campaign":
            return await self.use_skill(
                "schedule_campaign",
                name=ctx.get("campaign_name", ctx.get("campaign_id", "")),
                segment=ctx.get("segment", {}),
                start_date=ctx.get("start_date", ""),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    # ── private helpers ──────────────────────────────────────────────────

    async def _skill_outreach(self, ctx: dict[str, Any]) -> str:
        contact_email = ctx.get("contact_email", "")
        company = ctx.get("company", "")

        if contact_email and company:
            await self.report_relationship(
                "Person", contact_email,
                "WORKS_AT",
                "Company", company,
            )

        machine = ctx.get("machine", "")
        if company and machine:
            await self.report_relationship(
                "Company", company,
                "INTERESTED_IN",
                "Machine", machine,
            )

        dossier = await self._build_context_dossier(contact_email, ctx)
        return await self.use_skill(
            "draft_outreach_email",
            email=contact_email,
            company=company,
            region=ctx.get("region", ""),
            stage=ctx.get("stage", "INTRO"),
            context=dossier,
        )

    async def _skill_drip_campaign(self, ctx: dict[str, Any]) -> str:
        return await self.use_skill(
            "create_drip_sequence",
            email=ctx.get("contact_email", ""),
            company=ctx.get("company", ""),
            region=ctx.get("region", ""),
            machine=ctx.get("machine", ""),
            stages=len(self._DRIP_STAGES),
        )

    async def _build_context_dossier(self, contact_email: str, context: dict[str, Any]) -> str:
        crm_results = await self.search_knowledge(
            f"CRM contact {contact_email}", limit=5,
        )
        company = context.get("company", "")
        product_results = await self.search_knowledge(
            f"product fit {company}" if company else f"product fit {contact_email}",
            limit=5,
        )
        reference_results = await self.search_knowledge(
            f"customer success reference story {company or contact_email}",
            limit=5,
        )

        dossier_parts = {
            "contact_email": contact_email,
            "company": company,
            "crm_signals": self._format_context(crm_results),
            "product_fit": self._format_context(product_results),
            "reference_stories": self._format_context(reference_results),
            "region": context.get("region", "unknown"),
        }
        return json.dumps(dossier_parts, indent=2)

    async def design_drip_campaign(self, contact_email: str, context: dict[str, Any]) -> str:
        """Legacy method — delegates to skill."""
        return await self._skill_drip_campaign({
            "contact_email": contact_email,
            **context,
        })
