"""Rich error tracking with context and self-healing suggestions.

:class:`ErrorMonitor` records exceptions with full context (traceback,
severity, surrounding state), rate-limits Telegram alerts, and identifies
errors that might be auto-fixable (connection timeouts, stale caches, etc.).
"""

from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_ERRORS = 1000
_ALERTS_PER_HOUR = 3

_SELF_HEALING_PATTERNS: dict[str, str] = {
    "ConnectionTimeout": "retry_with_backoff",
    "ConnectionRefused": "check_service_health",
    "StaleCache": "clear_and_rebuild_cache",
    "RateLimitExceeded": "exponential_backoff",
    "JSONDecodeError": "retry_with_fallback_parser",
    "QdrantException": "reconnect_qdrant",
    "Neo4jError": "reconnect_neo4j",
}

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


class ErrorMonitor:
    """In-memory error tracker with Telegram alerting and self-healing hints."""

    def __init__(
        self,
        telegram_token: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> None:
        self._telegram_token = telegram_token
        self._telegram_chat_id = telegram_chat_id
        self._errors: list[dict[str, Any]] = []
        self._alert_counts: dict[str, list[datetime]] = defaultdict(list)

    # ── recording ─────────────────────────────────────────────────────────

    def record_error(
        self,
        error: Exception,
        context: dict[str, Any],
        severity: str = "MEDIUM",
    ) -> None:
        """Store an error with timestamp, traceback, and context.

        Uses a ring buffer capped at ``_MAX_ERRORS`` entries.
        """
        severity = severity.upper() if severity.upper() in _SEVERITY_ORDER else "MEDIUM"

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exception(type(error), error, error.__traceback__),
            "severity": severity,
            "context": context,
        }

        if len(self._errors) >= _MAX_ERRORS:
            self._errors.pop(0)
        self._errors.append(entry)

        logger.log(
            logging.CRITICAL if severity == "CRITICAL" else logging.ERROR,
            "[%s] %s: %s",
            severity,
            type(error).__name__,
            error,
        )

    # ── alerting ──────────────────────────────────────────────────────────

    def should_alert(self, error_type: str) -> bool:
        """Rate limiting: max ``_ALERTS_PER_HOUR`` alerts per error type per hour."""
        now = datetime.now(timezone.utc)
        recent = [
            ts for ts in self._alert_counts[error_type]
            if (now - ts).total_seconds() < 3600
        ]
        self._alert_counts[error_type] = recent
        return len(recent) < _ALERTS_PER_HOUR

    async def send_alert(self, message: str) -> None:
        """Send a Telegram notification for CRITICAL/HIGH errors."""
        if not self._telegram_token or not self._telegram_chat_id:
            logger.debug("Telegram alerting not configured; skipping alert")
            return

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        payload = {
            "chat_id": self._telegram_chat_id,
            "text": message[:4096],
            "parse_mode": "HTML",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("Alert sent to Telegram")
        except httpx.HTTPError:
            logger.exception("Failed to send Telegram alert")

    async def record_and_alert(
        self,
        error: Exception,
        context: dict[str, Any],
        severity: str = "MEDIUM",
    ) -> None:
        """Record an error and send a Telegram alert if severity warrants it."""
        self.record_error(error, context, severity)

        if severity.upper() in ("CRITICAL", "HIGH"):
            error_type = type(error).__name__
            if self.should_alert(error_type):
                self._alert_counts[error_type].append(datetime.now(timezone.utc))
                msg = (
                    f"<b>[{severity.upper()}]</b> {error_type}\n"
                    f"{str(error)[:500]}\n"
                    f"Context: {str(context)[:200]}"
                )
                await self.send_alert(msg)

    # ── summaries ─────────────────────────────────────────────────────────

    def get_error_summary(self, hours: int = 24) -> dict:
        """Aggregate errors by type and severity over the last *hours*."""
        now = datetime.now(timezone.utc)
        by_type: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        total = 0

        for entry in self._errors:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, KeyError):
                continue

            if (now - ts).total_seconds() > hours * 3600:
                continue

            total += 1
            by_type[entry.get("error_type", "Unknown")] += 1
            by_severity[entry.get("severity", "MEDIUM")] += 1

        return {
            "total": total,
            "hours": hours,
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
        }

    def get_self_healing_candidates(self) -> list[dict]:
        """Return recent errors that might be auto-fixable."""
        candidates: list[dict] = []
        seen_types: set[str] = set()

        for entry in reversed(self._errors):
            error_type = entry.get("error_type", "")
            if error_type in seen_types:
                continue

            for pattern, action in _SELF_HEALING_PATTERNS.items():
                if pattern.lower() in error_type.lower() or pattern.lower() in entry.get("message", "").lower():
                    candidates.append({
                        "error_type": error_type,
                        "message": entry.get("message", ""),
                        "suggested_action": action,
                        "last_seen": entry.get("timestamp", ""),
                        "severity": entry.get("severity", "MEDIUM"),
                    })
                    seen_types.add(error_type)
                    break

        return candidates
