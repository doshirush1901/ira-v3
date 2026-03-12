"""Immune system — health monitoring, error tracking, and self-healing.

Provides startup validation of all external services, continuous error-rate
monitoring, knowledge-base health auditing, and basic service recovery
actions.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient

from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings

logger = logging.getLogger(__name__)

_ERROR_THRESHOLD = 5
_ERROR_WINDOW_SECONDS = 60
_CRITICAL_SERVICES = frozenset({"qdrant", "neo4j"})


class SystemHealthError(Exception):
    """Raised when a critical service fails startup validation."""

    def __init__(self, message: str, health_report: dict) -> None:
        super().__init__(message)
        self.health_report = health_report


_SENSE_KEYS = ("qdrant", "neo4j", "postgresql", "openai", "voyage")


class ImmuneSystem:
    """Comprehensive error monitoring, health checking, and self-healing.

    When critical services fail, can degrade gracefully by setting sense_lost
    state and spiking stress (Phantom Limb) instead of raising.
    """

    def __init__(
        self,
        qdrant: QdrantManager,
        knowledge_graph: KnowledgeGraph,
        embedding_service: EmbeddingService,
    ) -> None:
        self._qdrant = qdrant
        self._graph = knowledge_graph
        self._embeddings = embedding_service
        self._sense_lost: dict[str, bool] = {k: False for k in _SENSE_KEYS}
        self._endocrine: Any = None

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._database_url = settings.database.url
        self._qdrant_url = settings.qdrant.url
        self._neo4j_uri = settings.neo4j.uri
        self._neo4j_user, self._neo4j_password = settings.neo4j.resolved_auth()

        self._langfuse_public_key = settings.langfuse.public_key
        self._langfuse_secret_key = settings.langfuse.secret_key.get_secret_value()
        self._langfuse_base_url = settings.langfuse.base_url.rstrip("/")

        self._error_tracker: dict[str, list[float]] = {}
        self._error_monitor: Any = None
        try:
            from ira.brain.error_monitor import ErrorMonitor
            self._error_monitor = ErrorMonitor()
        except ImportError:
            pass

    def set_endocrine(self, endocrine: Any) -> None:
        """Set the EndocrineSystem so stress can be spiked on sense loss."""
        self._endocrine = endocrine

    def get_sense_lost(self) -> dict[str, bool]:
        """Return which capabilities are currently severed (phantom limb state)."""
        return dict(self._sense_lost)

    def clear_sense_lost(self, service: str | None = None) -> None:
        """Clear sense_lost for a service or all (e.g. after recovery)."""
        if service is None:
            for k in self._sense_lost:
                self._sense_lost[k] = False
        elif service in self._sense_lost:
            self._sense_lost[service] = False

    # ── STARTUP VALIDATION ────────────────────────────────────────────────

    async def run_startup_validation(self) -> dict[str, dict[str, Any]]:
        """Check every external service in parallel. Raise on critical failure."""
        checks = await asyncio.gather(
            self._check_qdrant(),
            self._check_neo4j(),
            self._check_postgresql(),
            self._check_openai(),
            self._check_voyage(),
            self._check_langfuse(),
            return_exceptions=True,
        )

        names = ["qdrant", "neo4j", "postgresql", "openai", "voyage", "langfuse"]
        report: dict[str, dict[str, Any]] = {}

        for name, result in zip(names, checks, strict=False):
            if isinstance(result, Exception):
                report[name] = {
                    "status": "unhealthy",
                    "latency_ms": None,
                    "error": str(result),
                }
            else:
                report[name] = result

        unhealthy_critical = [
            name for name in _CRITICAL_SERVICES
            if report.get(name, {}).get("status") == "unhealthy"
        ]

        for name, info in report.items():
            if info["status"] == "unhealthy" and name not in _CRITICAL_SERVICES:
                logger.warning("Non-critical service %s is unhealthy: %s", name, info["error"])

        if unhealthy_critical:
            for name in unhealthy_critical:
                self._sense_lost[name] = True
            if self._endocrine is not None:
                try:
                    self._endocrine.boost("stress", 0.5)
                except Exception:
                    pass
            logger.warning(
                "Critical services unhealthy (graceful degradation): %s — sense_lost set, stress spiked",
                unhealthy_critical,
            )
            return report

        for name in _SENSE_KEYS:
            self._sense_lost[name] = report.get(name, {}).get("status") != "healthy"
        logger.info("Startup validation passed: %s", {k: v["status"] for k, v in report.items()})
        return report

    async def _check_qdrant(self) -> dict[str, Any]:
        start = time.monotonic()
        collections = await self._qdrant._client.get_collections()
        latency = (time.monotonic() - start) * 1000
        collection_names = [c.name for c in collections.collections]
        expected = self._qdrant._default_collection
        if expected not in collection_names:
            logger.warning("Qdrant collection '%s' not found (available: %s)", expected, collection_names)
        return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}

    async def _check_neo4j(self) -> dict[str, Any]:
        start = time.monotonic()
        result = await self._graph.run_cypher("RETURN 1 AS ok")
        latency = (time.monotonic() - start) * 1000
        if not result:
            return {"status": "unhealthy", "latency_ms": round(latency, 1), "error": "Empty result from RETURN 1"}
        return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}

    async def _check_postgresql(self) -> dict[str, Any]:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        start = time.monotonic()
        engine = create_async_engine(self._database_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000
            return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}
        finally:
            await engine.dispose()

    async def _check_openai(self) -> dict[str, Any]:
        if not self._openai_key:
            return {"status": "unhealthy", "latency_ms": None, "error": "No API key configured"}

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {self._openai_key}"},
            )
            resp.raise_for_status()
        latency = (time.monotonic() - start) * 1000
        return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}

    async def _check_voyage(self) -> dict[str, Any]:
        start = time.monotonic()
        await self._embeddings.embed_texts(["health check"])
        latency = (time.monotonic() - start) * 1000
        return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}

    async def _check_langfuse(self) -> dict[str, Any]:
        if not self._langfuse_public_key or not self._langfuse_secret_key:
            return {"status": "not_configured", "latency_ms": None, "error": None}

        token = base64.b64encode(
            f"{self._langfuse_public_key}:{self._langfuse_secret_key}".encode()
        ).decode()

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self._langfuse_base_url}/api/public/health",
                headers={"Authorization": f"Basic {token}"},
            )
            resp.raise_for_status()
        latency = (time.monotonic() - start) * 1000
        return {"status": "healthy", "latency_ms": round(latency, 1), "error": None}

    # ── ERROR LOGGING ─────────────────────────────────────────────────────

    def log_error(self, error: Exception, context: dict[str, Any]) -> None:
        """Log an error and track frequency for alerting."""
        service = context.get("service", "unknown")
        logger.error(
            "Service error: %s — %s",
            service,
            error,
            exc_info=error,
            extra={"service": service, "context": context},
        )

        if self._error_monitor is not None:
            severity = "CRITICAL" if service in _CRITICAL_SERVICES else "MEDIUM"
            self._error_monitor.record_error(error, context, severity=severity)

        now = time.monotonic()
        entries = self._error_tracker.setdefault(service, [])
        entries.append(now)

        cutoff = now - _ERROR_WINDOW_SECONDS
        self._error_tracker[service] = [t for t in entries if t > cutoff]

        if len(self._error_tracker[service]) >= _ERROR_THRESHOLD:
            try:
                loop = asyncio.get_running_loop()
                _alert_task = loop.create_task(self.send_alert(
                    f"Service `{service}` has {len(self._error_tracker[service])} errors in the last {_ERROR_WINDOW_SECONDS}s",
                    severity="critical",
                ))
            except RuntimeError:
                logger.warning("No running event loop — cannot send alert for %s", service)
            self._error_tracker[service] = []

    # ── ALERTING ──────────────────────────────────────────────────────────

    async def send_alert(self, message: str, severity: str = "warning") -> None:
        """Log an alert at the appropriate severity level."""
        logger.log(
            logging.CRITICAL if severity.upper() == "critical" else logging.WARNING,
            "[IRA %s] %s", severity.upper(), message,
        )

    # ── KNOWLEDGE HEALTH ──────────────────────────────────────────────────

    async def check_knowledge_health(self) -> dict[str, Any]:
        """Audit the knowledge base for size, staleness, orphans, and domain rules."""
        report: dict[str, Any] = {}

        try:
            collection_name = self._qdrant._default_collection
            info = await self._qdrant._client.get_collection(collection_name)
            report["qdrant"] = {
                "collection": collection_name,
                "point_count": info.points_count,
                "status": str(info.status),
            }
        except Exception as exc:
            report["qdrant"] = {"error": str(exc)}

        try:
            node_rows = await self._graph.run_cypher(
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
            )
            node_counts = {row["label"]: row["cnt"] for row in node_rows}
            total_nodes = sum(node_counts.values())

            orphan_rows = await self._graph.run_cypher(
                "MATCH (n) WHERE NOT (n)--() RETURN labels(n) AS labels, count(n) AS cnt"
            )
            orphaned = sum(row["cnt"] for row in orphan_rows)

            report["neo4j"] = {
                "total_nodes": total_nodes,
                "orphaned_nodes": orphaned,
                "node_counts": node_counts,
            }
        except Exception as exc:
            report["neo4j"] = {"error": str(exc)}

        try:
            from ira.brain.knowledge_health import KnowledgeHealthMonitor
            monitor = KnowledgeHealthMonitor(qdrant_manager=self._qdrant, knowledge_graph=self._graph)
            domain_report = await monitor.run_health_check()
            report["domain_health"] = domain_report
            chronic = monitor.get_chronic_issues()
            if chronic:
                report["chronic_issues"] = chronic
                await self.send_alert(
                    f"Knowledge health: {len(chronic)} chronic issue(s) detected",
                    severity="warning",
                )
        except Exception:
            logger.warning("KnowledgeHealthMonitor not available", exc_info=True)

        return report

    # ── SELF-HEALING ──────────────────────────────────────────────────────

    async def attempt_recovery(self, service_name: str) -> dict[str, Any]:
        """Try basic recovery actions for a failed service."""
        result: dict[str, Any] = {"service": service_name, "action": "", "success": False, "error": None}

        try:
            if service_name == "qdrant":
                result["action"] = "reconnect_qdrant"
                await self._qdrant._client.close()
                settings = get_settings()
                api_key = settings.qdrant.api_key.get_secret_value()
                self._qdrant._client = AsyncQdrantClient(
                    url=self._qdrant_url,
                    api_key=api_key or None,
                )
                await self._qdrant.ensure_collection()
                check = await self._check_qdrant()
                result["success"] = check["status"] == "healthy"

            elif service_name == "neo4j":
                result["action"] = "reconnect_neo4j"
                from neo4j import AsyncGraphDatabase
                await self._graph._driver.close()
                self._graph._driver = AsyncGraphDatabase.driver(
                    self._neo4j_uri,
                    auth=(self._neo4j_user, self._neo4j_password),
                )
                check = await self._check_neo4j()
                result["success"] = check["status"] == "healthy"

            elif service_name == "postgresql":
                result["action"] = "test_postgresql"
                check = await self._check_postgresql()
                result["success"] = check["status"] == "healthy"

            else:
                result["action"] = "unknown_service"
                result["error"] = f"No recovery action for '{service_name}'"

        except Exception as exc:
            result["error"] = str(exc)
            logger.exception("Recovery failed for %s", service_name)

        logger.info("Recovery attempt: %s", result)
        return result

    # ── RESPOND (bridge from heartbeat) ───────────────────────────────────

    async def respond(self, vitals: dict[str, Any]) -> None:
        """Called by RespiratorySystem when vitals are unhealthy."""
        issues: list[str] = []
        if vitals.get("memory_mb", 0) > 2048:
            issues.append(f"High memory: {vitals['memory_mb']}MB")
        if vitals.get("avg_breath_ms", 0) > 30_000:
            issues.append(f"Slow breath: {vitals['avg_breath_ms']}ms avg")

        if issues:
            message = "Unhealthy vitals detected:\n" + "\n".join(f"- {i}" for i in issues)
            logger.warning(message)
            await self.send_alert(message, severity="warning")
