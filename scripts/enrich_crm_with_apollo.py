#!/usr/bin/env python3
"""Bulk-enrich CRM contacts and companies using Apollo.io.

- **Contacts:** Apollo People Enrichment → updates role (title), tags (linkedin_url, apollo_enriched_at).
- **Companies:** Apollo Organization Enrichment → updates industry, website, employee_count, region.

Uses Apollo credits per contact and per company. Company domain is taken from the person's
organization_primary_domain when available, otherwise from contact email domain (if not generic).

Usage:
  poetry run python scripts/enrich_crm_with_apollo.py
  poetry run python scripts/enrich_crm_with_apollo.py --dry-run
  poetry run python scripts/enrich_crm_with_apollo.py --limit 20
  poetry run python scripts/enrich_crm_with_apollo.py --contact-type LEAD_NO_INTERACTIONS
  poetry run python scripts/enrich_crm_with_apollo.py --contacts-only   # skip company enrichment

Requires: APOLLO_API_KEY in .env, database (Postgres) with CRM schema.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Project root
_root = Path(__file__).resolve().parents[1]
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

# Load .env
_env = _root / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            import os
            os.environ[k.strip()] = v.strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Import after path and env
from ira.data.crm import CRMDatabase
from ira.data.models import ContactType
from ira.systems.apollo_crm_sync import sync_crm_with_apollo


async def run(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    contact_type: str | None = None,
    contacts_only: bool = False,
) -> None:
    crm = CRMDatabase()
    result = await sync_crm_with_apollo(
        crm,
        dry_run=dry_run,
        limit=limit,
        contact_type=contact_type,
        contacts_only=contacts_only,
    )
    if result.get("contact_type_error"):
        logger.error("%s", result["contact_type_error"])
        return
    logger.info(
        "Done. contacts_updated=%d companies_updated=%d skipped_no_email=%d no_match=%d errors=%d",
        result["contacts_updated"],
        result["companies_updated"],
        result["skipped_no_email"],
        result["no_match"],
        result["errors"],
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk-enrich CRM contacts and companies with Apollo.io")
    ap.add_argument("--dry-run", action="store_true", help="Do not write to CRM, only log what would be done")
    ap.add_argument("--limit", type=int, default=None, help="Process only the first N contacts")
    ap.add_argument("--contact-type", type=str, default=None, help="Filter by contact_type (e.g. LEAD_NO_INTERACTIONS, LIVE_CUSTOMER)")
    ap.add_argument("--contacts-only", action="store_true", help="Only enrich contacts (role, LinkedIn); skip company enrichment")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit, contact_type=args.contact_type, contacts_only=args.contacts_only))


if __name__ == "__main__":
    main()
