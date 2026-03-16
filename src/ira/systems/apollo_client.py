"""Apollo.io API client for contact and company enrichment.

- People: POST /people/match — enrich contact by email, name, or domain.
- Organizations: POST /organizations/enrich (single) or /organizations/bulk_enrich (up to 10).
Consumes Apollo credits per call.

Create an API key: Apollo Settings > Integrations > API Keys > Create new key.
Set APOLLO_API_KEY in .env.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ira.config import ApolloConfig, get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.apollo.io/api/v1"


class ApolloError(Exception):
    """Raised when an Apollo API call fails."""


def _get_client(config: ApolloConfig | None = None) -> ApolloConfig:
    return config or get_settings().apollo


def _normalize_domain(domain: str | None) -> str | None:
    """Strip www., @, and whitespace. Returns None if empty or invalid."""
    if not domain or not isinstance(domain, str):
        return None
    d = domain.strip().lower().replace("www.", "").split("@")[-1]
    return d if d and "." in d else None


def enrich_person(
    *,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    name: str | None = None,
    domain: str | None = None,
    organization_name: str | None = None,
    config: ApolloConfig | None = None,
) -> dict[str, Any] | None:
    """Enrich one person via Apollo People Enrichment API.

    Pass at least one of: email, (first_name + last_name or name), or domain.
    Returns the enriched person dict (with title, company, linkedin_url, etc.)
    or None if no key, no match, or API error. Does not reveal personal emails
    or phone numbers (no extra credits).
    """
    cfg = _get_client(config)
    api_key = cfg.api_key.get_secret_value()
    if not api_key or not api_key.strip():
        logger.debug("Apollo API key not set — skipping enrichment")
        return None

    params: dict[str, str | bool] = {}
    if email and "@" in email:
        params["email"] = email.strip()
    if first_name:
        params["first_name"] = first_name.strip()
    if last_name:
        params["last_name"] = last_name.strip()
    if name:
        params["name"] = name.strip()
    if domain:
        params["domain"] = domain.strip().replace("www.", "")
    if organization_name:
        params["organization_name"] = organization_name.strip()

    if not params:
        logger.debug("Apollo enrich_person: no identifier provided")
        return None

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_BASE_URL}/people/match",
                params=params,
                headers={"Content-Type": "application/json", "x-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Apollo people/match HTTP %s: %s", exc.response.status_code, exc.response.text[:200])
        return None
    except Exception as exc:
        logger.warning("Apollo people/match failed: %s", exc)
        return None

    person = data.get("person")
    if not person:
        return None

    org = person.get("organization")
    if not isinstance(org, dict):
        org = {}
    org_name = org.get("name")
    org_primary_domain = _normalize_domain(org.get("primary_domain") or org.get("website_url"))

    # Return a flat summary useful for CRM/agents (avoid huge employment_history by default)
    return {
        "id": person.get("id"),
        "first_name": person.get("first_name"),
        "last_name": person.get("last_name"),
        "name": person.get("name"),
        "title": person.get("title"),
        "email": person.get("email"),
        "linkedin_url": person.get("linkedin_url"),
        "organization_name": org_name,
        "organization_id": person.get("organization_id"),
        "organization_primary_domain": org_primary_domain,
    }


def enrich_organization(
    *,
    domain: str,
    config: ApolloConfig | None = None,
) -> dict[str, Any] | None:
    """Enrich one company via Apollo Organization Enrichment API.

    Pass company domain (e.g. 'apollo.io', no www/@). Returns normalized dict
    with industry, website, employee_count, region, or None if no key, no match, or error.
    """
    cfg = _get_client(config)
    api_key = cfg.api_key.get_secret_value()
    if not api_key or not api_key.strip():
        logger.debug("Apollo API key not set — skipping organization enrichment")
        return None

    domain = _normalize_domain(domain)
    if not domain:
        logger.debug("Apollo enrich_organization: no valid domain provided")
        return None

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_BASE_URL}/organizations/enrich",
                params={"domain": domain},
                headers={"Content-Type": "application/json", "x-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Apollo organizations/enrich HTTP %s: %s",
            exc.response.status_code,
            (exc.response.text or "")[:200],
        )
        return None
    except Exception as exc:
        logger.warning("Apollo organizations/enrich failed: %s", exc)
        return None

    org = data.get("organization") if isinstance(data.get("organization"), dict) else data
    if not org:
        return None

    # Map to CRM CompanyModel-like fields: industry, website, employee_count, region
    region_parts = [org.get("state"), org.get("country")]
    region = ", ".join(p for p in region_parts if p) or None
    return {
        "name": org.get("name"),
        "industry": org.get("industry"),
        "website": org.get("website_url") or org.get("primary_domain"),
        "employee_count": org.get("estimated_num_employees"),
        "region": region,
        "primary_domain": _normalize_domain(org.get("primary_domain") or org.get("website_url")),
    }


def enrich_organizations_bulk(
    domains: list[str],
    *,
    config: ApolloConfig | None = None,
) -> list[dict[str, Any]]:
    """Enrich up to 10 companies in one call. Returns list of normalized org dicts (same shape as enrich_organization)."""
    cfg = _get_client(config)
    api_key = cfg.api_key.get_secret_value()
    if not api_key or not api_key.strip():
        logger.debug("Apollo API key not set — skipping bulk organization enrichment")
        return []

    normalized = [_normalize_domain(d) for d in domains if d]
    normalized = list(dict.fromkeys([d for d in normalized if d]))[:10]
    if not normalized:
        return []

    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                f"{_BASE_URL}/organizations/bulk_enrich",
                params=[("domains[]", d) for d in normalized],
                headers={"Content-Type": "application/json", "x-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Apollo organizations/bulk_enrich HTTP %s: %s",
            exc.response.status_code,
            (exc.response.text or "")[:200],
        )
        return []
    except Exception as exc:
        logger.warning("Apollo organizations/bulk_enrich failed: %s", exc)
        return []

    orgs = data.get("organizations") or []
    result = []
    for org in orgs:
        if not isinstance(org, dict):
            continue
        region_parts = [org.get("state"), org.get("country")]
        region = ", ".join(p for p in region_parts if p) or None
        result.append({
            "name": org.get("name"),
            "industry": org.get("industry"),
            "website": org.get("website_url") or org.get("primary_domain"),
            "employee_count": org.get("estimated_num_employees"),
            "region": region,
            "primary_domain": _normalize_domain(org.get("primary_domain") or org.get("website_url")),
        })
    return result


async def enrich_person_async(
    *,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    name: str | None = None,
    domain: str | None = None,
    organization_name: str | None = None,
    config: ApolloConfig | None = None,
) -> dict[str, Any] | None:
    """Async wrapper for enrich_person (for use in agent tools)."""
    import asyncio
    return await asyncio.to_thread(
        enrich_person,
        email=email,
        first_name=first_name,
        last_name=last_name,
        name=name,
        domain=domain,
        organization_name=organization_name,
        config=config,
    )
