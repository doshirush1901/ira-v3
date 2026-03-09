#!/usr/bin/env python3
"""
PREDICTION LOG — Track Verifiable Predictions and Reconcile Outcomes
=====================================================================

Every time the Reasoner or an observer makes a concrete, verifiable
prediction ("This deal will close this week", "This customer will churn"),
it gets logged here with actual_outcome = NULL.

During nap, the outcome reconciliation phase checks CRM events (deals
won/lost, customer replies) and fills in actual_outcome + was_correct.

The aggregated accuracy per pattern_id feeds back into the LearningHub's
confidence calibration loop.

Usage:
    from openclaw.agents.ira.src.learning.prediction_log import get_prediction_log

    log = get_prediction_log()
    log.record_prediction(
        pattern_id="lp_abc123",
        predicted_outcome="Deal with Acme will close this week",
        context={"deal_id": "d_001", "customer": "Acme"},
    )

    # During nap:
    log.record_outcome("pred_xyz", actual_outcome="Deal closed", was_correct=True)
    accuracy = log.accuracy_by_pattern()
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[6]
LEARNING_DIR = PROJECT_ROOT / "data" / "learning"
LEARNING_DIR.mkdir(parents=True, exist_ok=True)
PREDICTIONS_DB = LEARNING_DIR / "predictions.db"


@dataclass
class Prediction:
    prediction_id: str
    timestamp: str
    pattern_id: str
    predicted_outcome: str
    actual_outcome: Optional[str]
    was_correct: Optional[bool]
    context_json: str = "{}"
    reconciled_at: Optional[str] = None

    @property
    def context(self) -> Dict[str, Any]:
        try:
            return json.loads(self.context_json)
        except (json.JSONDecodeError, TypeError):
            return {}


class PredictionLog:
    """SQLite-backed log of verifiable predictions and their outcomes."""

    def __init__(self, db_path: Path = PREDICTIONS_DB):
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
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id    TEXT PRIMARY KEY,
                    timestamp        TEXT NOT NULL,
                    pattern_id       TEXT NOT NULL,
                    predicted_outcome TEXT NOT NULL,
                    actual_outcome   TEXT,
                    was_correct      INTEGER,
                    context_json     TEXT NOT NULL DEFAULT '{}',
                    reconciled_at    TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pred_pattern
                ON predictions(pattern_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pred_unreconciled
                ON predictions(was_correct) WHERE was_correct IS NULL
            """)

    # =========================================================================
    # RECORD
    # =========================================================================

    def record_prediction(
        self,
        pattern_id: str,
        predicted_outcome: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Log a new verifiable prediction.
        Returns the prediction_id.
        """
        pred_id = f"pred_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        ctx = json.dumps(context or {})

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO predictions
                    (prediction_id, timestamp, pattern_id, predicted_outcome, context_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pred_id, now, pattern_id, predicted_outcome, ctx),
            )

        logger.info(
            "Prediction logged: %s (pattern=%s) — %s",
            pred_id, pattern_id, predicted_outcome[:60],
        )
        return pred_id

    def record_outcome(
        self,
        prediction_id: str,
        actual_outcome: str,
        was_correct: bool,
    ) -> bool:
        """Fill in the actual outcome for a previously logged prediction."""
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE predictions
                SET actual_outcome = ?,
                    was_correct = ?,
                    reconciled_at = ?
                WHERE prediction_id = ? AND was_correct IS NULL
                """,
                (actual_outcome, int(was_correct), now, prediction_id),
            )
            if cur.rowcount == 0:
                logger.warning("record_outcome: %s not found or already reconciled", prediction_id)
                return False
        return True

    # =========================================================================
    # QUERY
    # =========================================================================

    def get_unreconciled(self, max_age_days: int = 30) -> List[Prediction]:
        """Get predictions that haven't been reconciled yet."""
        cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM predictions
                WHERE was_correct IS NULL AND timestamp >= ?
                ORDER BY timestamp DESC
                """,
                (cutoff,),
            ).fetchall()
        return [self._row_to_prediction(r) for r in rows]

    def get_by_pattern(self, pattern_id: str) -> List[Prediction]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM predictions WHERE pattern_id = ? ORDER BY timestamp DESC",
                (pattern_id,),
            ).fetchall()
        return [self._row_to_prediction(r) for r in rows]

    def get_recent(self, limit: int = 50) -> List[Prediction]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM predictions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_prediction(r) for r in rows]

    # =========================================================================
    # ACCURACY
    # =========================================================================

    def accuracy_by_pattern(self, min_predictions: int = 3) -> Dict[str, float]:
        """
        Compute accuracy ratio per pattern_id.

        Only includes patterns with at least min_predictions reconciled outcomes.
        Returns {pattern_id: accuracy_ratio (0.0 - 1.0)}.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT pattern_id,
                       COUNT(*) as total,
                       SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
                FROM predictions
                WHERE was_correct IS NOT NULL
                GROUP BY pattern_id
                HAVING total >= ?
                """,
                (min_predictions,),
            ).fetchall()

        result = {}
        for row in rows:
            total = row["total"]
            correct = row["correct"]
            result[row["pattern_id"]] = correct / total if total > 0 else 0.0
        return result

    def overall_accuracy(self) -> Dict[str, Any]:
        """Aggregate accuracy stats across all predictions."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct,
                       SUM(CASE WHEN was_correct = 0 THEN 1 ELSE 0 END) as incorrect,
                       SUM(CASE WHEN was_correct IS NULL THEN 1 ELSE 0 END) as pending
                FROM predictions
                """
            ).fetchone()

        total = row["total"]
        correct = row["correct"] or 0
        incorrect = row["incorrect"] or 0
        reconciled = correct + incorrect
        return {
            "total_predictions": total,
            "reconciled": reconciled,
            "pending": row["pending"] or 0,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": correct / reconciled if reconciled > 0 else None,
        }

    # =========================================================================
    # CLEANUP
    # =========================================================================

    def purge_old(self, days: int = 180) -> int:
        """Remove reconciled predictions older than N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM predictions WHERE was_correct IS NOT NULL AND timestamp < ?",
                (cutoff,),
            )
            return cur.rowcount

    # =========================================================================
    # INTERNALS
    # =========================================================================

    @staticmethod
    def _row_to_prediction(row: sqlite3.Row) -> Prediction:
        was_correct = row["was_correct"]
        if was_correct is not None:
            was_correct = bool(was_correct)
        return Prediction(
            prediction_id=row["prediction_id"],
            timestamp=row["timestamp"],
            pattern_id=row["pattern_id"],
            predicted_outcome=row["predicted_outcome"],
            actual_outcome=row["actual_outcome"],
            was_correct=was_correct,
            context_json=row["context_json"],
            reconciled_at=row["reconciled_at"],
        )


# =============================================================================
# SINGLETON
# =============================================================================

_log: Optional[PredictionLog] = None


def get_prediction_log() -> PredictionLog:
    global _log
    if _log is None:
        _log = PredictionLog()
    return _log


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prediction Log CLI")
    parser.add_argument("--stats", action="store_true", help="Overall accuracy stats")
    parser.add_argument("--unreconciled", action="store_true", help="Show pending predictions")
    parser.add_argument("--accuracy", action="store_true", help="Accuracy by pattern")
    parser.add_argument("--recent", type=int, default=0, help="Show N recent predictions")
    args = parser.parse_args()

    pl = get_prediction_log()

    if args.stats:
        print(json.dumps(pl.overall_accuracy(), indent=2))
    elif args.unreconciled:
        for p in pl.get_unreconciled():
            print(f"  [{p.prediction_id}] pattern={p.pattern_id} — {p.predicted_outcome[:60]}")
    elif args.accuracy:
        acc = pl.accuracy_by_pattern()
        for pid, ratio in sorted(acc.items(), key=lambda x: x[1]):
            print(f"  {pid}: {ratio:.0%}")
    elif args.recent > 0:
        for p in pl.get_recent(args.recent):
            status = "?" if p.was_correct is None else ("Y" if p.was_correct else "N")
            print(f"  [{status}] {p.pattern_id} — {p.predicted_outcome[:60]}")
    else:
        parser.print_help()
