"""Sync CRM contacts and companies with Apollo.io enrichment.

Used by CLI (ira crm sync-apollo), API (POST /api/crm/sync-apollo), and agent tool.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ira.data.crm import CRMDatabase
from ira.data.models import ContactType
from ira.systems.apollo_client import enrich_person, enrich_organizations_bulk

logger = logging.getLogger(__name__)

_DELAY_SECONDS = 0.8
_BULK_ORG_BATCH = 10

_SKIP_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "outlook.com",
    "hotmail.com", "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com",
    "mail.com", "zoho.com", "yandex.com", "gmx.com", "fastmail.com",
})


def _domain_from_contact(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.strip().lower().split("@")[-1]
    return None if domain in _SKIP_EMAIL_DOMAINS else domain


async def sync_crm_with_apollo(
    crm: CRMDatabase,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    contact_type: str | None = None,
    contacts_only: bool = False,
) -> dict[str, Any]:
    """Run Apollo enrichment for CRM contacts and their companies.

    Returns a dict with keys: contacts_updated, companies_updated, skipped_no_email,
    no_match, errors, contact_type_error (only set if contact_type was invalid).
    """
    result: dict[str, Any] = {
        "contacts_updated": 0,
        "companies_updated": 0,
        "skipped_no_email": 0,
        "no_match": 0,
        "errors": 0,
    }

    filters: dict[str, Any] = {}
    if contact_type:
        try:
            filters["contact_type"] = ContactType(contact_type)
        except ValueError:
            result["contact_type_error"] = f"Invalid contact_type. Use one of: {[e.value for e in ContactType]}"
            return result

    contacts = await crm.list_contacts(filters=filters or None)
    if not contacts:
        return result

    if limit:
        contacts = contacts[:limit]

    company_domains: dict[str, str] = {}

    for i, contact in enumerate(contacts):
        email = (contact.email or "").strip().lower()
        if not email or "@" not in email:
            result["skipped_no_email"] += 1
            continue

        name = (contact.name or "").strip() or None
        company_name = (contact.company.name or "").strip() if contact.company else None

        person_result = enrich_person(
            email=email,
            name=name,
            organization_name=company_name,
        )
        await asyncio.sleep(_DELAY_SECONDS)

        if person_result is None:
            result["no_match"] += 1
            continue

        title = person_result.get("title")
        linkedin_url = person_result.get("linkedin_url")
        if not dry_run:
            try:
                tags = dict(contact.tags or {})
                if linkedin_url:
                    tags["linkedin_url"] = linkedin_url
                from datetime import datetime, timezone
                tags["apollo_enriched_at"] = datetime.now(timezone.utc).isoformat()
                kwargs: dict[str, Any] = {"tags": tags}
                if title:
                    kwargs["role"] = title
                await crm.update_contact(contact.id, **kwargs)
                result["contacts_updated"] += 1
            except Exception as exc:
                result["errors"] += 1
                logger.warning("Failed to update contact %s: %s", email, exc)
        else:
            result["contacts_updated"] += 1

        if not contacts_only and contact.company_id:
            domain = person_result.get("organization_primary_domain") or _domain_from_contact(email)
            if domain and contact.company_id not in company_domains:
                company_domains[str(contact.company_id)] = domain

    if contacts_only or not company_domains:
        return result

    unique_domains = list(dict.fromkeys(company_domains.values()))
    domain_to_company_ids: dict[str, list[str]] = {}
    for cid, dom in company_domains.items():
        domain_to_company_ids.setdefault(dom, []).append(cid)

    for offset in range(0, len(unique_domains), _BULK_ORG_BATCH):
        batch = unique_domains[offset : offset + _BULK_ORG_BATCH]
        orgs = enrich_organizations_bulk(batch)
        await asyncio.sleep(_DELAY_SECONDS)

        org_by_domain = {o["primary_domain"]: o for o in orgs if o and o.get("primary_domain")}

        for domain in batch:
            org = org_by_domain.get(domain)
            if not org:
                continue
            for company_id in domain_to_company_ids.get(domain, []):
                company = await crm.get_company(company_id)
                if not company:
                    continue
                updates: dict[str, Any] = {}
                if org.get("industry") is not None:
                    updates["industry"] = org["industry"]
                if org.get("website") is not None:
                    updates["website"] = org["website"]
                if org.get("employee_count") is not None:
                    updates["employee_count"] = org["employee_count"]
                if org.get("region") is not None:
                    updates["region"] = org["region"]
                if not updates:
                    continue
                if not dry_run:
                    try:
                        await crm.update_company(company_id, **updates)
                        result["companies_updated"] += 1
                    except Exception as exc:
                        logger.warning("Failed to update company %s: %s", company_id, exc)
                else:
                    result["companies_updated"] += 1

    return result
