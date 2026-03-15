"""Ingest Mem0 memories into Neo4j as entities and relationships.

Fetches all memories for configured user IDs from the Mem0 cloud API,
extracts entities (companies, people, machines) using the KnowledgeGraph
LLM extractor, and writes them to Neo4j with ``source: "mem0"`` provenance.

Usage:
    python scripts/mem0_to_neo4j.py
    python scripts/mem0_to_neo4j.py --dry-run
    python scripts/mem0_to_neo4j.py --user-ids rushabh_doshi
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402
from ira.config import get_settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_USER_IDS = ["rushabh_doshi", "rushabh@machinecraft.org"]


async def fetch_mem0_memories(api_key: str, user_id: str) -> list[dict[str, Any]]:
    """Fetch all memories for a user from the Mem0 REST API."""
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.mem0.ai/v1/memories/",
            headers=headers,
            params={"user_id": user_id},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        return []


async def ingest_memories(
    user_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch Mem0 memories, extract entities, write to Neo4j."""
    settings = get_settings()
    api_key = settings.memory.api_key.get_secret_value()
    if not api_key:
        logger.error("MEM0_API_KEY not set; cannot fetch memories")
        return {}

    ids = user_ids or DEFAULT_USER_IDS
    graph = KnowledgeGraph()

    stats: dict[str, int] = {
        "memories_fetched": 0,
        "companies": 0,
        "people": 0,
        "machines": 0,
        "relationships": 0,
        "errors": 0,
    }

    try:
        before = await _count(graph)
        logger.info(
            "Before: %d nodes, %d relationships, %d orphans",
            before["nodes"], before["relationships"], before["orphans"],
        )

        all_memories: list[dict[str, Any]] = []
        for uid in ids:
            memories = await fetch_mem0_memories(api_key, uid)
            logger.info("Fetched %d memories for user_id=%s", len(memories), uid)
            all_memories.extend(memories)

        stats["memories_fetched"] = len(all_memories)

        for i, mem in enumerate(all_memories, 1):
            text = mem.get("memory", "")
            if not text or len(text) < 10:
                continue

            logger.info("[%d/%d] Extracting entities from: %.100s...", i, len(all_memories), text)

            try:
                extracted = await graph.extract_entities_from_text(text)
            except Exception:
                logger.debug("Extraction failed for memory %d", i, exc_info=True)
                stats["errors"] += 1
                continue

            if dry_run:
                _log_extracted(extracted, text)
                continue

            await _write_entities(graph, extracted, stats)

        after = await _count(graph)
        logger.info(
            "After: %d nodes, %d relationships, %d orphans",
            after["nodes"], after["relationships"], after["orphans"],
        )
        logger.info(
            "Delta: %+d nodes, %+d relationships, %+d orphans",
            after["nodes"] - before["nodes"],
            after["relationships"] - before["relationships"],
            after["orphans"] - before["orphans"],
        )
        logger.info(
            "Stats: %d memories, %d companies, %d people, %d machines, %d rels, %d errors",
            stats["memories_fetched"], stats["companies"], stats["people"],
            stats["machines"], stats["relationships"], stats["errors"],
        )
    finally:
        await graph.close()

    return stats


async def _write_entities(
    graph: KnowledgeGraph,
    extracted: dict[str, Any],
    stats: dict[str, int],
) -> None:
    """Write extracted entities and relationships to Neo4j."""
    for company in extracted.get("companies", []):
        name = company.get("name", "")
        if not name:
            continue
        try:
            await graph.add_company(
                name=name,
                region=company.get("region", ""),
                industry=company.get("industry", ""),
                website=company.get("website", ""),
            )
            stats["companies"] += 1
        except Exception:
            logger.debug("Failed to add company %s", name, exc_info=True)

    for person in extracted.get("people", []):
        name = person.get("name", "")
        if not name:
            continue
        try:
            await graph.add_person(
                name=name,
                email=person.get("email", ""),
                company_name=person.get("company", ""),
                role=person.get("role", ""),
            )
            stats["people"] += 1
        except Exception:
            logger.debug("Failed to add person %s", name, exc_info=True)

    for machine in extracted.get("machines", []):
        model = machine.get("model", "")
        if not model:
            continue
        try:
            await graph.add_machine(
                model=model,
                category=machine.get("category", ""),
                description=machine.get("description", ""),
            )
            stats["machines"] += 1
        except Exception:
            logger.debug("Failed to add machine %s", model, exc_info=True)

    for rel in extracted.get("relationships", []):
        try:
            ok = await graph.add_relationship(
                from_type=rel.get("from_type", ""),
                from_key=rel.get("from_key", ""),
                rel_type=rel.get("rel", ""),
                to_type=rel.get("to_type", ""),
                to_key=rel.get("to_key", ""),
            )
            if ok:
                stats["relationships"] += 1
        except Exception:
            logger.debug("Failed to add relationship %s", rel, exc_info=True)


def _log_extracted(extracted: dict[str, Any], text: str) -> None:
    """Log what would be written in dry-run mode."""
    companies = extracted.get("companies", [])
    people = extracted.get("people", [])
    machines = extracted.get("machines", [])
    rels = extracted.get("relationships", [])
    if not any([companies, people, machines, rels]):
        return
    logger.info("  [DRY RUN] From: %.80s...", text)
    for c in companies:
        logger.info("    Company: %s (region=%s)", c.get("name"), c.get("region", ""))
    for p in people:
        logger.info("    Person: %s (%s)", p.get("name"), p.get("email", ""))
    for m in machines:
        logger.info("    Machine: %s", m.get("model"))
    for r in rels:
        logger.info(
            "    Rel: (%s:%s)-[%s]->(%s:%s)",
            r.get("from_type"), r.get("from_key"),
            r.get("rel"), r.get("to_type"), r.get("to_key"),
        )


async def _count(graph: KnowledgeGraph) -> dict[str, int]:
    rows = await graph.run_cypher("MATCH (n) RETURN count(n) AS nodes")
    nodes = rows[0]["nodes"] if rows else 0
    rows = await graph.run_cypher("MATCH ()-[r]->() RETURN count(r) AS rels")
    rels = rows[0]["rels"] if rows else 0
    rows = await graph.run_cypher("MATCH (n) WHERE NOT (n)--() RETURN count(n) AS orphans")
    orphans = rows[0]["orphans"] if rows else 0
    return {"nodes": nodes, "relationships": rels, "orphans": orphans}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Mem0 memories into Neo4j graph")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--user-ids", type=str, default=None,
        help=f"Comma-separated Mem0 user IDs (default: {', '.join(DEFAULT_USER_IDS)})",
    )
    args = parser.parse_args()

    user_ids = args.user_ids.split(",") if args.user_ids else None
    asyncio.run(ingest_memories(user_ids=user_ids, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
