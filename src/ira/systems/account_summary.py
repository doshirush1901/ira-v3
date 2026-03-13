"""LLM-generated account summaries for CRM contacts.

Gathers context from CRM (contact, company, deals, interactions) and
optionally from data/imports/24_WebSite_Leads lead context files, then
produces a short prose summary via LLM and stores it on the contact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from ira.data.crm import CRMDatabase
from ira.prompt_loader import load_prompt
from ira.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_IMPORTS_LEADS_DIR = Path(__file__).resolve().parents[2] / "data" / "imports" / "24_WebSite_Leads"
_ACCOUNT_SUMMARY_SYSTEM = load_prompt("account_summary")


def _find_lead_context_for_email(email: str) -> str | None:
    """Return raw text of a *_contact_context.md that contains this email, or None."""
    if not email or "@" not in email or not _IMPORTS_LEADS_DIR.is_dir():
        return None
    email_lower = email.strip().lower()
    for path in _IMPORTS_LEADS_DIR.glob("*_contact_context.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if email_lower in text.lower():
                return text
        except Exception:
            continue
    return None


async def gather_account_context(crm: CRMDatabase, contact_id: str | UUID) -> str:
    """Build a single text block of all known context for this contact for the LLM."""
    contact = await crm.get_contact(contact_id)
    if not contact:
        return ""

    parts: list[str] = []

    # Contact
    parts.append("--- CONTACT ---")
    parts.append(f"Name: {contact.name or ''}; Email: {contact.email or ''}; Role: {contact.role or ''}; Source: {contact.source or ''}; Contact type: {contact.contact_type.value if contact.contact_type else ''}; Warmth: {contact.warmth_level.value if contact.warmth_level else ''}; Lead score: {contact.lead_score or 0}")

    # Company
    company_name = None
    if contact.company_id:
        company = await crm.get_company(contact.company_id)
        if company:
            company_name = company.name
            parts.append("--- COMPANY ---")
            parts.append(f"Name: {company.name}; Region: {company.region or ''}; Industry: {company.industry or ''}; Notes: {company.notes or ''}")

    # Deals
    deals = await crm.list_deals(filters={"contact_id": contact_id})
    if deals:
        parts.append("--- DEALS ---")
        for d in deals:
            stage = d.stage.value if hasattr(d.stage, "value") else str(d.stage)
            parts.append(f"Stage: {stage}; Value: {d.value}; Machine: {d.machine_model or ''}; Updated: {d.updated_at}")

    # Interactions
    interactions = await crm.list_interactions(filters={"contact_id": contact_id}, limit=50)
    if interactions:
        parts.append("--- INTERACTIONS ---")
        for i in interactions:
            ch = i.channel.value if hasattr(i.channel, "value") else str(i.channel)
            dr = i.direction.value if hasattr(i.direction, "value") else str(i.direction)
            parts.append(f"Channel: {ch}; Direction: {dr}; Subject: {i.subject or ''}; Date: {i.created_at}")
            if i.content:
                snippet = (i.content[:500] + "...") if len(i.content) > 500 else i.content
                parts.append(f"  Content snippet: {snippet}")

    # Lead context file (imports)
    lead_text = _find_lead_context_for_email(contact.email or "")
    if lead_text:
        parts.append("--- LEAD CONTEXT (from imports) ---")
        parts.append(lead_text)

    return "\n".join(parts)


async def generate_account_summary(llm_client: LLMClient, context: str) -> str:
    """Call LLM to produce account summary from context. Returns plain text."""
    if not context.strip():
        return ""
    system = _ACCOUNT_SUMMARY_SYSTEM
    text = await llm_client.generate_text(
        system=system,
        user=context,
        temperature=0.2,
        max_tokens=1024,
        name="account_summary",
    )
    return (text or "").strip()


async def refresh_account_summary(
    crm: CRMDatabase,
    llm_client: LLMClient,
    contact_id: str | UUID,
) -> bool:
    """Gather context, generate summary, update contact. Returns True if updated."""
    context = await gather_account_context(crm, contact_id)
    if not context.strip():
        logger.warning("No context for contact %s", contact_id)
        return False
    summary = await generate_account_summary(llm_client, context)
    if not summary:
        return False
    updated = await crm.update_contact(contact_id, account_summary=summary)
    if updated:
        logger.info("Refreshed account summary for contact %s", contact_id)
    return updated is not None
