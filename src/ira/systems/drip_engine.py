"""Autonomous drip marketing engine for Machinecraft.

Manages multi-step email outreach campaigns — Ira as a persistent,
intelligent sales development representative.  Upstream dependencies
(MessageBus, Gmail) are injected via Protocol interfaces so the engine
is testable and decoupled from infrastructure built in later phases.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from ira.config import get_settings
from ira.data.crm import (
    CampaignStatus,
    CRMDatabase,
    DripCampaignModel,
    DripStepModel,
)
from ira.data.models import AgentMessage, Channel, Direction
from ira.data.quotes import QuoteManager

logger = logging.getLogger(__name__)


# ── Protocol interfaces for upstream dependencies ────────────────────────────


class MessageBusProtocol(Protocol):
    async def send(self, message: AgentMessage) -> AgentMessage: ...


class GmailSenderProtocol(Protocol):
    async def send_email(
        self, to: str, subject: str, body: str
    ) -> dict[str, Any]: ...

    async def check_replies(self, thread_id: str) -> list[dict[str, Any]]: ...


# ── LLM prompts ──────────────────────────────────────────────────────────────

_EVALUATE_SYSTEM_PROMPT = """\
You are a marketing analytics expert for Machinecraft, an industrial machinery
manufacturer.  Given the campaign metrics and sample email content, provide
actionable improvement suggestions.

Return ONLY valid JSON:
{
  "improvement_suggestions": ["suggestion 1", "suggestion 2"],
  "best_subject_lines": ["subject 1"],
  "recommended_changes": {"step_number": "change description"}
}"""

_ADJUST_SYSTEM_PROMPT = """\
You are a sales copywriter for Machinecraft.  Rewrite the following
underperforming drip email to be more engaging and action-oriented.
Keep the same general theme but improve the hook and call-to-action.

Return ONLY valid JSON:
{"subject": "new subject line", "body": "new email body"}"""


# ── European campaign template ───────────────────────────────────────────────

EUROPEAN_CAMPAIGN_TEMPLATE: dict[str, Any] = {
    "name": "European Market Introduction",
    "target_segment": {
        "region": "EU",
        "warmth_level": ["STRANGER", "ACQUAINTANCE"],
        "lead_score_min": 0,
        "lead_score_max": 100,
    },
    "gdpr_notice": (
        "\n\n---\nYou are receiving this email because you expressed interest "
        "in industrial machinery solutions. If you wish to unsubscribe, please "
        "reply with 'UNSUBSCRIBE'. We respect your privacy in accordance with "
        "GDPR (EU 2016/679). Your data is processed by Machinecraft for "
        "legitimate business communication purposes."
    ),
    "steps": [
        {
            "step_number": 1,
            "delay_days": 0,
            "theme": "introduction",
            "template": (
                "Subject: Machinecraft — Industrial Solutions for {industry}\n\n"
                "Dear {name},\n\n"
                "I hope this message finds you well. I'm reaching out from "
                "Machinecraft, where we specialise in precision industrial "
                "machinery for the {industry} sector across Europe.\n\n"
                "I'd love to understand your current production challenges "
                "and explore how we might help.\n\n"
                "Best regards,\nIra — Machinecraft"
            ),
        },
        {
            "step_number": 2,
            "delay_days": 5,
            "theme": "value_proposition",
            "template": (
                "Subject: How Machinecraft Reduces Downtime by 40%\n\n"
                "Dear {name},\n\n"
                "Following my previous note, I wanted to share how our "
                "clients in {region} have achieved significant improvements "
                "in production efficiency.\n\n"
                "Our machines are engineered for the European market with "
                "CE certification and local service support.\n\n"
                "Would a brief call be useful?\n\n"
                "Best regards,\nIra — Machinecraft"
            ),
        },
        {
            "step_number": 3,
            "delay_days": 12,
            "theme": "case_study",
            "template": (
                "Subject: Case Study — {industry} Success in Europe\n\n"
                "Dear {name},\n\n"
                "I thought you might find this relevant: one of our European "
                "clients in the {industry} sector recently achieved a 35% "
                "increase in throughput after deploying our machinery.\n\n"
                "I'd be happy to share the full case study.\n\n"
                "Best regards,\nIra — Machinecraft"
            ),
        },
        {
            "step_number": 4,
            "delay_days": 20,
            "theme": "meeting_request",
            "template": (
                "Subject: Quick Chat About Your Production Goals?\n\n"
                "Dear {name},\n\n"
                "I've reached out a few times and understand you're busy. "
                "If there's ever a convenient time for a 15-minute call to "
                "discuss your production requirements, I'd welcome the "
                "opportunity.\n\n"
                "No pressure at all — just let me know.\n\n"
                "Best regards,\nIra — Machinecraft"
            ),
        },
    ],
    "timezone": "Europe/Berlin",
    "send_window": {"start_hour": 9, "end_hour": 17},
}


# ── AutonomousDripEngine ────────────────────────────────────────────────────


class AutonomousDripEngine:
    """Manages multi-step email outreach campaigns."""

    def __init__(
        self,
        crm: CRMDatabase,
        quotes: QuoteManager,
        message_bus: MessageBusProtocol,
        gmail: GmailSenderProtocol,
    ) -> None:
        self._crm = crm
        self._quotes = quotes
        self._bus = message_bus
        self._gmail = gmail

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model
        self._sender_email = settings.google.ira_email

    # ── Campaign creation ────────────────────────────────────────────────

    async def create_campaign(
        self,
        name: str,
        target_segment: dict[str, Any],
        steps: list[dict[str, Any]],
    ) -> DripCampaignModel:
        contacts = await self._crm.list_contacts(filters=target_segment)
        if not contacts:
            logger.warning("No contacts match segment %s", target_segment)

        campaign = await self._crm.create_campaign(
            name=name,
            target_segment=target_segment,
            status=CampaignStatus.ACTIVE,
        )

        now = datetime.now(timezone.utc)
        for contact in contacts:
            for step_def in steps:
                delay = timedelta(days=step_def.get("delay_days", 0))
                scheduled = now + delay
                await self._crm.create_drip_step(
                    campaign_id=str(campaign.id),
                    contact_id=str(contact.id),
                    step_number=step_def["step_number"],
                    email_subject=step_def.get("template", "").split("\n")[0]
                    if step_def.get("template")
                    else None,
                    email_body=step_def.get("template"),
                    scheduled_at=scheduled,
                )

        return campaign

    # ── Campaign cycle ───────────────────────────────────────────────────

    async def run_campaign_cycle(self) -> int:
        """Process all due drip steps. Returns the number of emails sent."""
        now = datetime.now(timezone.utc)
        sent_count = 0

        # Find due steps across all active campaigns
        active_campaigns = await self._crm.list_campaigns(
            filters={"status": CampaignStatus.ACTIVE}
        )

        for campaign in active_campaigns:
            steps = await self._crm.list_drip_steps(
                filters={"campaign_id": str(campaign.id), "sent": False}
            )

            for step in steps:
                if step.scheduled_at:
                    sched = step.scheduled_at
                    if sched.tzinfo is None:
                        sched = sched.replace(tzinfo=timezone.utc)
                    if sched > now:
                        continue

                contact = await self._crm.get_contact(step.contact_id)
                if not contact:
                    logger.warning("Contact %s not found, skipping step", step.contact_id)
                    continue

                context = await self._build_contact_context(contact)
                context["step_number"] = step.step_number
                context["campaign_name"] = campaign.name

                hermes_msg = AgentMessage(
                    from_agent="drip_engine",
                    to_agent="hermes",
                    query=f"Draft drip email for step {step.step_number}",
                    context=context,
                )
                response = await self._bus.send(hermes_msg)

                email_content = self._parse_email_response(
                    response.response or "", step
                )

                try:
                    await self._gmail.send_email(
                        to=contact.email,
                        subject=email_content["subject"],
                        body=email_content["body"],
                    )
                except Exception:
                    logger.exception("Failed to send email to %s", contact.email)
                    continue

                await self._crm.update_drip_step(
                    str(step.id),
                    sent_at=now,
                    email_subject=email_content["subject"],
                    email_body=email_content["body"],
                )

                await self._crm.create_interaction(
                    contact_id=str(contact.id),
                    channel=Channel.EMAIL,
                    direction=Direction.OUTBOUND,
                    subject=email_content["subject"],
                    content=email_content["body"],
                )

                sent_count += 1

        await self._check_replies()
        return sent_count

    async def _check_replies(self) -> None:
        """Check for replies to previously sent drip emails."""
        active_campaigns = await self._crm.list_campaigns(
            filters={"status": CampaignStatus.ACTIVE}
        )

        for campaign in active_campaigns:
            sent_steps = await self._crm.list_drip_steps(
                filters={"campaign_id": str(campaign.id), "sent": True}
            )

            for step in sent_steps:
                if step.reply_received:
                    continue

                contact = await self._crm.get_contact(step.contact_id)
                if not contact:
                    continue

                try:
                    replies = await self._gmail.check_replies(
                        f"drip-{campaign.id}-{contact.id}-{step.step_number}"
                    )
                except Exception:
                    logger.exception("Failed to check replies for step %s", step.id)
                    continue

                if replies:
                    reply_text = replies[0].get("body", "")
                    await self._crm.update_drip_step(
                        str(step.id),
                        reply_received=True,
                        reply_content=reply_text,
                    )

                    await self._crm.create_interaction(
                        contact_id=str(contact.id),
                        channel=Channel.EMAIL,
                        direction=Direction.INBOUND,
                        subject=f"Re: {step.email_subject or ''}",
                        content=reply_text,
                    )

    # ── Campaign evaluation ──────────────────────────────────────────────

    async def evaluate_campaign(
        self, campaign_id: str | UUID
    ) -> dict[str, Any]:
        all_steps = await self._crm.list_drip_steps(
            filters={"campaign_id": str(campaign_id)}
        )
        if not all_steps:
            return {"error": "No steps found for campaign"}

        step_numbers = sorted({s.step_number for s in all_steps})
        per_step: dict[int, dict[str, Any]] = {}

        for sn in step_numbers:
            sn_steps = [s for s in all_steps if s.step_number == sn]
            sent = [s for s in sn_steps if s.sent_at]
            opened = [s for s in sent if s.opened]
            replied = [s for s in sent if s.reply_received]

            sent_count = len(sent)
            per_step[sn] = {
                "total": len(sn_steps),
                "sent_count": sent_count,
                "open_rate": len(opened) / sent_count if sent_count else 0,
                "reply_rate": len(replied) / sent_count if sent_count else 0,
            }

        contact_ids = {str(s.contact_id) for s in all_steps}
        converted = 0
        for cid in contact_ids:
            deals = await self._crm.get_deals_for_contact(cid)
            qualified_stages = {"QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON"}
            if any(d.get("stage") in qualified_stages for d in deals):
                converted += 1

        total_contacts = len(contact_ids)
        overall_conversion = converted / total_contacts if total_contacts else 0

        best_step = max(per_step, key=lambda sn: per_step[sn]["reply_rate"]) if per_step else None

        improvement_suggestions = await self._get_improvement_suggestions(
            per_step, all_steps
        )

        return {
            "per_step_metrics": per_step,
            "overall_conversion_rate": overall_conversion,
            "best_performing_step": best_step,
            "improvement_suggestions": improvement_suggestions,
            "total_contacts": total_contacts,
            "converted_contacts": converted,
        }

    async def _get_improvement_suggestions(
        self,
        per_step: dict[int, dict[str, Any]],
        steps: list[DripStepModel],
    ) -> list[str]:
        sample_content = {}
        for s in steps[:10]:
            if s.email_subject and s.step_number not in sample_content:
                sample_content[s.step_number] = {
                    "subject": s.email_subject,
                    "body": (s.email_body or "")[:300],
                }

        context = json.dumps(
            {"metrics": per_step, "sample_emails": sample_content},
            indent=2,
            default=str,
        )

        raw = await self._llm_call(_EVALUATE_SYSTEM_PROMPT, context)
        try:
            result = json.loads(raw)
            return result.get("improvement_suggestions", [])
        except (json.JSONDecodeError, TypeError):
            return [raw] if raw else []

    # ── Auto-adjustment ──────────────────────────────────────────────────

    async def auto_adjust_campaign(self, campaign_id: str | UUID) -> dict[str, Any]:
        evaluation = await self.evaluate_campaign(campaign_id)
        adjustments: dict[str, Any] = {"paused_contacts": [], "revised_steps": []}

        all_steps = await self._crm.list_drip_steps(
            filters={"campaign_id": str(campaign_id)}
        )
        contact_ids = {str(s.contact_id) for s in all_steps}

        for cid in contact_ids:
            interactions = await self._crm.get_interactions_for_contact(cid)
            negative = any(
                i.get("sentiment") is not None and i["sentiment"] < -0.3
                for i in interactions
            )

            contact_steps = [s for s in all_steps if str(s.contact_id) == cid]
            opted_out = any(
                s.reply_content
                and any(
                    kw in s.reply_content.lower()
                    for kw in ("unsubscribe", "opt out", "stop", "remove")
                )
                for s in contact_steps
                if s.reply_content
            )

            if negative or opted_out:
                unsent = [s for s in contact_steps if not s.sent_at]
                for s in unsent:
                    await self._crm.update_drip_step(
                        str(s.id), scheduled_at=None
                    )
                adjustments["paused_contacts"].append(cid)

        per_step = evaluation.get("per_step_metrics", {})
        for sn, metrics in per_step.items():
            if metrics.get("reply_rate", 0) < 0.05 and metrics.get("sent_count", 0) > 2:
                sample_step = next(
                    (s for s in all_steps if s.step_number == sn and s.email_body),
                    None,
                )
                if not sample_step:
                    continue

                revised = await self._revise_email(
                    sample_step.email_subject or "",
                    sample_step.email_body or "",
                )

                unsent_for_step = [
                    s
                    for s in all_steps
                    if s.step_number == sn
                    and not s.sent_at
                    and str(s.contact_id) not in adjustments["paused_contacts"]
                ]
                for s in unsent_for_step:
                    await self._crm.update_drip_step(
                        str(s.id),
                        email_subject=revised.get("subject", s.email_subject),
                        email_body=revised.get("body", s.email_body),
                    )
                adjustments["revised_steps"].append(sn)

        return adjustments

    async def _revise_email(
        self, subject: str, body: str
    ) -> dict[str, str]:
        context = json.dumps({"subject": subject, "body": body[:2000]})
        raw = await self._llm_call(_ADJUST_SYSTEM_PROMPT, context)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"subject": subject, "body": body}

    # ── European campaign ────────────────────────────────────────────────

    async def create_european_campaign(self) -> DripCampaignModel:
        tmpl = EUROPEAN_CAMPAIGN_TEMPLATE
        gdpr_notice = tmpl["gdpr_notice"]
        tz = ZoneInfo(tmpl["timezone"])
        window = tmpl["send_window"]

        contacts = await self._crm.list_contacts(filters=tmpl["target_segment"])
        compliant = [c for c in contacts if self._check_gdpr_compliance(c)]

        campaign = await self._crm.create_campaign(
            name=tmpl["name"],
            target_segment=tmpl["target_segment"],
            status=CampaignStatus.ACTIVE,
        )

        now = datetime.now(timezone.utc)
        for contact in compliant:
            for step_def in tmpl["steps"]:
                delay = timedelta(days=step_def["delay_days"])
                scheduled = self._schedule_in_timezone(now + delay, tz, window)

                body = step_def["template"]
                body = body.replace("{name}", contact.name)
                body = body.replace("{region}", "Europe")
                body = body.replace("{industry}", "your industry")
                body += gdpr_notice

                subject = body.split("\n")[0].replace("Subject: ", "")

                await self._crm.create_drip_step(
                    campaign_id=str(campaign.id),
                    contact_id=str(contact.id),
                    step_number=step_def["step_number"],
                    email_subject=subject,
                    email_body=body,
                    scheduled_at=scheduled,
                )

        return campaign

    @staticmethod
    def _check_gdpr_compliance(contact: Any) -> bool:
        tags = getattr(contact, "tags", None) or {}
        if isinstance(tags, list):
            return "gdpr_optout" not in tags
        if isinstance(tags, dict):
            if tags.get("gdpr_optout"):
                return False
            return True
        return True

    @staticmethod
    def _schedule_in_timezone(
        base_dt: datetime,
        tz: ZoneInfo,
        send_window: dict[str, int],
    ) -> datetime:
        local = base_dt.astimezone(tz)
        start_hour = send_window.get("start_hour", 9)
        end_hour = send_window.get("end_hour", 17)

        if local.hour < start_hour:
            local = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        elif local.hour >= end_hour:
            local = (local + timedelta(days=1)).replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            )

        if local.weekday() >= 5:
            days_ahead = 7 - local.weekday()
            local = (local + timedelta(days=days_ahead)).replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            )

        return local.astimezone(timezone.utc)

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _build_contact_context(self, contact: Any) -> dict[str, Any]:
        contact_dict = contact.to_dict() if hasattr(contact, "to_dict") else {}
        cid = str(contact.id)

        company = None
        if hasattr(contact, "company_id") and contact.company_id:
            company_obj = await self._crm.get_company(contact.company_id)
            if company_obj:
                company = company_obj.to_dict()

        interactions = await self._crm.get_interactions_for_contact(cid)
        deals = await self._crm.get_deals_for_contact(cid)

        return {
            "contact": contact_dict,
            "company": company,
            "recent_interactions": interactions[:5],
            "deals": deals[:5],
        }

    @staticmethod
    def _parse_email_response(
        response: str, step: DripStepModel
    ) -> dict[str, str]:
        try:
            parsed = json.loads(response)
            return {
                "subject": parsed.get("subject", step.email_subject or ""),
                "body": parsed.get("body", step.email_body or ""),
            }
        except (json.JSONDecodeError, TypeError):
            return {
                "subject": step.email_subject or "Follow-up from Machinecraft",
                "body": response or step.email_body or "",
            }

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return ""

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("LLM call failed in DripEngine")
            return ""
