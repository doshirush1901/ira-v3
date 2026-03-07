"""Autonomous drip engine — automated multi-step email campaigns.

Evaluates active drip campaigns, sends pending steps via Gmail, and
checks for replies.  Integrated into the :class:`RespiratorySystem`
exhale cycle for nightly execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ira.exceptions import DatabaseError, IraError

logger = logging.getLogger(__name__)


class AutonomousDripEngine:
    """Manages automated drip email campaigns."""

    def __init__(
        self,
        crm: Any,
        quotes: Any | None = None,
        message_bus: Any | None = None,
        gmail: Any | None = None,
    ) -> None:
        self._crm = crm
        self._quotes = quotes
        self._bus = message_bus
        self._gmail = gmail

    async def evaluate_campaigns(self) -> dict[str, Any]:
        """Check active campaigns and evaluate performance metrics."""
        try:
            campaigns = await self._crm.list_campaigns()
        except (DatabaseError, Exception):
            logger.exception("Failed to list campaigns")
            return {"campaigns": 0, "active": 0, "error": "CRM query failed"}

        active = [c for c in campaigns if getattr(c, "status", None) in ("ACTIVE", "active")]

        stats: list[dict[str, Any]] = []
        for campaign in active:
            try:
                steps = await self._crm.list_drip_steps(
                    filters={"campaign_id": str(campaign.id)},
                )
                sent = sum(1 for s in steps if s.sent_at)
                replied = sum(1 for s in steps if s.reply_received)
                reply_rate = replied / sent if sent > 0 else 0.0

                stats.append({
                    "campaign": campaign.name,
                    "total_steps": len(steps),
                    "sent": sent,
                    "replied": replied,
                    "reply_rate": round(reply_rate, 3),
                })
            except (DatabaseError, Exception):
                logger.exception("Failed to evaluate campaign %s", campaign.name)

        return {"campaigns": len(campaigns), "active": len(active), "stats": stats}

    async def send_pending_steps(self) -> dict[str, Any]:
        """Send drip steps that are due."""
        sent_count = 0
        errors: list[str] = []

        try:
            campaigns = await self._crm.list_campaigns()
        except (DatabaseError, Exception):
            return {"sent": 0, "errors": ["CRM query failed"]}

        active = [c for c in campaigns if getattr(c, "status", None) in ("ACTIVE", "active")]

        for campaign in active:
            try:
                steps = await self._crm.list_drip_steps(
                    filters={"campaign_id": str(campaign.id)},
                )
                pending = [s for s in steps if s.sent_at is None]

                for step in pending:
                    if self._gmail is not None:
                        try:
                            await self._gmail.send_draft(
                                to=str(step.lead_id),
                                subject=step.email_subject,
                                body=step.email_body,
                            )
                            step.sent_at = datetime.now(timezone.utc)
                            sent_count += 1
                        except (IraError, Exception) as exc:
                            errors.append(f"Send failed for step {step.step_number}: {exc}")
                    else:
                        logger.debug("Gmail sender not configured — skipping step %d", step.step_number)
            except (DatabaseError, Exception):
                logger.exception("Failed to process campaign %s", campaign.name)

        logger.info("Drip engine: sent %d steps, %d errors", sent_count, len(errors))
        return {"sent": sent_count, "errors": errors}

    async def check_replies(self) -> dict[str, Any]:
        """Poll for replies to sent drip steps."""
        reply_count = 0

        if self._gmail is None:
            return {"replies_detected": 0, "note": "Gmail not configured"}

        try:
            campaigns = await self._crm.list_campaigns()
            active = [c for c in campaigns if getattr(c, "status", None) in ("ACTIVE", "active")]

            for campaign in active:
                steps = await self._crm.list_drip_steps(
                    filters={"campaign_id": str(campaign.id)},
                )
                sent_unreplied = [s for s in steps if s.sent_at and not s.reply_received]

                for step in sent_unreplied:
                    try:
                        has_reply = await self._gmail.check_reply(
                            to=str(step.lead_id),
                            subject=step.email_subject,
                        )
                        if has_reply:
                            step.reply_received = True
                            reply_count += 1
                    except (IraError, Exception):
                        logger.debug("Reply check failed for step %d", step.step_number)

        except (DatabaseError, Exception):
            logger.exception("Reply check cycle failed")

        return {"replies_detected": reply_count}

    async def run_cycle(self) -> dict[str, Any]:
        """Full drip cycle: evaluate, send pending, check replies."""
        evaluation = await self.evaluate_campaigns()
        send_result = await self.send_pending_steps()
        reply_result = await self.check_replies()

        return {
            "evaluation": evaluation,
            "sends": send_result,
            "replies": reply_result,
        }
