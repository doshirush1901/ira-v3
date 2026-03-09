#!/usr/bin/env python3
"""Seed Neo4j v1 knowledge lineage nodes from ingestion + correction stores.

Creates/updates:
- (:Document {source_id})
- (:Fact {fact_id}) for ingestion summaries and correction entities
- (:Correction {correction_id})

Relationships:
- (:Fact)-[:FROM_SOURCE]->(:Document)
- (:Correction)-[:CORRECTS]->(:Fact)
- (:Fact)-[:ABOUT]->(:Company|:Person|:Machine) (best-effort)

Usage:
    poetry run python scripts/seed_neo4j_from_ingestion_log.py --apply-schema
    poetry run python scripts/seed_neo4j_from_ingestion_log.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402

INGESTION_LOG_PATH = ROOT / "data" / "brain" / "ingestion_log.json"
CORRECTIONS_DB_PATH = ROOT / "data" / "brain" / "corrections.db"
SCHEMA_PATH = ROOT / "scripts" / "neo4j_schema_v1.cypher"


def _load_ingestion_entries() -> list[dict[str, Any]]:
    if not INGESTION_LOG_PATH.exists():
        return []
    payload = json.loads(INGESTION_LOG_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for rel_path, value in payload.get("files", {}).items():
        if not isinstance(value, dict):
            continue
        source_id = str(value.get("source_id", "")).strip()
        if not source_id:
            continue
        rows.append({"rel_path": rel_path, **value})
    return rows


def _load_corrections() -> list[dict[str, Any]]:
    if not CORRECTIONS_DB_PATH.exists():
        return []
    con = sqlite3.connect(str(CORRECTIONS_DB_PATH))
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT id, entity, category, severity, old_value, new_value, source, created_at, status "
            "FROM corrections"
        )
        rows = cur.fetchall()
    finally:
        con.close()
    return [
        {
            "id": int(r[0]),
            "entity": r[1] or "",
            "category": r[2] or "GENERAL",
            "severity": r[3] or "MEDIUM",
            "old_value": r[4] or "",
            "new_value": r[5] or "",
            "source": r[6] or "",
            "created_at": r[7] or "",
            "status": r[8] or "pending",
        }
        for r in rows
    ]


def _split_cypher_statements(text: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            statements.append(tail)
    return statements


async def _apply_schema(graph: KnowledgeGraph, dry_run: bool) -> int:
    if not SCHEMA_PATH.exists():
        return 0
    statements = _split_cypher_statements(SCHEMA_PATH.read_text(encoding="utf-8"))
    if dry_run:
        print(f"[DRY RUN] Would apply {len(statements)} schema statements")
        return len(statements)
    for stmt in statements:
        await graph._run_cypher_write(stmt)
    return len(statements)


async def _seed_documents_and_facts(
    graph: KnowledgeGraph,
    rows: list[dict[str, Any]],
    dry_run: bool,
) -> int:
    writes = 0
    for row in rows:
        source_id = str(row.get("source_id", "")).strip()
        rel_path = str(row.get("rel_path", ""))
        ingested_at = str(row.get("ingested_at", ""))
        chunks_created = int(row.get("chunks_created", 0))
        entities = row.get("entities", {}) if isinstance(row.get("entities"), dict) else {}

        fact_id = f"{source_id}:ingestion"
        fact_text = (
            f"Ingested {rel_path} with {chunks_created} chunks. "
            f"Entities summary: {entities}."
        )

        if dry_run:
            writes += 1
            continue

        await graph._run_cypher_write(
            """
            MERGE (d:Document {source_id: $source_id})
            SET d.path = $path,
                d.hash = $hash,
                d.collection = $collection,
                d.pipeline = $pipeline,
                d.ingested_at = $ingested_at
            MERGE (f:Fact {fact_id: $fact_id})
            SET f.text = $fact_text,
                f.confidence = 0.9,
                f.status = 'active',
                f.updated_at = datetime()
            MERGE (f)-[:FROM_SOURCE]->(d)
            """,
            params={
                "source_id": source_id,
                "path": rel_path,
                "hash": str(row.get("hash", "")),
                "collection": str(row.get("collection", "")),
                "pipeline": str(row.get("pipeline", "")),
                "ingested_at": ingested_at,
                "fact_id": fact_id,
                "fact_text": fact_text,
            },
        )
        writes += 1
    return writes


async def _seed_corrections(graph: KnowledgeGraph, rows: list[dict[str, Any]], dry_run: bool) -> int:
    writes = 0
    for row in rows:
        correction_id = int(row["id"])
        entity = str(row.get("entity", "")).strip()
        entity_fact_id = f"entity:{entity.lower()}" if entity else f"entity:correction:{correction_id}"

        if dry_run:
            writes += 1
            continue

        await graph._run_cypher_write(
            """
            MERGE (f:Fact {fact_id: $entity_fact_id})
            ON CREATE SET f.text = $entity_text, f.confidence = 0.7, f.status = 'active', f.created_at = datetime()
            SET f.updated_at = datetime()
            MERGE (c:Correction {correction_id: $correction_id})
            SET c.entity = $entity,
                c.category = $category,
                c.severity = $severity,
                c.old_value = $old_value,
                c.new_value = $new_value,
                c.source = $source,
                c.created_at = $created_at,
                c.status = $status
            MERGE (c)-[:CORRECTS]->(f)
            """,
            params={
                "entity_fact_id": entity_fact_id,
                "entity_text": f"Entity fact for {entity}" if entity else "Entity fact placeholder",
                "correction_id": correction_id,
                "entity": entity,
                "category": str(row.get("category", "GENERAL")),
                "severity": str(row.get("severity", "MEDIUM")),
                "old_value": str(row.get("old_value", "")),
                "new_value": str(row.get("new_value", "")),
                "source": str(row.get("source", "")),
                "created_at": str(row.get("created_at", "")),
                "status": str(row.get("status", "pending")),
            },
        )
        writes += 1

        if entity:
            await graph._run_cypher_write(
                """
                MATCH (f:Fact {fact_id: $fact_id})
                OPTIONAL MATCH (c:Company {name: $entity})
                OPTIONAL MATCH (p:Person {email: $entity})
                OPTIONAL MATCH (m:Machine {model: $entity})
                FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (f)-[:ABOUT]->(c))
                FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (f)-[:ABOUT]->(p))
                FOREACH (_ IN CASE WHEN m IS NULL THEN [] ELSE [1] END | MERGE (f)-[:ABOUT]->(m))
                """,
                params={"fact_id": entity_fact_id, "entity": entity},
            )
    return writes


async def main_async(*, dry_run: bool, apply_schema: bool) -> None:
    ingestion_rows = _load_ingestion_entries()
    correction_rows = _load_corrections()
    print(f"Ingestion rows with source_id: {len(ingestion_rows)}")
    print(f"Correction rows: {len(correction_rows)}")

    graph = KnowledgeGraph()
    try:
        schema_count = await _apply_schema(graph, dry_run=dry_run) if apply_schema else 0
        document_writes = await _seed_documents_and_facts(graph, ingestion_rows, dry_run=dry_run)
        correction_writes = await _seed_corrections(graph, correction_rows, dry_run=dry_run)
    finally:
        await graph.close()

    print(
        "Done:",
        {
            "dry_run": dry_run,
            "schema_statements": schema_count,
            "document_fact_writes": document_writes,
            "correction_writes": correction_writes,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Neo4j lineage/facts from Ira stores")
    parser.add_argument("--dry-run", action="store_true", help="Preview writes without applying")
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="Apply scripts/neo4j_schema_v1.cypher before seeding",
    )
    args = parser.parse_args()
    asyncio.run(main_async(dry_run=args.dry_run, apply_schema=args.apply_schema))


if __name__ == "__main__":
    main()

