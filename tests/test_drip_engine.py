"""Tests for the AutonomousDripEngine.

Covers campaign creation, step scheduling, campaign-cycle execution
(sending due emails, skipping future ones), and reply checking.
All external services (Gmail, MessageBus, LLM) are mocked.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.data.crm import (
    Base,
    CampaignStatus,
    CRMDatabase,
    DripCampaignModel,
)
from ira.data.models import Channel, DealStage, Direction
from ira.systems.drip_engine import AutonomousDripEngine


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def crm_db():
    with patch("ira.data.crm.get_settings") as mock_settings:
        mock_settings.return_value.database.url = "sqlite+aiosqlite://"
        db = CRMDatabase(database_url="sqlite+aiosqlite://")
    await db.create_tables()
    yield db
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await db._engine.dispose()


def _mock_drip_settings():
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = ""
    s.llm.openai_model = "gpt-4.1"
    s.google.ira_email = "ira@machinecraft.org"
    return s


@pytest.fixture()
def mock_bus():
    bus = AsyncMock()
    bus.send = AsyncMock(
        return_value=MagicMock(
            response=json.dumps({"subject": "Follow-up", "body": "Hi there!"})
        )
    )
    return bus


@pytest.fixture()
def mock_gmail():
    gmail = AsyncMock()
    gmail.create_draft = AsyncMock(return_value={"id": "draft_123"})
    gmail.send_notification = AsyncMock()
    gmail.check_replies = AsyncMock(return_value=[])
    return gmail


@pytest.fixture()
async def engine(crm_db, mock_bus, mock_gmail):
    quote_mgr = MagicMock()
    with patch("ira.systems.drip_engine.get_settings", return_value=_mock_drip_settings()):
        eng = AutonomousDripEngine(
            crm=crm_db,
            quotes=quote_mgr,
            message_bus=mock_bus,
            gmail=mock_gmail,
        )
    return eng


# ── helpers ───────────────────────────────────────────────────────────────────


async def _make_company(crm_db, **kw):
    defaults = {"id": str(uuid4()), "name": f"Co-{uuid4().hex[:6]}", "region": "EU"}
    defaults.update(kw)
    return await crm_db.create_company(**defaults)


async def _make_contact(crm_db, **kw):
    defaults = {
        "id": str(uuid4()),
        "name": "Test Contact",
        "email": f"{uuid4().hex[:8]}@test.com",
        "source": "web_form",
        "lead_score": 50.0,
    }
    defaults.update(kw)
    return await crm_db.create_contact(**defaults)


# ═════════════════════════════════════════════════════════════════════════════
# 1. Campaign creation
# ═════════════════════════════════════════════════════════════════════════════


class TestCampaignCreation:

    async def test_create_campaign_returns_active_model(self, crm_db, engine):
        co = await _make_company(crm_db, name="CampCo", region="EU")
        await _make_contact(crm_db, company_id=str(co.id))

        campaign = await engine.create_campaign(
            name="Launch",
            target_segment={"region": "EU"},
            steps=[{"step_number": 1, "delay_days": 0}],
        )

        assert isinstance(campaign, DripCampaignModel)
        assert campaign.status == CampaignStatus.ACTIVE
        assert campaign.name == "Launch"

    async def test_create_campaign_enrolls_matching_contacts_only(self, crm_db, engine):
        eu_co = await _make_company(crm_db, name="EU-Co", region="EU")
        mena_co = await _make_company(crm_db, name="MENA-Co", region="MENA")

        await _make_contact(crm_db, name="EU-1", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="EU-2", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="MENA-1", company_id=str(mena_co.id))

        campaign = await engine.create_campaign(
            name="EU Only",
            target_segment={"region": "EU"},
            steps=[{"step_number": 1, "delay_days": 0}],
        )

        steps = await crm_db.list_drip_steps(filters={"campaign_id": str(campaign.id)})
        contact_ids = {s.contact_id for s in steps}
        assert len(contact_ids) == 2

    async def test_create_campaign_generates_steps_per_contact(self, crm_db, engine):
        co = await _make_company(crm_db, name="MultiCo", region="EU")
        await _make_contact(crm_db, company_id=str(co.id))
        await _make_contact(crm_db, company_id=str(co.id))

        campaign = await engine.create_campaign(
            name="Multi",
            target_segment={"region": "EU"},
            steps=[
                {"step_number": 1, "delay_days": 0},
                {"step_number": 2, "delay_days": 5},
                {"step_number": 3, "delay_days": 10},
            ],
        )

        steps = await crm_db.list_drip_steps(filters={"campaign_id": str(campaign.id)})
        assert len(steps) == 6  # 2 contacts x 3 steps

    async def test_create_campaign_with_no_matching_contacts(self, crm_db, engine):
        campaign = await engine.create_campaign(
            name="Empty",
            target_segment={"region": "ANTARCTICA"},
            steps=[{"step_number": 1, "delay_days": 0}],
        )

        steps = await crm_db.list_drip_steps(filters={"campaign_id": str(campaign.id)})
        assert len(steps) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 2. Step scheduling
# ═════════════════════════════════════════════════════════════════════════════


class TestStepScheduling:

    async def test_steps_scheduled_with_correct_delays(self, crm_db, engine):
        co = await _make_company(crm_db, name="SchedCo", region="EU")
        await _make_contact(crm_db, company_id=str(co.id))

        campaign = await engine.create_campaign(
            name="Timed",
            target_segment={"region": "EU"},
            steps=[
                {"step_number": 1, "delay_days": 0},
                {"step_number": 2, "delay_days": 7},
                {"step_number": 3, "delay_days": 14},
            ],
        )

        steps = await crm_db.list_drip_steps(filters={"campaign_id": str(campaign.id)})
        by_num = sorted(steps, key=lambda s: s.step_number)

        assert by_num[0].scheduled_at is not None
        assert by_num[1].scheduled_at is not None
        assert by_num[2].scheduled_at is not None

        delta_1_2 = by_num[1].scheduled_at - by_num[0].scheduled_at
        delta_1_3 = by_num[2].scheduled_at - by_num[0].scheduled_at
        assert abs(delta_1_2.days - 7) <= 1
        assert abs(delta_1_3.days - 14) <= 1

    async def test_template_stored_as_email_body(self, crm_db, engine):
        co = await _make_company(crm_db, name="TplCo", region="EU")
        await _make_contact(crm_db, company_id=str(co.id))

        template = "Subject: Hello\n\nDear {name}, welcome!"
        campaign = await engine.create_campaign(
            name="Template",
            target_segment={"region": "EU"},
            steps=[{"step_number": 1, "delay_days": 0, "template": template}],
        )

        steps = await crm_db.list_drip_steps(filters={"campaign_id": str(campaign.id)})
        assert steps[0].email_body == template
        assert steps[0].email_subject == "Subject: Hello"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Campaign cycle — action execution
# ═════════════════════════════════════════════════════════════════════════════


class TestCampaignCycleExecution:

    async def test_sends_due_steps(self, crm_db, engine, mock_bus, mock_gmail):
        co = await _make_company(crm_db, name="SendCo", region="EU")
        contact = await _make_contact(
            crm_db, name="Alice", email="alice@test.com", company_id=str(co.id)
        )

        campaign = await crm_db.create_campaign(
            name="Send Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Intro",
            email_body="Hello!",
            scheduled_at=past,
        )

        sent = await engine.run_campaign_cycle()

        assert sent >= 1
        mock_gmail.create_draft.assert_called()
        mock_bus.send.assert_called()

        msg = mock_bus.send.call_args[0][0]
        assert msg.to_agent == "hermes"

    async def test_skips_future_steps(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="FutureCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Future", target_segment={}, status=CampaignStatus.ACTIVE
        )
        future = datetime.now(timezone.utc) + timedelta(days=7)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            scheduled_at=future,
        )

        sent = await engine.run_campaign_cycle()

        assert sent == 0
        mock_gmail.create_draft.assert_not_called()

    async def test_skips_paused_campaigns(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="PausedCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Paused", target_segment={}, status=CampaignStatus.PAUSED
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            scheduled_at=past,
        )

        sent = await engine.run_campaign_cycle()

        assert sent == 0
        mock_gmail.create_draft.assert_not_called()

    async def test_records_interaction_after_send(self, crm_db, engine, mock_bus, mock_gmail):
        co = await _make_company(crm_db, name="LogCo", region="EU")
        contact = await _make_contact(
            crm_db, name="Bob", email="bob@test.com", company_id=str(co.id)
        )

        campaign = await crm_db.create_campaign(
            name="Log Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hi",
            email_body="Body",
            scheduled_at=past,
        )

        await engine.run_campaign_cycle()

        interactions = await crm_db.list_interactions(
            filters={"contact_id": str(contact.id)}
        )
        assert len(interactions) >= 1
        assert interactions[0].direction.value == "OUTBOUND"

    async def test_marks_step_as_sent(self, crm_db, engine, mock_bus, mock_gmail):
        co = await _make_company(crm_db, name="MarkCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Mark Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        step = await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hi",
            scheduled_at=past,
        )

        await engine.run_campaign_cycle()

        updated = await crm_db.get_drip_step(step.id)
        assert updated is not None
        assert updated.sent_at is not None

    async def test_handles_gmail_failure_gracefully(self, crm_db, engine, mock_bus, mock_gmail):
        mock_gmail.create_draft = AsyncMock(side_effect=RuntimeError("SMTP error"))

        co = await _make_company(crm_db, name="FailCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Fail Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        step = await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hi",
            scheduled_at=past,
        )

        sent = await engine.run_campaign_cycle()

        assert sent == 0
        updated = await crm_db.get_drip_step(step.id)
        assert updated.sent_at is None


# ═════════════════════════════════════════════════════════════════════════════
# 4. Reply checking
# ═════════════════════════════════════════════════════════════════════════════


class TestReplyChecking:

    async def test_detects_reply_and_records_it(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="ReplyCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Reply Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(days=2)
        step = await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hello",
            sent_at=past,
            scheduled_at=past,
        )

        mock_gmail.check_replies = AsyncMock(
            return_value=[{"body": "Interested!", "from": contact.email}]
        )

        await engine.run_campaign_cycle()

        updated = await crm_db.get_drip_step(step.id)
        assert updated.reply_received is True
        assert updated.reply_content == "Interested!"

    async def test_skips_already_replied_steps(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="SkipCo", region="EU")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Skip Reply", target_segment={}, status=CampaignStatus.ACTIVE
        )
        past = datetime.now(timezone.utc) - timedelta(days=2)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hello",
            sent_at=past,
            scheduled_at=past,
            reply_received=True,
            reply_content="Already replied",
        )

        await engine.run_campaign_cycle()

        mock_gmail.check_replies.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# 5. Parse email response
# ═════════════════════════════════════════════════════════════════════════════


class TestParseEmailResponse:

    def test_parses_valid_json(self):
        step = MagicMock()
        step.email_subject = "Fallback Subject"
        step.email_body = "Fallback Body"

        result = AutonomousDripEngine._parse_email_response(
            json.dumps({"subject": "Custom Subject", "body": "Custom Body"}),
            step,
        )

        assert result["subject"] == "Custom Subject"
        assert result["body"] == "Custom Body"

    def test_falls_back_on_invalid_json(self):
        step = MagicMock()
        step.email_subject = "Fallback Subject"
        step.email_body = "Fallback Body"

        result = AutonomousDripEngine._parse_email_response("not json", step)

        assert result["subject"] == "Fallback Subject"
        assert result["body"] == "not json"

    def test_falls_back_on_empty_response(self):
        step = MagicMock()
        step.email_subject = "Fallback Subject"
        step.email_body = "Fallback Body"

        result = AutonomousDripEngine._parse_email_response("", step)

        assert result["subject"] == "Fallback Subject"
        assert result["body"] == "Fallback Body"
