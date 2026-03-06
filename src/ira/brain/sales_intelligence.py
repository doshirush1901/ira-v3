"""Sales-specific analytical capabilities for Ira.

Provides lead qualification, customer-health scoring, stale-lead
detection, and real-time company intelligence.  All knowledge retrieval
goes through :class:`~ira.brain.retriever.UnifiedRetriever`; CRM data is
accessed via the :class:`SalesCRMRepository` protocol (implemented in
Phase 4).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID

import httpx

from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.data.models import Contact
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


# ── CRM repository interface ────────────────────────────────────────────────


class SalesCRMRepository(Protocol):
    """Minimal CRM surface the sales-intelligence layer needs."""

    async def get_contact(self, contact_id: str) -> dict[str, Any] | None: ...
    async def get_deals_for_contact(self, contact_id: str) -> list[dict[str, Any]]: ...
    async def get_interactions_for_contact(self, contact_id: str) -> list[dict[str, Any]]: ...
    async def get_stale_leads(self, since: datetime) -> list[dict[str, Any]]: ...


# ── LLM prompts ─────────────────────────────────────────────────────────────

_QUALIFY_SYSTEM_PROMPT = load_prompt("qualify_lead")

_HEALTH_SYSTEM_PROMPT = load_prompt("customer_health")

_REENGAGE_SYSTEM_PROMPT = load_prompt("reengage_lead")

_INTEL_SYSTEM_PROMPT = load_prompt("lead_intelligence")


class SalesIntelligence:
    """Sales analytics: lead qualification, health scoring, and intel."""

    def __init__(
        self,
        retriever: UnifiedRetriever,
        crm: SalesCRMRepository | None = None,
    ) -> None:
        self._retriever = retriever
        self._crm = crm

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model
        self._newsdata_key = settings.external_apis.api_key.get_secret_value()

    # ── lead qualification ───────────────────────────────────────────────

    async def qualify_lead(
        self,
        contact: Contact,
        inquiry_text: str,
    ) -> dict[str, Any]:
        """Score and classify an inbound lead.

        Returns ``score`` (0-100), ``qualification_level`` (HOT/WARM/COLD),
        ``buying_signals``, ``risk_factors``, and ``reasoning``.
        """
        enrichment = await self._enrich_contact(contact)

        context_lines = [
            "CONTACT PROFILE:",
            f"  Name: {contact.name}",
            f"  Email: {contact.email}",
            f"  Company: {contact.company or 'Unknown'}",
            f"  Region: {contact.region or 'Unknown'}",
            f"  Industry: {contact.industry or 'Unknown'}",
            f"  Current score: {contact.score}",
            "",
            "ENRICHMENT CONTEXT:",
            json.dumps(enrichment, indent=2, default=str),
            "",
            "INQUIRY TEXT:",
            inquiry_text[:4_000],
        ]

        raw = await self._llm_call(_QUALIFY_SYSTEM_PROMPT, "\n".join(context_lines))

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Lead-qualification LLM returned non-JSON")
            return {
                "score": 0,
                "qualification_level": "COLD",
                "buying_signals": [],
                "risk_factors": ["LLM parse failure"],
                "reasoning": raw,
            }

    # ── customer health ──────────────────────────────────────────────────

    async def score_customer_health(
        self,
        contact_id: UUID,
    ) -> dict[str, Any]:
        """Calculate a health score for an existing customer."""
        engagement = await self._gather_engagement(str(contact_id))

        raw = await self._llm_call(
            _HEALTH_SYSTEM_PROMPT,
            f"ENGAGEMENT DATA:\n{json.dumps(engagement, indent=2, default=str)}",
        )

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Health-score LLM returned non-JSON")
            return {
                "health_score": 0,
                "trend": "unknown",
                "reasoning": raw,
            }

    # ── stale leads ──────────────────────────────────────────────────────

    async def identify_stale_leads(
        self,
        days_threshold: int = 14,
    ) -> list[dict[str, Any]]:
        """Find leads not contacted in *days_threshold* days and suggest
        re-engagement strategies."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)

        if self._crm is not None:
            stale = await self._crm.get_stale_leads(cutoff)
        else:
            stale = []
            logger.info("CRM not connected; stale-lead detection unavailable")
            return stale

        if not stale:
            return []

        raw = await self._llm_call(
            _REENGAGE_SYSTEM_PROMPT,
            f"STALE LEADS (>{days_threshold} days):\n"
            + json.dumps(stale[:20], indent=2, default=str),
        )

        try:
            strategies = json.loads(raw)
            if isinstance(strategies, list):
                return strategies
        except (json.JSONDecodeError, TypeError):
            logger.warning("Re-engagement LLM returned non-JSON")

        return [{"raw": raw}]

    # ── company intelligence ─────────────────────────────────────────────

    async def generate_lead_intelligence(
        self,
        company_name: str,
    ) -> dict[str, Any]:
        """Gather real-time intelligence about a company from web and news."""
        kb_results = await self._retriever.search(
            query=f"{company_name} company profile industry",
            limit=5,
        )

        news_results = await self._fetch_news(company_name)

        context_lines = [
            f"Company: {company_name}",
            "",
            "KNOWLEDGE BASE:",
            *[r.get("content", "")[:400] for r in kb_results],
            "",
            "NEWS RESULTS:",
            *[f"- {n}" for n in news_results[:10]],
        ]

        raw = await self._llm_call(_INTEL_SYSTEM_PROMPT, "\n".join(context_lines))

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Intel LLM returned non-JSON")
            return {"raw": raw}

    # ── internal helpers ─────────────────────────────────────────────────

    async def _enrich_contact(self, contact: Contact) -> dict[str, Any]:
        """Pull CRM history and KB context for a contact."""
        enrichment: dict[str, Any] = {}

        if self._crm is not None:
            deals = await self._crm.get_deals_for_contact(str(contact.id))
            interactions = await self._crm.get_interactions_for_contact(str(contact.id))
            enrichment["deal_history"] = deals[:10]
            enrichment["recent_interactions"] = interactions[:10]

        if contact.company:
            kb = await self._retriever.search(
                query=f"{contact.company} {contact.industry or ''}",
                limit=5,
            )
            enrichment["knowledge_base"] = [r.get("content", "")[:300] for r in kb]

        return enrichment

    async def _gather_engagement(self, contact_id: str) -> dict[str, Any]:
        """Collect engagement metrics for health scoring."""
        if self._crm is None:
            return {"note": "CRM not connected"}

        interactions = await self._crm.get_interactions_for_contact(contact_id)
        deals = await self._crm.get_deals_for_contact(contact_id)

        return {
            "total_interactions": len(interactions),
            "recent_interactions": interactions[:15],
            "total_deals": len(deals),
            "deals": deals[:10],
        }

    async def _fetch_news(self, company_name: str) -> list[str]:
        """Fetch recent news headlines from Newsdata.io."""
        if not self._newsdata_key:
            logger.debug("No Newsdata API key; skipping news fetch")
            return []

        params = {
            "apikey": self._newsdata_key,
            "q": company_name,
            "language": "en",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://newsdata.io/api/1/news",
                    params=params,
                )
                resp.raise_for_status()
                articles = resp.json().get("results", [])
                return [
                    f"{a.get('title', '')} — {a.get('source_id', '')}"
                    for a in articles
                    if a.get("title")
                ]
        except (httpx.HTTPError, KeyError):
            logger.exception("Newsdata fetch failed for '%s'", company_name)
            return []

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return "(No OpenAI key configured)"

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("LLM call failed in SalesIntelligence")
            return "(LLM call failed)"
