"""Ingestion log — tracks which files have been ingested into Qdrant.

Alexandros owns this log.  It records per-file ingestion metadata (hash,
chunks created, nutrient counts, entities found, pipeline version) so that
the gatekeeper can detect new, changed, or legacy-ingested files.

The log uses the same ``name+size+mtime`` fingerprint as the imports
metadata index, enabling direct comparison.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_PATH = _PROJECT_ROOT / "data" / "brain" / "ingestion_log.json"

CURRENT_PIPELINE = "digestive_v2"


def _empty_log() -> dict[str, Any]:
    return {"files": {}, "last_full_scan": None, "total_ingested": 0, "version": 1}


def load_log() -> dict[str, Any]:
    if not LOG_PATH.exists():
        return _empty_log()
    try:
        return json.loads(LOG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupted ingestion log, starting fresh")
        return _empty_log()


def save_log(log: dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2, default=str))


def file_fingerprint(filepath: Path) -> str:
    """Same fingerprint as imports_metadata_index: md5(name:size:mtime)[:12]."""
    stat = filepath.stat()
    key = f"{filepath.name}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def record_ingestion(
    log: dict[str, Any],
    rel_path: str,
    file_hash: str,
    result: dict[str, Any],
    collection: str,
) -> None:
    """Record a successful ingestion in the log."""
    nutrients = result.get("nutrients_extracted", {})
    log["files"][rel_path] = {
        "hash": file_hash,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "chunks_created": result.get("chunks_created", 0),
        "protein_items": nutrients.get("protein", 0),
        "carbs_items": nutrients.get("carbs", 0),
        "waste_discarded": nutrients.get("waste", 0),
        "entities": result.get("entities_found", {}),
        "collection": collection,
        "pipeline": CURRENT_PIPELINE,
    }
    log["total_ingested"] = len(log["files"])


def needs_ingestion(
    log: dict[str, Any],
    rel_path: str,
    current_hash: str,
    *,
    force: bool = False,
) -> str:
    """Return the reason a file needs ingestion, or empty string if up-to-date.

    Reasons: "new", "changed", "legacy_pipeline", "forced", or "".
    """
    if force:
        return "forced"

    entry = log["files"].get(rel_path)
    if entry is None:
        return "new"
    if entry.get("hash") != current_hash:
        return "changed"
    if entry.get("pipeline") != CURRENT_PIPELINE:
        return "legacy_pipeline"
    return ""
