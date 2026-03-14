"""Backfill Neo4j from existing Qdrant chunks: scroll → entity extraction → graph write.

Use for one-time or occasional sync of graph data from chunk content that was
already stored in Qdrant (e.g. after restore or to re-run extraction with a
better model). Uses MERGE so duplicates are idempotent.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.exceptions import DatabaseError

logger = logging.getLogger(__name__)


async def run_backfill_from_qdrant(
    qdrant: QdrantManager,
    graph: KnowledgeGraph,
    *,
    max_chunks: int | None = None,
    batch_size: int = 200,
    source_category: str | None = None,
) -> dict[str, Any]:
    """Scroll Qdrant chunks, extract entities from content, write to Neo4j.

    Same entity/relationship logic as DigestiveSystem._extract_entities.
    Returns stats: chunks_processed, companies, people, machines, relationships.
    """
    stats: dict[str, int] = {
        "chunks_processed": 0,
        "companies": 0,
        "people": 0,
        "machines": 0,
        "relationships": 0,
        "errors": 0,
    }
    async for batch in qdrant.scroll_collection_payloads(
        batch_size=batch_size,
        max_points=max_chunks,
        source_category=source_category,
    ):
        for item in batch:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            point_id = item.get("point_id") or ""
            source = item.get("source", "")
            source_category_item = item.get("source_category", "")
            try:
                extracted = await graph.extract_entities_from_text(content)
            except (DatabaseError, Exception):
                logger.debug("Entity extraction failed for chunk from %s", source, exc_info=True)
                stats["errors"] += 1
                continue

            for company in extracted.get("companies", []):
                if company.get("name"):
                    try:
                        await graph.add_company(
                            name=company["name"],
                            region=company.get("region", ""),
                            industry=company.get("industry", ""),
                            website=company.get("website", ""),
                        )
                        stats["companies"] += 1
                    except (DatabaseError, Exception):
                        logger.debug("Failed to add company %s", company.get("name"), exc_info=True)

            for person in extracted.get("people", []):
                if person.get("name"):
                    try:
                        await graph.add_person(
                            name=person["name"],
                            email=person.get("email", ""),
                            company_name=person.get("company", ""),
                            role=person.get("role", ""),
                        )
                        stats["people"] += 1
                    except (DatabaseError, Exception):
                        logger.debug("Failed to add person %s", person.get("name"), exc_info=True)

            for machine in extracted.get("machines", []):
                if machine.get("model"):
                    try:
                        await graph.add_machine(
                            model=machine["model"],
                            category=machine.get("category", ""),
                            description=machine.get("description", ""),
                        )
                        stats["machines"] += 1
                    except (DatabaseError, Exception):
                        logger.debug("Failed to add machine %s", machine.get("model"), exc_info=True)

            for rel in extracted.get("relationships", []):
                try:
                    ok = await graph.add_relationship(
                        from_type=rel.get("from_type", ""),
                        from_key=rel.get("from_key", ""),
                        rel_type=rel.get("rel", ""),
                        to_type=rel.get("to_type", ""),
                        to_key=rel.get("to_key", ""),
                        properties={
                            k: v for k, v in rel.items()
                            if k not in ("from_type", "from_key", "rel", "to_type", "to_key")
                        },
                    )
                    if ok:
                        stats["relationships"] += 1
                except (DatabaseError, Exception):
                    logger.debug("Failed to add relationship %s", rel, exc_info=True)

            # Link this Qdrant chunk to Neo4j (Chunk node + DESCRIBES edges) for denser network
            entity_refs: list[tuple[str, str]] = []
            for c in extracted.get("companies", []):
                if c.get("name"):
                    entity_refs.append(("Company", c["name"]))
            for p in extracted.get("people", []):
                if p.get("email"):
                    entity_refs.append(("Person", p["email"]))
            for m in extracted.get("machines", []):
                if m.get("model"):
                    entity_refs.append(("Machine", m["model"]))
            for q in extracted.get("quotes", []):
                if q.get("quote_id"):
                    entity_refs.append(("Quote", q["quote_id"]))
            if point_id and entity_refs:
                try:
                    await graph.add_chunk_and_describes(
                        qdrant_point_id=point_id,
                        source=source,
                        source_category=source_category_item,
                        content_preview=content[:500],
                        entity_refs=entity_refs,
                    )
                except (DatabaseError, Exception):
                    logger.debug("Failed to add Chunk/DESCRIBES for point %s", point_id, exc_info=True)

            stats["chunks_processed"] += 1

            # Progress every 10 chunks so the run doesn't look stuck
            if stats["chunks_processed"] % 10 == 0:
                logger.info(
                    "Backfill progress: %d chunks, companies=%d people=%d machines=%d rels=%d",
                    stats["chunks_processed"],
                    stats["companies"],
                    stats["people"],
                    stats["machines"],
                    stats["relationships"],
                )

        # Final batch progress
        if stats["chunks_processed"] and stats["chunks_processed"] % 10 != 0:
            logger.info(
                "Backfill progress: %d chunks, companies=%d people=%d machines=%d rels=%d",
                stats["chunks_processed"],
                stats["companies"],
                stats["people"],
                stats["machines"],
                stats["relationships"],
            )

    return stats
