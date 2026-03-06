"""Respiratory system — operational rhythm and cadence.

Manages Ira's heartbeat (periodic health logging), inhale cycle (morning
data ingestion), exhale cycle (nightly consolidation and reporting), and
per-request breath timing.
"""

from __future__ import annotations

import asyncio
import logging
import resource
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ira.brain.document_ingestor import DocumentIngestor
from ira.config import get_settings
from ira.systems.digestive import DigestiveSystem

logger = logging.getLogger(__name__)

_MEMORY_THRESHOLD_MB = 2048
_BREATH_THRESHOLD_MS = 30_000


class RespiratorySystem:
    """Manages Ira's operational rhythm via heartbeat, inhale/exhale cycles."""

    def __init__(
        self,
        digestive: DigestiveSystem,
        ingestor: DocumentIngestor,
        *,
        dream_mode: Any | None = None,
        drip_engine: Any | None = None,
        immune_system: Any | None = None,
        email_processor: Any | None = None,
        inhale_hour: int = 6,
        inhale_minute: int = 0,
        exhale_hour: int = 22,
        exhale_minute: int = 0,
        heartbeat_interval_seconds: int = 300,
    ) -> None:
        self._digestive = digestive
        self._ingestor = ingestor
        self._dream_mode = dream_mode
        self._drip_engine = drip_engine
        self._immune_system = immune_system
        self._email_processor = email_processor

        self._inhale_hour = inhale_hour
        self._inhale_minute = inhale_minute
        self._exhale_hour = exhale_hour
        self._exhale_minute = exhale_minute
        self._heartbeat_interval = heartbeat_interval_seconds

        self._scheduler = AsyncIOScheduler()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._start_time: float = 0.0

        self._breath_durations: list[float] = []
        self._breath_lock = asyncio.Lock()

    # ── HEARTBEAT ─────────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                vitals = self._collect_vitals()
                logger.info(
                    "HEARTBEAT | %s | vitals=%s",
                    datetime.now(timezone.utc).isoformat(),
                    vitals,
                )
                if self._is_unhealthy(vitals) and self._immune_system is not None:
                    await self._immune_system.respond(vitals)
            except Exception:
                logger.exception("Heartbeat iteration failed")
            await asyncio.sleep(self._heartbeat_interval)

    def _collect_vitals(self) -> dict[str, Any]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        memory_mb = usage.ru_maxrss / (1024 * 1024)  # macOS reports bytes

        avg_breath: float = 0.0
        if self._breath_durations:
            avg_breath = sum(self._breath_durations) / len(self._breath_durations)

        return {
            "memory_mb": round(memory_mb, 1),
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "avg_breath_ms": round(avg_breath, 1),
        }

    @staticmethod
    def _is_unhealthy(vitals: dict[str, Any]) -> bool:
        if vitals.get("memory_mb", 0) > _MEMORY_THRESHOLD_MB:
            return True
        if vitals.get("avg_breath_ms", 0) > _BREATH_THRESHOLD_MS:
            return True
        return False

    # ── INHALE ────────────────────────────────────────────────────────────

    async def _inhale(self) -> None:
        logger.info("INHALE cycle starting")
        try:
            ingest_result = await self._ingestor.ingest_all()
            logger.info("INHALE documents: %s", ingest_result)
        except Exception:
            logger.exception("INHALE document ingestion failed")

        if self._email_processor is not None:
            try:
                await self._email_processor.fetch_and_process()
                logger.info("INHALE email processing complete")
            except Exception:
                logger.exception("INHALE email processing failed")
        else:
            logger.debug("INHALE skipping email processing (no EmailProcessor)")

    # ── EXHALE ────────────────────────────────────────────────────────────

    async def _exhale(self) -> None:
        logger.info("EXHALE cycle starting")
        summary_parts: list[str] = []

        if self._dream_mode is not None:
            try:
                dream_report = await self._dream_mode.run_dream_cycle()
                summary_parts.append(f"Dream cycle: {dream_report}")
            except Exception:
                logger.exception("EXHALE dream cycle failed")
        else:
            logger.debug("EXHALE skipping dream mode (not configured)")

        if self._drip_engine is not None:
            try:
                drip_result = await self._drip_engine.evaluate_campaigns()
                summary_parts.append(f"Drip evaluation: {drip_result}")
            except Exception:
                logger.exception("EXHALE drip evaluation failed")
        else:
            logger.debug("EXHALE skipping drip engine (not configured)")

        summary = "Ira Daily Exhale Report\n" + "\n".join(summary_parts) if summary_parts else "Ira Daily Exhale: no active subsystems"
        await self._send_telegram_summary(summary)

    async def _send_telegram_summary(self, summary: str) -> None:
        settings = get_settings()
        token = settings.telegram.bot_token.get_secret_value()
        chat_id = settings.telegram.admin_chat_id

        if not token or not chat_id:
            logger.debug("Telegram not configured — skipping daily summary")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": summary[:4096],
            "parse_mode": "Markdown",
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception:
            logger.exception("Failed to send Telegram daily summary")

    # ── BREATH TIMING ─────────────────────────────────────────────────────

    @asynccontextmanager
    async def breath(self) -> AsyncIterator[None]:
        """Context manager that measures per-request processing time."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            async with self._breath_lock:
                self._breath_durations.append(elapsed_ms)
                if len(self._breath_durations) > 1000:
                    self._breath_durations = self._breath_durations[-500:]
            logger.debug("BREATH duration=%.1fms", elapsed_ms)

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the heartbeat task and scheduled inhale/exhale cycles."""
        self._start_time = time.monotonic()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        self._scheduler.add_job(
            self._inhale,
            CronTrigger(hour=self._inhale_hour, minute=self._inhale_minute),
            id="inhale",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._exhale,
            CronTrigger(hour=self._exhale_hour, minute=self._exhale_minute),
            id="exhale",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("RespiratorySystem started")

    async def stop(self) -> None:
        """Cancel the heartbeat and shut down the scheduler."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

        logger.info("RespiratorySystem stopped")
