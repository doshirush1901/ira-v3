#!/usr/bin/env python3
"""Report potential duplicate chunks in Qdrant (same content hash across sources).

Scrolls the knowledge collection, groups points by content hash (first 500 chars),
and prints groups with more than one point (cross-file duplicates). Does not
delete; use for auditing. Optional: --max-points to limit scan.

Usage::
    poetry run python scripts/dedup_ingestion_chunks.py
    poetry run python scripts/dedup_ingestion_chunks.py --max-points 20000 --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.embeddings import EmbeddingService
from ira.brain.qdrant_manager import QdrantManager


def _content_hash(content: str, length: int = 500) -> str:
    s = (content or "").strip()[:length]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Report duplicate chunks by content hash")
    parser.add_argument("--max-points", type=int, default=None, help="Cap points scanned")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)

    hash_to_points: dict[str, list[dict]] = {}
    total = 0
    try:
        async for batch in qdrant.scroll_collection_payloads(
            batch_size=500,
            max_points=args.max_points,
        ):
            for item in batch:
                content = item.get("content", "") or ""
                if not content.strip():
                    continue
                h = _content_hash(content)
                hash_to_points.setdefault(h, []).append({
                    "point_id": item.get("point_id", ""),
                    "source": item.get("source", ""),
                    "source_category": item.get("source_category", ""),
                    "content_preview": content[:120].replace("\n", " "),
                })
                total += 1
    finally:
        await qdrant.close()

    duplicates = {h: pts for h, pts in hash_to_points.items() if len(pts) > 1}
    report = {
        "total_points_scanned": total,
        "unique_content_hashes": len(hash_to_points),
        "duplicate_groups": len(duplicates),
        "groups": [
            {"hash": h, "count": len(pts), "points": pts}
            for h, pts in sorted(duplicates.items(), key=lambda x: -len(x[1]))
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Scanned {total} points, {len(hash_to_points)} unique hashes, {len(duplicates)} duplicate groups.")
        for g in report["groups"][:20]:
            pts = g["points"]
            print(f"  Hash {g['hash']}: {g['count']} points")
            for p in pts[:3]:
                print(f"    - {p.get('source', '')} | {(p.get('content_preview') or '')[:80]}...")
            if len(pts) > 3:
                print(f"    ... and {len(pts) - 3} more")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
