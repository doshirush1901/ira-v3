"""Ingestion gatekeeper — Alexandros's brain for deciding what to ingest.

Compares the imports metadata index against the ingestion log to find
files that are new, changed, or were ingested by an older pipeline.
Processes them through the DigestiveSystem and updates the log.

Supports parallel processing: multiple files are digested concurrently
(each file's GPT calls run independently), giving near-linear speedup
since all work is I/O-bound (API calls to OpenAI / Qdrant / Neo4j).

  Concurrency 1 (serial):   ~45s/file  — 712 files = ~9 hours
  Concurrency 5 (default):  ~9s/file   — 712 files = ~1.8 hours
  Concurrency 10:           ~5s/file   — 712 files = ~1 hour

Can be called from the CLI (``ira ingest``), the respiratory system's
inhale cycle, or directly by the Alexandros agent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.brain.imports_metadata_index import load_index
from ira.brain.ingestion_log import (
    CURRENT_PIPELINE,
    file_fingerprint,
    load_log,
    needs_ingestion,
    record_ingestion,
    save_log,
)

from ira.exceptions import IngestionError, IraError

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 5


async def scan_for_undigested(*, force: bool = False) -> list[dict[str, Any]]:
    """Compare the metadata index against the ingestion log.

    Returns a list of file dicts needing ingestion, each with keys
    ``rel_path``, ``path``, ``hash``, ``reason``, ``category``,
    ``extension``, ``name``.
    """
    index = await load_index()
    log = await load_log()
    queue: list[dict[str, Any]] = []

    for rel_path, meta in index.get("files", {}).items():
        filepath = Path(meta.get("path", ""))
        if not filepath.exists():
            continue

        current_hash = meta.get("hash", "")
        if not current_hash:
            try:
                current_hash = file_fingerprint(filepath)
            except OSError:
                continue

        reason = needs_ingestion(log, rel_path, current_hash, force=force)
        if reason:
            queue.append({
                "rel_path": rel_path,
                "path": str(filepath),
                "hash": current_hash,
                "reason": reason,
                "category": meta.get("doc_type", "other"),
                "extension": meta.get("extension", filepath.suffix.lower()),
                "name": meta.get("name", filepath.name),
                "size_kb": meta.get("size_kb", 0),
            })

    queue.sort(key=lambda f: (
        0 if f["reason"] == "new" else
        1 if f["reason"] == "changed" else
        2 if f["reason"] == "forced" else 3,
        f["size_kb"],  # smaller files first within each reason group
    ))

    logger.info(
        "Gatekeeper scan: %d files need ingestion (%s)",
        len(queue),
        ", ".join(
            f'{r}: {sum(1 for f in queue if f["reason"] == r)}'
            for r in sorted({f["reason"] for f in queue})
        ) if queue else "none",
    )
    return queue


ProgressCallback = Any  # Callable[[int, int, str, dict], None]


async def run_ingestion_cycle(
    *,
    force: bool = False,
    batch_size: int = 712,
    concurrency: int = DEFAULT_CONCURRENCY,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run a gated ingestion cycle through the DigestiveSystem.

    Processes up to *batch_size* files with *concurrency* files in
    parallel.  The log is updated as each file completes.

    *progress_callback(done, total, filename, file_result)* is called
    after each file finishes so the CLI can update a progress bar.
    """
    from ira.brain.document_ingestor import DocumentIngestor, _READERS
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.config import get_settings
    from ira.systems.digestive import DigestiveSystem

    queue = await scan_for_undigested(force=force)
    if not queue:
        logger.info("Gatekeeper: nothing to ingest")
        return {"files_processed": 0, "files_skipped": 0, "reason": "up_to_date"}

    batch = queue[:batch_size]
    batch_total = len(batch)
    logger.info(
        "Gatekeeper: ingesting %d / %d files (concurrency=%d)",
        batch_total, len(queue), concurrency,
    )

    # Shared services — thread-safe for concurrent use
    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    await qdrant.ensure_collection()
    graph = KnowledgeGraph()
    ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)
    digestive = DigestiveSystem(
        ingestor=ingestor,
        knowledge_graph=graph,
        embedding_service=embedding,
        qdrant=qdrant,
    )

    settings = get_settings()
    collection = settings.qdrant.collection
    log = await load_log()

    # Shared counters protected by a lock (concurrent writes from parallel tasks)
    lock = asyncio.Lock()
    processed = 0
    skipped = 0
    failed = 0
    total_chunks = 0
    total_entities: dict[str, int] = {"companies": 0, "people": 0, "machines": 0}
    errors: list[str] = []
    done_count = 0

    async def _process_one(file_info: dict[str, Any]) -> None:
        nonlocal processed, skipped, failed, total_chunks, done_count

        rel_path = file_info["rel_path"]
        filepath = Path(file_info["path"])

        try:
            reader = _READERS.get(file_info["extension"])
            if reader is None:
                async with lock:
                    skipped += 1
                    done_count += 1
                    if progress_callback is not None:
                        progress_callback(done_count, batch_total, file_info["name"], {})
                return

            text = reader(filepath)
            if not text or not text.strip():
                async with lock:
                    skipped += 1
                    done_count += 1
                    if progress_callback is not None:
                        progress_callback(done_count, batch_total, file_info["name"], {})
                return

            result = await digestive.ingest(
                raw_data=text,
                source=str(filepath),
                source_category=file_info["category"],
            )

            chunks = result.get("chunks_created", 0)
            async with lock:
                done_count += 1
                if chunks > 0:
                    record_ingestion(log, rel_path, file_info["hash"], result, collection)
                    await save_log(log)
                    processed += 1
                    total_chunks += chunks
                    for k in total_entities:
                        total_entities[k] += result.get("entities_found", {}).get(k, 0)
                else:
                    skipped += 1
                if progress_callback is not None:
                    progress_callback(done_count, batch_total, file_info["name"], result)

        except (IngestionError, Exception) as exc:
            logger.exception("Gatekeeper: failed to ingest %s", rel_path)
            async with lock:
                errors.append(f"{rel_path}: {exc}")
                failed += 1
                done_count += 1
                if progress_callback is not None:
                    progress_callback(done_count, batch_total, file_info["name"], {})

    # Run with bounded concurrency using a semaphore
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(file_info: dict[str, Any]) -> None:
        async with sem:
            await _process_one(file_info)

    try:
        await asyncio.gather(*[_guarded(f) for f in batch])

        log["last_full_scan"] = datetime.now(timezone.utc).isoformat()
        await save_log(log)
    finally:
        for closeable in [qdrant, graph]:
            try:
                await closeable.close()
            except (IraError, Exception):
                logger.debug("Failed to close %s", type(closeable).__name__, exc_info=True)
        try:
            ingestor.close()
        except (IraError, Exception):
            logger.debug("Failed to close ingestor", exc_info=True)

    summary = {
        "files_processed": processed,
        "files_skipped": skipped,
        "files_failed": failed,
        "files_remaining": len(queue) - batch_total,
        "total_chunks": total_chunks,
        "total_entities": total_entities,
        "errors": errors,
        "pipeline": CURRENT_PIPELINE,
        "batch_size": batch_total,
        "total_queued": len(queue),
        "concurrency": concurrency,
    }
    logger.info("Gatekeeper ingestion cycle complete: %s", summary)
    return summary
