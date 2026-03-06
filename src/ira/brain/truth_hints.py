"""Deterministic answer engine for known questions.

Maintains a library of pattern/keyword-matched hints that can short-circuit
the full LLM pipeline when a high-confidence match is found.  Hints are
loaded from two JSON files:

* ``data/brain/truth_hints.json`` — manually curated seed hints.
* ``data/brain/learned_truth_hints.json`` — hints auto-populated by the
  sleep trainer during dream-mode consolidation.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data/brain")
_MANUAL_PATH = _DATA_DIR / "truth_hints.json"
_LEARNED_PATH = _DATA_DIR / "learned_truth_hints.json"

_MATCH_THRESHOLD = 3
_PATTERN_WEIGHT = 5
_KEYWORD_WEIGHT = 1
_PRICING_STALENESS_DAYS = 90

_PRICING_KEYWORDS = frozenset({
    "price", "pricing", "cost", "quote", "discount", "margin",
})

_COMPLEXITY_MARKERS = re.compile(
    r"\band\s+also\b|\badditionally\b|\bcompare\b|\bvs\.?\b",
    re.IGNORECASE,
)


def _is_complex_query(query: str) -> bool:
    """Return True if *query* looks like a multi-part or comparative question."""
    if query.count("?") > 1:
        return True
    return bool(_COMPLEXITY_MARKERS.search(query))


class TruthHintsEngine:
    """Pattern/keyword matcher that returns canned answers for known questions."""

    def __init__(self, data_dir: Path | None = None) -> None:
        base = data_dir or _DATA_DIR
        self._manual_path = base / "truth_hints.json"
        self._learned_path = base / "learned_truth_hints.json"
        self._manual_hints: list[dict[str, Any]] = []
        self._learned_hints: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        self._manual_hints = self._read_file(self._manual_path)
        self._learned_hints = self._read_file(self._learned_path)
        logger.info(
            "TruthHints loaded: %d manual, %d learned",
            len(self._manual_hints),
            len(self._learned_hints),
        )

    @staticmethod
    def _read_file(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("hints", [])
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read truth hints from %s", path)
            return []

    # ── public API ────────────────────────────────────────────────────────

    def match(self, query: str) -> dict[str, Any] | None:
        """Score *query* against all hints and return the best match, or None."""
        if _is_complex_query(query):
            return None

        query_lower = query.lower()
        best: dict[str, Any] | None = None
        best_score = 0

        for hint in self._all_hints():
            if self._is_stale_pricing(hint, query_lower):
                continue

            score = self._score(hint, query, query_lower)
            if score >= _MATCH_THRESHOLD and score > best_score:
                best_score = score
                best = hint

        if best is not None:
            logger.info("TruthHint matched (score=%d): %s", best_score, best.get("answer", "")[:80])
        return best

    def is_complex_query(self, query: str) -> bool:
        """Public wrapper around the complexity detector."""
        return _is_complex_query(query)

    def add_learned_hint(
        self,
        patterns: list[str],
        keywords: list[str],
        answer: str,
    ) -> None:
        """Append a new learned hint and persist to disk."""
        hint: dict[str, Any] = {
            "patterns": patterns,
            "keywords": keywords,
            "answer": answer,
            "source": "learned",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._learned_hints.append(hint)
        self._persist_learned()
        logger.info("Learned hint added (%d total learned)", len(self._learned_hints))

    def get_stats(self) -> dict[str, int]:
        """Return counts of manual and learned hints."""
        return {
            "manual": len(self._manual_hints),
            "learned": len(self._learned_hints),
            "total": len(self._manual_hints) + len(self._learned_hints),
        }

    def reload(self) -> None:
        """Re-read both hint files from disk."""
        self._load()

    # ── internals ─────────────────────────────────────────────────────────

    def _all_hints(self) -> list[dict[str, Any]]:
        return self._manual_hints + self._learned_hints

    @staticmethod
    def _score(hint: dict[str, Any], query: str, query_lower: str) -> int:
        score = 0
        for pattern in hint.get("patterns", []):
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    score += _PATTERN_WEIGHT
            except re.error:
                continue

        for kw in hint.get("keywords", []):
            if kw.lower() in query_lower:
                score += _KEYWORD_WEIGHT

        return score

    @staticmethod
    def _is_stale_pricing(hint: dict[str, Any], query_lower: str) -> bool:
        """Skip pricing hints older than the staleness window."""
        is_pricing = any(kw in query_lower for kw in _PRICING_KEYWORDS)
        if not is_pricing:
            return False

        created = hint.get("created_at")
        if not created:
            return True
        try:
            ts = datetime.fromisoformat(created)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - ts).days
            return age_days > _PRICING_STALENESS_DAYS
        except (ValueError, TypeError):
            return True

    def _persist_learned(self) -> None:
        self._learned_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"hints": self._learned_hints}, indent=2, ensure_ascii=False)
        self._learned_path.write_text(payload, encoding="utf-8")
