"""Ingest LinkedIn connections and company follows into Neo4j.

Parses the LinkedIn data export CSV files and creates Person->WORKS_AT->Company
relationships in the knowledge graph. Also adds followed companies.

Usage:
    python scripts/linkedin_to_neo4j.py
    python scripts/linkedin_to_neo4j.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

LINKEDIN_DIR = Path(
    "data/imports/16_LINKEDIN DATA/Complete_LinkedInDataExport_03-03-2026.zip"
)


def parse_connections(repo_root: Path) -> list[dict[str, str]]:
    path = repo_root / LINKEDIN_DIR / "Connections.csv"
    if not path.exists():
        logger.error("Connections.csv not found at %s", path)
        return []

    connections = []
    with open(path, encoding="utf-8") as f:
        for _ in range(3):
            next(f)
        reader = csv.DictReader(f)
        for row in reader:
            first = (row.get("First Name") or "").strip()
            last = (row.get("Last Name") or "").strip()
            name = f"{first} {last}".strip()
            if not name:
                continue
            connections.append({
                "name": name,
                "email": (row.get("Email Address") or "").strip(),
                "company": (row.get("Company") or "").strip(),
                "position": (row.get("Position") or "").strip(),
                "url": (row.get("URL") or "").strip(),
                "connected_on": (row.get("Connected On") or "").strip(),
            })
    return connections


def parse_company_follows(repo_root: Path) -> list[str]:
    path = repo_root / LINKEDIN_DIR / "Company Follows.csv"
    if not path.exists():
        return []
    companies = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Organization") or "").strip()
            if name:
                companies.append(name)
    return companies


async def ingest(dry_run: bool = False) -> dict[str, int]:
    repo_root = Path(__file__).resolve().parent.parent
    stats = {"persons": 0, "companies": 0, "works_at": 0, "follows": 0, "skipped": 0}

    connections = parse_connections(repo_root)
    logger.info("Parsed %d LinkedIn connections", len(connections))

    follows = parse_company_follows(repo_root)
    logger.info("Parsed %d company follows", len(follows))

    if dry_run:
        for c in connections[:10]:
            logger.info("[DRY] %s (%s) at %s - %s", c["name"], c["email"], c["company"], c["position"])
        logger.info("[DRY] ... and %d more", len(connections) - 10)
        for co in follows[:5]:
            logger.info("[DRY] Follow: %s", co)
        return stats

    graph = KnowledgeGraph()
    try:
        for i, c in enumerate(connections, 1):
            name = c["name"]
            email = c["email"] or c["url"] or name
            company = c["company"]
            position = c["position"]

            if not company:
                stats["skipped"] += 1
                continue

            try:
                await graph.add_company(name=company)
                stats["companies"] += 1

                await graph.add_person(
                    name=name,
                    email=email,
                    company_name=company,
                    role=position,
                )
                stats["persons"] += 1
                stats["works_at"] += 1
            except Exception:
                logger.debug("Failed for %s at %s", name, company, exc_info=True)

            if i % 200 == 0:
                logger.info("Progress: %d/%d connections", i, len(connections))

        for co in follows:
            try:
                await graph.add_company(name=co)
                stats["follows"] += 1
            except Exception:
                logger.debug("Failed to add followed company %s", co, exc_info=True)

        logger.info("LinkedIn ingestion done: %s", stats)
    finally:
        await graph.close()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest LinkedIn data into Neo4j")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(ingest(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
