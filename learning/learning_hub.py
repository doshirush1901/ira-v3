#!/usr/bin/env python3
"""
LEARNING HUB — Central Registry of Learned Patterns
====================================================

Ira's self-aware knowledge store. Every pattern has:
- A confidence score that decays over time (half-life: 30 days)
- A reinforcement counter that tracks real-world usage
- A calibrated accuracy based on prediction outcomes

Patterns that aren't reinforced fade. Patterns that make wrong
predictions lose credibility. Only battle-tested knowledge survives.

Usage:
    from openclaw.agents.ira.src.learning.learning_hub import get_learning_hub

    hub = get_learning_hub()
    hub.publish_pattern(
        pattern_type=PatternType.BEHAVIORAL,
        content="Dutch companies prefer email follow-ups over calls",
        source="episodic_consolidation",
        confidence=0.75,
    )
    hub.reinforce_pattern(pattern_id)
"""

import json
import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[6]
LEARNING_DIR = PROJECT_ROOT / "data" / "learning"
LEARNING_DIR.mkdir(parents=True, exist_ok=True)
LEARNING_DB = LEARNING_DIR / "learning_hub.db"

HALF_LIFE_DAYS = 30
ARCHIVE_THRESHOLD = 0.10
SIMILARITY_THRESHOLD = 0.55


class PatternType(str, Enum):
    BEHAVIORAL = "behavioral"
    PREFERENCE = "preference"
    TEMPORAL = "temporal"
    ENTITY = "entity"
    PROCEDURAL = "procedural"
    SALES = "sales"
    TECHNICAL = "technical"
    CORRECTION = "correction"


@dataclass
class LearnedPattern:
    pattern_id: str
    pattern_type: str
    content: str
    source: str
    confidence: float
    last_reinforced_ts: str
    reinforcement_count: int
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    archived: bool = False
    historical_accuracy: Optional[float] = None

    def effective_confidence(self) -> float:
        """Confidence blended with historical accuracy when available."""
        if self.historical_accuracy is not None and self.historical_accuracy >= 0:
            return 0.6 * self.confidence + 0.4 * self.historical_accuracy
        return self.confidence

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["effective_confidence"] = self.effective_confidence()
        return d


class LearningHub:
    """SQLite-backed registry of learned patterns with decay and reinforcement."""

    def __init__(self, db_path: Path = LEARNING_DB):
        self._db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    pattern_id        TEXT PRIMARY KEY,
                    pattern_type      TEXT NOT NULL,
                    content           TEXT NOT NULL,
                    source            TEXT NOT NULL DEFAULT '',
                    confidence        REAL NOT NULL DEFAULT 0.5,
                    last_reinforced_ts TEXT NOT NULL,
                    reinforcement_count INTEGER NOT NULL DEFAULT 1,
                    created_at        TEXT NOT NULL,
                    metadata_json     TEXT NOT NULL DEFAULT '{}',
                    archived          INTEGER NOT NULL DEFAULT 0,
                    historical_accuracy REAL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_type
                ON learned_patterns(pattern_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_archived
                ON learned_patterns(archived)
            """)

    # =========================================================================
    # PUBLISH
    # =========================================================================

    def publish_pattern(
        self,
        pattern_type: str,
        content: str,
        source: str = "",
        confidence: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LearnedPattern:
        """
        Publish a new pattern or reinforce an existing duplicate.

        If a pattern with the same type and sufficiently similar content
        already exists, we reinforce it instead of creating a duplicate.
        """
        existing = self._find_duplicate(pattern_type, content)
        if existing:
            self.reinforce_pattern(existing.pattern_id, confidence_boost=0.0)
            refreshed = self.get_pattern(existing.pattern_id)
            logger.info(
                "Reinforced existing pattern %s (count=%d)",
                existing.pattern_id,
                refreshed.reinforcement_count if refreshed else 0,
            )
            return refreshed or existing

        now = datetime.utcnow().isoformat()
        pattern_id = f"lp_{uuid.uuid4().hex[:12]}"
        meta = metadata or {}

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO learned_patterns
                    (pattern_id, pattern_type, content, source, confidence,
                     last_reinforced_ts, reinforcement_count, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    pattern_id,
                    pattern_type,
                    content,
                    source,
                    confidence,
                    now,
                    now,
                    json.dumps(meta),
                ),
            )

        pattern = LearnedPattern(
            pattern_id=pattern_id,
            pattern_type=pattern_type,
            content=content,
            source=source,
            confidence=confidence,
            last_reinforced_ts=now,
            reinforcement_count=1,
            created_at=now,
            metadata=meta,
        )
        logger.info("Published pattern %s: %.60s", pattern_id, content)
        return pattern

    def add_learning(
        self,
        content: str,
        source: str = "realtime_observer",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[LearnedPattern]:
        """
        Compatibility helper for realtime learning ingestion.

        Accepts a concise learning string (or "null"), infers a coarse pattern
        type from prefixes, and stores it through publish_pattern().
        """
        cleaned = (content or "").strip()
        if not cleaned or cleaned.lower() == "null":
            return None

        lowered = cleaned.lower()
        if lowered.startswith("correction:"):
            pattern_type = PatternType.CORRECTION.value
        elif lowered.startswith("preference:") or "prefers" in lowered:
            pattern_type = PatternType.PREFERENCE.value
        elif lowered.startswith("fact:"):
            pattern_type = PatternType.ENTITY.value
        else:
            pattern_type = PatternType.BEHAVIORAL.value

        return self.publish_pattern(
            pattern_type=pattern_type,
            content=cleaned,
            source=source,
            confidence=0.75,
            metadata=metadata or {},
        )

    # =========================================================================
    # REINFORCE
    # =========================================================================

    def reinforce_pattern(
        self,
        pattern_id: str,
        confidence_boost: float = 0.02,
    ) -> bool:
        """
        Mark a pattern as recently used.

        Updates last_reinforced_ts, increments reinforcement_count,
        and optionally nudges confidence upward (capped at 1.0).
        """
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE learned_patterns
                SET last_reinforced_ts = ?,
                    reinforcement_count = reinforcement_count + 1,
                    confidence = MIN(1.0, confidence + ?)
                WHERE pattern_id = ? AND archived = 0
                """,
                (now, confidence_boost, pattern_id),
            )
            if cur.rowcount == 0:
                logger.warning("reinforce_pattern: %s not found or archived", pattern_id)
                return False
        return True

    # =========================================================================
    # QUERY
    # =========================================================================

    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM learned_patterns WHERE pattern_id = ?",
                (pattern_id,),
            ).fetchone()
        return self._row_to_pattern(row) if row else None

    def get_active_patterns(
        self,
        pattern_type: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> List[LearnedPattern]:
        with self._conn() as conn:
            if pattern_type:
                rows = conn.execute(
                    """
                    SELECT * FROM learned_patterns
                    WHERE archived = 0 AND pattern_type = ? AND confidence >= ?
                    ORDER BY confidence DESC
                    """,
                    (pattern_type, min_confidence),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM learned_patterns
                    WHERE archived = 0 AND confidence >= ?
                    ORDER BY confidence DESC
                    """,
                    (min_confidence,),
                ).fetchall()
        return [self._row_to_pattern(r) for r in rows]

    def get_all_patterns(self, include_archived: bool = False) -> List[LearnedPattern]:
        with self._conn() as conn:
            if include_archived:
                rows = conn.execute("SELECT * FROM learned_patterns").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM learned_patterns WHERE archived = 0"
                ).fetchall()
        return [self._row_to_pattern(r) for r in rows]

    # =========================================================================
    # DECAY
    # =========================================================================

    def apply_decay(self, half_life_days: float = HALF_LIFE_DAYS) -> Dict[str, Any]:
        """
        Exponential decay on all active patterns based on time since
        last reinforcement.

        decay_factor = 0.5 ^ (days_since_reinforcement / half_life_days)

        Patterns below ARCHIVE_THRESHOLD are archived.
        Returns summary stats.
        """
        now = datetime.utcnow()
        decayed = 0
        archived = 0

        patterns = self.get_active_patterns()
        with self._conn() as conn:
            for p in patterns:
                try:
                    last_ts = datetime.fromisoformat(p.last_reinforced_ts)
                except (ValueError, TypeError):
                    last_ts = now

                days_elapsed = max(0, (now - last_ts).total_seconds() / 86400)
                decay_factor = math.pow(0.5, days_elapsed / half_life_days)
                new_confidence = p.confidence * decay_factor

                if new_confidence < ARCHIVE_THRESHOLD:
                    conn.execute(
                        "UPDATE learned_patterns SET confidence = ?, archived = 1 WHERE pattern_id = ?",
                        (new_confidence, p.pattern_id),
                    )
                    archived += 1
                else:
                    conn.execute(
                        "UPDATE learned_patterns SET confidence = ? WHERE pattern_id = ?",
                        (new_confidence, p.pattern_id),
                    )
                decayed += 1

        logger.info("Decay pass: %d patterns decayed, %d archived", decayed, archived)
        return {"decayed": decayed, "archived": archived}

    # =========================================================================
    # CALIBRATION (called after prediction reconciliation)
    # =========================================================================

    def calibrate_from_predictions(
        self,
        accuracy_by_pattern: Dict[str, float],
    ) -> int:
        """
        Update historical_accuracy for patterns based on prediction outcomes.

        accuracy_by_pattern: {pattern_id: accuracy_ratio (0.0-1.0)}
        Returns number of patterns updated.
        """
        updated = 0
        with self._conn() as conn:
            for pid, accuracy in accuracy_by_pattern.items():
                cur = conn.execute(
                    """
                    UPDATE learned_patterns
                    SET historical_accuracy = ?
                    WHERE pattern_id = ? AND archived = 0
                    """,
                    (accuracy, pid),
                )
                if cur.rowcount > 0:
                    updated += 1
        logger.info("Calibrated %d patterns from prediction accuracy", updated)
        return updated

    # =========================================================================
    # STATS
    # =========================================================================

    def stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM learned_patterns"
            ).fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM learned_patterns WHERE archived = 0"
            ).fetchone()[0]
            archived = total - active
            avg_conf = conn.execute(
                "SELECT AVG(confidence) FROM learned_patterns WHERE archived = 0"
            ).fetchone()[0] or 0.0
            by_type = {}
            for row in conn.execute(
                "SELECT pattern_type, COUNT(*) FROM learned_patterns WHERE archived = 0 GROUP BY pattern_type"
            ).fetchall():
                by_type[row[0]] = row[1]
        return {
            "total": total,
            "active": active,
            "archived": archived,
            "avg_confidence": round(avg_conf, 3),
            "by_type": by_type,
        }

    # =========================================================================
    # INTERNALS
    # =========================================================================

    def _find_duplicate(
        self, pattern_type: str, content: str
    ) -> Optional[LearnedPattern]:
        """Word-overlap similarity check against existing patterns of same type."""
        candidates = self.get_active_patterns(pattern_type=pattern_type)
        content_words = set(content.lower().split())
        if not content_words:
            return None

        for c in candidates:
            c_words = set(c.content.lower().split())
            if not c_words:
                continue
            intersection = len(content_words & c_words)
            union = len(content_words | c_words)
            jaccard = intersection / union if union else 0
            if jaccard >= SIMILARITY_THRESHOLD:
                return c
        return None

    @staticmethod
    def _row_to_pattern(row: sqlite3.Row) -> LearnedPattern:
        meta = {}
        try:
            meta = json.loads(row["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            pass
        return LearnedPattern(
            pattern_id=row["pattern_id"],
            pattern_type=row["pattern_type"],
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            last_reinforced_ts=row["last_reinforced_ts"],
            reinforcement_count=row["reinforcement_count"],
            created_at=row["created_at"],
            metadata=meta,
            archived=bool(row["archived"]),
            historical_accuracy=row["historical_accuracy"],
        )


# =============================================================================
# SINGLETON
# =============================================================================

_hub: Optional[LearningHub] = None


def get_learning_hub() -> LearningHub:
    global _hub
    if _hub is None:
        _hub = LearningHub()
    return _hub


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Learning Hub CLI")
    parser.add_argument("--stats", action="store_true", help="Show hub statistics")
    parser.add_argument("--list", action="store_true", help="List active patterns")
    parser.add_argument("--decay", action="store_true", help="Run decay pass")
    parser.add_argument("--include-archived", action="store_true")
    args = parser.parse_args()

    hub = get_learning_hub()

    if args.stats:
        s = hub.stats()
        print(json.dumps(s, indent=2))
    elif args.list:
        patterns = hub.get_all_patterns(include_archived=args.include_archived)
        for p in patterns:
            flag = " [ARCHIVED]" if p.archived else ""
            print(
                f"  [{p.confidence:.2f}] {p.pattern_type:12s} | "
                f"{p.content[:60]}... | reinforced {p.reinforcement_count}x{flag}"
            )
        print(f"\n{len(patterns)} patterns total")
    elif args.decay:
        result = hub.apply_decay()
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
