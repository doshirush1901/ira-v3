"""Hermes — Marketing / CMO agent.

Manages marketing campaigns, lead nurturing, drip sequences,
and market positioning strategy.  Uses skills for email drafting,
drip design, and social content generation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("hermes_system")


class Hermes(BaseAgent):
    name = "hermes"
    role = "Chief Marketing Officer"
    description = "Marketing campaigns, lead nurturing, and market positioning"

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

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nMarketing Context:\n{kb_context}",
        )

    async def _skill_outreach(self, ctx: dict[str, Any]) -> str:
        """Use the draft_outreach_email skill with dossier context."""
        dossier = await self._build_context_dossier(
            ctx.get("contact_email", ""), ctx,
        )
        return await self.use_skill(
            "draft_outreach_email",
            email=ctx.get("contact_email", ""),
            company=ctx.get("company", ""),
            region=ctx.get("region", ""),
            stage=ctx.get("stage", "INTRO"),
            context=dossier,
        )

    async def _skill_drip_campaign(self, ctx: dict[str, Any]) -> str:
        """Use the create_drip_sequence skill."""
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
