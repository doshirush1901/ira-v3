"""Bulk sync CRM data (deals, contacts, companies) to Neo4j graph.

Reads all CRM records from PostgreSQL and creates/updates corresponding
Neo4j nodes and relationships with properties (CUSTOMER_OF with since/status,
WORKS_AT with role, Company with region/industry).

Usage:
    python scripts/crm_to_neo4j_sync.py
    python scripts/crm_to_neo4j_sync.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402
from ira.data.crm import CRMDatabase  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


async def sync(dry_run: bool = False) -> dict[str, int]:
    crm = CRMDatabase()
    graph = KnowledgeGraph()
    stats = {
        "companies_synced": 0,
        "contacts_synced": 0,
        "deals_synced": 0,
        "customer_of_created": 0,
        "interested_in_created": 0,
        "works_at_created": 0,
    }

    try:
        companies = await crm.list_companies()
        logger.info("CRM companies: %d", len(companies))
        for co in companies:
            name = co.name
            if not name:
                continue
            region = co.region or ""
            industry = co.industry or ""
            if dry_run:
                if region or industry:
                    logger.info("[DRY] Company: %s (region=%s, industry=%s)", name, region, industry)
            else:
                await graph.add_company(
                    name=name, region=region, industry=industry,
                    website=co.website or "",
                )
            stats["companies_synced"] += 1

        deals = await crm.list_deals_with_details(limit=500)
        logger.info("CRM deals: %d", len(deals))
        for deal in deals:
            company_name = deal.get("company_name", "")
            machine = deal.get("machine_model", "")
            stage = deal.get("stage", "")
            created = deal.get("created_at")
            value = deal.get("value")

            if not company_name:
                continue

            since = ""
            if created:
                since = str(created)[:10] if hasattr(created, "isoformat") else str(created)[:10]

            status_map = {
                "NEW": "inquiry",
                "CONTACTED": "contacted",
                "QUALIFIED": "qualified",
                "PROPOSAL": "proposal",
                "NEGOTIATION": "negotiation",
                "WON": "delivered",
                "LOST": "lost",
            }
            status = status_map.get(stage, stage)

            props = {}
            if since:
                props["since"] = since
            if machine and machine != "thermoforming_machine":
                props["machine_model"] = machine
            if status:
                props["status"] = status
            if value and float(value) > 0:
                props["value"] = str(value)

            if dry_run:
                logger.info(
                    "[DRY] CUSTOMER_OF: %s -> Machinecraft %s", company_name, props,
                )
            else:
                await graph.add_company(name=company_name)
                ok = await graph.add_relationship(
                    from_type="Company",
                    from_key=company_name,
                    rel_type="CUSTOMER_OF",
                    to_type="Company",
                    to_key="Machinecraft",
                    properties=props,
                )
                if ok:
                    stats["customer_of_created"] += 1

                if machine and machine != "thermoforming_machine":
                    await graph.add_machine(model=machine)
                    ok2 = await graph.add_relationship(
                        from_type="Company",
                        from_key=company_name,
                        rel_type="INTERESTED_IN",
                        to_type="Machine",
                        to_key=machine,
                        properties={"stage": status} if status else {},
                    )
                    if ok2:
                        stats["interested_in_created"] += 1

            stats["deals_synced"] += 1

        contacts = await crm.list_deals_with_details(limit=1)
        # Use raw SQL for contacts with company join
        from sqlalchemy import text
        async with crm._engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT c.name, c.email, c.role, c.contact_type, c.lead_score, "
                "co.name AS company_name "
                "FROM contacts c "
                "LEFT JOIN companies co ON c.company_id = co.id"
            ))
            rows = result.fetchall()

        logger.info("CRM contacts: %d", len(rows))
        for row in rows:
            name, email, role, contact_type, lead_score, company_name = row
            if not email:
                continue

            if dry_run:
                if company_name:
                    logger.info("[DRY] WORKS_AT: %s (%s) -> %s", name, email, company_name)
            else:
                await graph.add_person(
                    name=name or "",
                    email=email,
                    company_name=company_name or "",
                    role=role or "",
                )
                stats["works_at_created"] += 1

            stats["contacts_synced"] += 1

        logger.info("Sync complete: %s", stats)
    finally:
        await graph.close()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk sync CRM to Neo4j")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(sync(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
