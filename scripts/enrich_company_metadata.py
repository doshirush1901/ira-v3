"""Enrich Neo4j Company nodes with region/industry via LLM classification.

For companies missing metadata, fetches DESCRIBES chunk previews and uses
the LLM to classify region and industry. Also enriches SUPPLIES edge
properties with component_type.

Usage:
    python scripts/enrich_company_metadata.py                    # classify companies
    python scripts/enrich_company_metadata.py --max 200          # limit to 200
    python scripts/enrich_company_metadata.py --mode edges       # enrich edge properties
    python scripts/enrich_company_metadata.py --mode edges --max 100
    python scripts/enrich_company_metadata.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402
from ira.services.llm_client import get_llm_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

CLASSIFY_TEMPLATE = (
    "You are classifying a company for Machinecraft's knowledge graph.\n"
    "Machinecraft is an Indian thermoforming machine OEM.\n\n"
    "Given the company name and text excerpts where it appears, determine:\n"
    '1. region: the country or region (e.g. "India", "Germany", "UK", "USA", "Turkey", "Japan")\n'
    '2. industry: a short industry label (e.g. "Automotive", "Packaging", "Plastics", '
    '"Industrial Machinery", "Thermoforming", "Chemicals", "Exhibition", "Logistics")\n\n'
    'Return ONLY valid JSON: {{"region": "...", "industry": "..."}}\n'
    "If you cannot determine a field, use empty string.\n\n"
    "Company: {company_name}\n"
    "Context:\n{context}"
)

EDGE_TEMPLATE = (
    "Given the supplier-customer relationship and text context, determine what "
    'the supplier provides. Return ONLY valid JSON: {{"component_type": "..."}}\n\n'
    "Supplier: {supplier}\n"
    "Customer: {customer}\n"
    "Context:\n{context}"
)


async def enrich_companies(max_count: int = 500, dry_run: bool = False) -> dict[str, int]:
    graph = KnowledgeGraph()
    llm = get_llm_client()
    stats = {"processed": 0, "enriched": 0, "errors": 0}

    try:
        companies = await graph.run_cypher(
            "MATCH (c:Company) "
            "WHERE (c.region IS NULL OR c.region = '') AND (c.industry IS NULL OR c.industry = '') "
            "OPTIONAL MATCH (ch:Chunk)-[:DESCRIBES]->(c) "
            "WITH c.name AS name, collect(ch.content_preview)[..3] AS previews, count(ch) AS chunk_count "
            "RETURN name, previews, chunk_count "
            "ORDER BY chunk_count DESC "
            "LIMIT $limit",
            {"limit": max_count},
        )
        logger.info("Companies to enrich: %d", len(companies))

        for row in companies:
            name = row.get("name", "")
            if not name:
                continue

            previews = row.get("previews", [])
            context = "\n".join(p for p in previews if p) if previews else "(no context available)"

            prompt = CLASSIFY_TEMPLATE.format(company_name=name, context=context[:2000])

            try:
                response = await llm.generate_text(
                    "You classify companies by region and industry.",
                    prompt,
                    name="enrich_company_metadata",
                )
                data = json.loads(response.strip().strip("`").strip())
                region = data.get("region", "")
                industry = data.get("industry", "")

                if dry_run:
                    logger.info("[DRY] %s -> region=%s, industry=%s", name, region, industry)
                elif region or industry:
                    await graph._run_cypher_write(
                        "MATCH (c:Company {name: $name}) SET c.region = $region, c.industry = $industry",
                        {"name": name, "region": region, "industry": industry},
                    )
                    stats["enriched"] += 1
            except Exception:
                logger.debug("Failed to classify %s", name, exc_info=True)
                stats["errors"] += 1

            stats["processed"] += 1
            if stats["processed"] % 50 == 0:
                logger.info("Progress: %d/%d processed, %d enriched", stats["processed"], len(companies), stats["enriched"])

        logger.info("Company enrichment done: %s", stats)
    finally:
        await graph.close()
    return stats


async def enrich_edges(max_count: int = 200, dry_run: bool = False) -> dict[str, int]:
    graph = KnowledgeGraph()
    llm = get_llm_client()
    stats = {"processed": 0, "enriched": 0, "errors": 0}

    try:
        edges = await graph.run_cypher(
            "MATCH (a:Company)-[r:SUPPLIES]->(b:Company) "
            "WHERE r.component_type IS NULL "
            "OPTIONAL MATCH (a)<-[:DESCRIBES]-(ch:Chunk) "
            "WITH a, b, r, collect(ch.content_preview)[..2] AS previews "
            "RETURN a.name AS supplier, b.name AS customer, previews "
            "LIMIT $limit",
            {"limit": max_count},
        )
        logger.info("SUPPLIES edges to enrich: %d", len(edges))

        for row in edges:
            supplier = row.get("supplier", "")
            customer = row.get("customer", "")
            previews = row.get("previews", [])
            context = "\n".join(p for p in previews if p) if previews else "(no context)"

            prompt = EDGE_TEMPLATE.format(supplier=supplier, customer=customer, context=context[:2000])

            try:
                response = await llm.generate_text(
                    "You classify supplier relationships.",
                    prompt,
                    name="enrich_edge_props",
                )
                data = json.loads(response.strip().strip("`").strip())
                comp_type = data.get("component_type", "")

                if dry_run:
                    logger.info("[DRY] %s -> %s: component_type=%s", supplier, customer, comp_type)
                elif comp_type:
                    await graph._run_cypher_write(
                        "MATCH (a:Company {name: $supplier})-[r:SUPPLIES]->(b:Company {name: $customer}) "
                        "SET r.component_type = $ct",
                        {"supplier": supplier, "customer": customer, "ct": comp_type},
                    )
                    stats["enriched"] += 1
            except Exception:
                logger.debug("Failed to enrich %s->%s", supplier, customer, exc_info=True)
                stats["errors"] += 1

            stats["processed"] += 1
            if stats["processed"] % 50 == 0:
                logger.info("Progress: %d/%d processed, %d enriched", stats["processed"], len(edges), stats["enriched"])

        logger.info("Edge enrichment done: %s", stats)
    finally:
        await graph.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich Neo4j company metadata and edge properties via LLM")
    parser.add_argument("--mode", choices=["companies", "edges"], default="companies")
    parser.add_argument("--max", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mode == "companies":
        asyncio.run(enrich_companies(max_count=args.max, dry_run=args.dry_run))
    else:
        asyncio.run(enrich_edges(max_count=args.max, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
