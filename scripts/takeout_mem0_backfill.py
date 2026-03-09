#!/usr/bin/env python3
"""Backfill distilled takeout memories into Mem0.

This script is designed for staged Google Takeout batches that were copied to:
`data/imports/takeout_batches/<batch_name>/`.

It performs:
- deterministic memory candidate extraction from raw text snapshots
- confidence filtering
- Mem0 semantic dedupe via similarity search
- checkpointing for resumable runs
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ira.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

_SUBJECT_RE = re.compile(r"^Subject:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_FROM_RE = re.compile(r"^From:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_TO_RE = re.compile(r"^To:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

_KEYWORD_RE = re.compile(
    r"\b(quote|quotation|pricing|price|proposal|rfq|order|po\b|invoice|delivery|lead time|"
    r"machine|thermoform|vacuum form|tooling|spec|specification|payment|dispatch|customer|"
    r"client|inquiry)\b",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    text: str
    confidence: float
    kind: str


def _normalize(text: str) -> str:
    return " ".join(text.strip().split())


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _file_signature(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_candidates(text: str, max_candidates: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    def _add(raw: str, confidence: float, kind: str) -> None:
        normalized = _normalize(raw)
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(Candidate(text=normalized, confidence=confidence, kind=kind))

    for s in _SUBJECT_RE.findall(text)[: max(1, max_candidates // 4)]:
        _add(f"Email subject trend: {s}", 0.84, "subject")
    for sender in _FROM_RE.findall(text)[: max(1, max_candidates // 6)]:
        _add(f"Business correspondence sender: {sender}", 0.78, "sender")
    for recipient in _TO_RE.findall(text)[: max(1, max_candidates // 6)]:
        _add(f"Business correspondence recipient: {recipient}", 0.74, "recipient")

    for line in text.splitlines():
        if len(candidates) >= max_candidates:
            break
        cleaned = _normalize(line)
        if len(cleaned) < 30 or len(cleaned) > 260:
            continue
        if not _KEYWORD_RE.search(cleaned):
            continue
        _add(cleaned, 0.69, "keyword_line")

    return candidates[:max_candidates]


def _load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}, "stats": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed": {}, "stats": {}}


def _save_checkpoint(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def _is_duplicate(
    memory: LongTermMemory,
    user_id: str,
    candidate: str,
    threshold: float,
) -> bool:
    results = await memory.search(candidate, user_id=user_id, limit=3)
    if not results:
        return False
    return float(results[0].get("score", 0.0)) >= threshold


async def backfill(
    batch_path: Path,
    checkpoint_path: Path,
    user_id: str,
    min_confidence: float,
    dedupe_threshold: float,
    max_chars_per_file: int,
    max_candidates_per_file: int,
    max_files: int,
    dry_run: bool,
) -> dict:
    memory = LongTermMemory()
    checkpoint = _load_checkpoint(checkpoint_path)
    processed = checkpoint.setdefault("processed", {})

    txt_files = sorted(batch_path.glob("*.txt"))
    if max_files > 0:
        txt_files = txt_files[:max_files]

    summary = {
        "batch_path": str(batch_path),
        "files_seen": len(txt_files),
        "files_processed": 0,
        "files_skipped_checkpoint": 0,
        "candidates_total": 0,
        "candidates_below_confidence": 0,
        "candidates_duplicates": 0,
        "stored": 0,
        "dry_run": dry_run,
        "finished_at": "",
    }

    for path in txt_files:
        signature = _file_signature(path)
        rel_source = str(path)
        prev = processed.get(rel_source)
        if prev and prev.get("signature") == signature:
            summary["files_skipped_checkpoint"] += 1
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.exception("Failed reading %s", path)
            continue

        text = text[:max_chars_per_file]
        candidates = _extract_candidates(text, max_candidates_per_file)
        summary["candidates_total"] += len(candidates)

        per_file = {"stored": 0, "duplicates": 0, "low_conf": 0}

        for cand in candidates:
            if cand.confidence < min_confidence:
                summary["candidates_below_confidence"] += 1
                per_file["low_conf"] += 1
                continue

            duplicate = await _is_duplicate(
                memory=memory,
                user_id=user_id,
                candidate=cand.text,
                threshold=dedupe_threshold,
            )
            if duplicate:
                summary["candidates_duplicates"] += 1
                per_file["duplicates"] += 1
                continue

            if not dry_run:
                metadata = {
                    "type": "takeout_fact",
                    "source": rel_source,
                    "source_kind": cand.kind,
                    "confidence": cand.confidence,
                    "candidate_hash": _short_hash(cand.text),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                }
                stored = await memory.store(
                    cand.text,
                    user_id=user_id,
                    metadata=metadata,
                )
                if stored:
                    summary["stored"] += 1
                    per_file["stored"] += 1
            else:
                summary["stored"] += 1
                per_file["stored"] += 1

        processed[rel_source] = {
            "signature": signature,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stats": per_file,
        }
        summary["files_processed"] += 1
        _save_checkpoint(checkpoint_path, checkpoint)

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint["stats"] = summary
    _save_checkpoint(checkpoint_path, checkpoint)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill staged takeout documents into Mem0")
    parser.add_argument(
        "--batch-path",
        default="data/imports/takeout_batches/batch_001_mbox_txt",
        help="Path to staged takeout batch directory containing .txt files",
    )
    parser.add_argument(
        "--checkpoint",
        default="data/brain/takeout_mem0_backfill_batch_001.json",
        help="Checkpoint JSON path",
    )
    parser.add_argument("--user-id", default="global", help="Mem0 user_id")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.70,
        help="Minimum candidate confidence to store",
    )
    parser.add_argument(
        "--dedupe-threshold",
        type=float,
        default=0.92,
        help="Mem0 similarity threshold to treat as duplicate",
    )
    parser.add_argument(
        "--max-chars-per-file",
        type=int,
        default=250000,
        help="Max chars loaded from each file",
    )
    parser.add_argument(
        "--max-candidates-per-file",
        type=int,
        default=30,
        help="Max candidate memories extracted per file",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Max files to process (0 = all files)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and dedupe only, do not write to Mem0",
    )
    return parser.parse_args()


async def _amain() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    batch_path = Path(args.batch_path)
    if not batch_path.exists():
        raise SystemExit(f"Batch path not found: {batch_path}")

    summary = await backfill(
        batch_path=batch_path,
        checkpoint_path=Path(args.checkpoint),
        user_id=args.user_id,
        min_confidence=args.min_confidence,
        dedupe_threshold=args.dedupe_threshold,
        max_chars_per_file=args.max_chars_per_file,
        max_candidates_per_file=args.max_candidates_per_file,
        max_files=args.max_files,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
