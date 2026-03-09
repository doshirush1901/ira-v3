"""Backfill Neo4j relationships from already-ingested documents.

Re-reads each previously ingested file, runs LLM entity extraction,
and writes only the relationships (nodes already exist from the
original ingestion).

Usage:
    python scripts/backfill_relationships.py
    python scripts/backfill_relationships.py --dry-run
    python scripts/backfill_relationships.py --limit 50
    python scripts/backfill_relationships.py --base-path data/imports
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.document_ingestor import _READERS, _LEDGER_PATH  # noqa: E402
from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


def get_ingested_files(ledger_path: Path) -> list[dict[str, str]]:
    """Read all file paths from the ingestion ledger."""
    if not ledger_path.exists():
        logger.error("Ingestion ledger not found: %s", ledger_path)
        return []
    conn = sqlite3.connect(str(ledger_path))
    rows = conn.execute("SELECT path, hash FROM ingested_files").fetchall()
    conn.close()
    return [{"path": r[0], "hash": r[1]} for r in rows]


def read_file(path: Path) -> str | None:
    """Read a file using the appropriate reader, or None on failure."""
    ext = path.suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        return None
    try:
        return reader(path)
    except Exception:
        logger.warning("Failed to read %s", path, exc_info=True)
        return None


async def backfill(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    base_path: str = "data/imports",
) -> None:
    files = get_ingested_files(_LEDGER_PATH)
    if not files:
        logger.info("No ingested files found in ledger")
        return

    base = Path(base_path).resolve()
    files = [
        f for f in files
        if Path(f["path"]).resolve().is_relative_to(base)
    ]
    if not files:
        logger.info("No ingested files found under base path: %s", base_path)
        return

    if limit:
        files = files[:limit]

    logger.info("Backfilling relationships for %d files (dry_run=%s)", len(files), dry_run)

    graph = KnowledgeGraph()
    total_rels = 0
    files_processed = 0
    files_skipped = 0
    errors = 0

    try:
        for i, entry in enumerate(files):
            file_path = Path(entry["path"])
            if not file_path.exists():
                logger.debug("File no longer exists: %s", file_path)
                files_skipped += 1
                continue

            text = read_file(file_path)
            if not text or not text.strip():
                files_skipped += 1
                continue

            try:
                extracted = await graph.extract_entities_from_text(text)
            except Exception:
                logger.warning("Extraction failed for %s", file_path, exc_info=True)
                errors += 1
                continue

            relationships = extracted.get("relationships", [])
            if not relationships:
                files_processed += 1
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] %s: would create %d relationships",
                    file_path.name, len(relationships),
                )
                for rel in relationships:
                    logger.info(
                        "  (%s:%s)-[%s]->(%s:%s)",
                        rel.get("from_type"), rel.get("from_key"),
                        rel.get("rel"),
                        rel.get("to_type"), rel.get("to_key"),
                    )
                total_rels += len(relationships)
                files_processed += 1
                continue

            file_rels = 0
            for rel in relationships:
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
                        file_rels += 1
                except Exception:
                    logger.debug("Relationship write failed: %s", rel, exc_info=True)

            total_rels += file_rels
            files_processed += 1

            if (i + 1) % 10 == 0 or i == len(files) - 1:
                logger.info(
                    "Progress: %d/%d files | %d relationships created | %d errors",
                    i + 1, len(files), total_rels, errors,
                )
    finally:
        await graph.close()

    action = "would create" if dry_run else "created"
    logger.info(
        "Backfill complete: %d files processed, %d skipped, %d errors, %d relationships %s",
        files_processed, files_skipped, errors, total_rels, action,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Neo4j relationships from ingested documents")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Neo4j")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N files")
    parser.add_argument("--base-path", default="data/imports", help="Base path for imports directory")
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run, limit=args.limit, base_path=args.base_path))


if __name__ == "__main__":
    main()
