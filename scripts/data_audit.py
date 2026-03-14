#!/usr/bin/env python3
"""One-off audit: where is data stored and what do we have (including takeout)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings


async def main() -> None:
    settings = get_settings()
    report = {
        "qdrant": {"url": settings.qdrant.url, "collection": settings.qdrant.collection},
        "neo4j": {"uri": settings.neo4j.uri.split("@")[-1] if "@" in settings.neo4j.uri else settings.neo4j.uri},
        "postgres": {"url": settings.database.url.split("@")[-1] if "@" in settings.database.url else "configured"},
        "mem0": {"configured": bool(settings.memory.api_key.get_secret_value())},
        "takeout_checkpoint": None,
        "local_files": {},
    }

    # Qdrant
    try:
        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        await qdrant.ensure_collection()
        col_name = settings.qdrant.collection
        info = await qdrant._client.get_collection(col_name)
        report["qdrant"]["points_count"] = info.points_count
        report["qdrant"]["status"] = str(info.status)
        takeout_count = await qdrant.count_by_source_category("takeout_email_protein")
        report["qdrant"]["takeout_email_protein_points"] = takeout_count
        await qdrant.close()
    except Exception as e:
        report["qdrant"]["error"] = str(e)

    # Neo4j
    try:
        graph = KnowledgeGraph()
        rows = await graph.run_cypher(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"
        )
        report["neo4j"]["node_counts"] = {r["label"]: r["cnt"] for r in rows}
        report["neo4j"]["total_nodes"] = sum(r["cnt"] for r in rows)
        await graph.close()
    except Exception as e:
        report["neo4j"]["error"] = str(e)

    # Postgres (CRM, quotes, vendors)
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(settings.database.url)
        async with engine.connect() as conn:
            for table in ("contacts", "companies", "deals", "interactions", "quotes", "vendors", "vendor_payables"):
                try:
                    r = await conn.execute(text(f"SELECT count(*) FROM {table}"))
                    report.setdefault("postgres_counts", {})[table] = r.scalar()
                except Exception:
                    report.setdefault("postgres_counts", {})[table] = None
        await engine.dispose()
    except Exception as e:
        report["postgres_error"] = str(e)

    # Takeout checkpoint (local file)
    checkpoint_path = Path("data/brain/takeout_ingest_batch-takeout.json")
    if checkpoint_path.exists():
        data = json.loads(checkpoint_path.read_text())
        report["takeout_checkpoint"] = data.get("stats", {})

    # Local file sizes
    for name, p in [
        ("qdrant_storage", Path("data/qdrant")),
        ("neo4j_storage", Path("data/neo4j")),
        ("postgres_storage", Path("data/postgres")),
        ("mem0_storage_dir", Path("data/mem0_storage")),
        ("ingestion_log", Path("data/brain/ingestion_log.json")),
    ]:
        if p.exists():
            if p.is_dir():
                report["local_files"][name] = f"{sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / (1024*1024):.1f} MB"
            else:
                report["local_files"][name] = f"{p.stat().st_size / 1024:.1f} KB"

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
