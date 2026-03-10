"""Tests for the AutonomousDripEngine.

Covers campaign evaluation, pending step sending, reply checking,
and the full run_cycle orchestration.
All external services (Gmail, MessageBus) are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.data.crm import (
    Base,
    CampaignStatus,
    CRMDatabase,
)
from ira.systems.drip_engine import AutonomousDripEngine


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
async def crm_db():
    CRMDatabase._reset_instances()
    with patch("ira.data.crm.get_settings") as mock_settings:
        mock_settings.return_value.database.url = "sqlite+aiosqlite://"
        db = CRMDatabase(database_url="sqlite+aiosqlite://")
    await db.create_tables()
    yield db
    CRMDatabase._reset_instances()


@pytest.fixture()
def mock_bus():
    bus = AsyncMock()
    bus.send = AsyncMock()
    return bus


@pytest.fixture()
def mock_gmail():
    gmail = AsyncMock()
    gmail.send_draft = AsyncMock()
    gmail.check_reply = AsyncMock(return_value=False)
    gmail.create_draft = AsyncMock(return_value={"id": "draft_123"})
    gmail.send_notification = AsyncMock()
    return gmail


@pytest.fixture()
async def engine(crm_db, mock_bus, mock_gmail):
    eng = AutonomousDripEngine(
        crm=crm_db,
        quotes=MagicMock(),
        message_bus=mock_bus,
        gmail=mock_gmail,
    )
    return eng


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_company(crm_db, **overrides):
    defaults = {"id": str(uuid4()), "name": f"Co-{uuid4().hex[:6]}", "region": "EU"}
    defaults.update(overrides)
    return await crm_db.create_company(**defaults)


async def _make_contact(crm_db, **overrides):
    defaults = {
        "id": str(uuid4()),
        "name": "Test Contact",
        "email": f"{uuid4().hex[:8]}@test.com",
        "source": "web_form",
        "lead_score": 50.0,
    }
    defaults.update(overrides)
    return await crm_db.create_contact(**defaults)


# ═════════════════════════════════════════════════════════════════════════════
# 1. evaluate_campaigns
# ═════════════════════════════════════════════════════════════════════════════


class TestEvaluateCampaigns:

    @pytest.mark.asyncio
    async def test_returns_campaign_count(self, crm_db, engine):
        await crm_db.create_campaign(
            name="Camp A", target_segment={}, status=CampaignStatus.ACTIVE,
        )
        await crm_db.create_campaign(
            name="Camp B", target_segment={}, status=CampaignStatus.PAUSED,
        )

        result = await engine.evaluate_campaigns()
        assert result["campaigns"] == 2
        assert result["active"] == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_campaigns(self, engine):
        result = await engine.evaluate_campaigns()
        assert result["campaigns"] == 0
        assert result["active"] == 0

    @pytest.mark.asyncio
    async def test_stats_include_reply_rate(self, crm_db, engine):
        co = await _make_company(crm_db, name="StatsCo")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Stats Test", target_segment={}, status=CampaignStatus.ACTIVE,
        )
        past = datetime.now(timezone.utc) - timedelta(days=1)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Hello",
            sent_at=past,
            scheduled_at=past,
        )

        result = await engine.evaluate_campaigns()
        assert len(result["stats"]) == 1
        assert result["stats"][0]["sent"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# 2. send_pending_steps
# ═════════════════════════════════════════════════════════════════════════════


class TestSendPendingSteps:

    @pytest.mark.asyncio
    async def test_sends_unsent_steps(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="SendCo")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Send Test", target_segment={}, status=CampaignStatus.ACTIVE,
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

        result = await engine.send_pending_steps()
        assert result["sent"] >= 1
        mock_gmail.create_draft.assert_called()

    @pytest.mark.asyncio
    async def test_no_sends_when_no_campaigns(self, engine, mock_gmail):
        result = await engine.send_pending_steps()
        assert result["sent"] == 0
        mock_gmail.create_draft.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_sends_for_paused_campaigns(self, crm_db, engine, mock_gmail):
        co = await _make_company(crm_db, name="PausedCo")
        contact = await _make_contact(crm_db, company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Paused", target_segment={}, status=CampaignStatus.PAUSED,
        )
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            email_subject="Intro",
            scheduled_at=past,
        )

        result = await engine.send_pending_steps()
        assert result["sent"] == 0

    @pytest.mark.asyncio
    async def test_create_draft_fallback_stores_thread_marker(self):
        class DraftOnlyAdapter:
            def __init__(self) -> None:
                self.create_draft = AsyncMock(
                    return_value={"id": "d1", "message": {"threadId": "thread-123"}},
                )

        crm = AsyncMock()
        campaign = SimpleNamespace(id="camp-1", status="ACTIVE", name="Draft Fallback")
        step = SimpleNamespace(
            id="step-1",
            contact_id="contact-1",
            step_number=1,
            email_subject="Intro",
            email_body="Hello!",
            scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
            sent_at=None,
            reply_received=False,
        )
        crm.list_campaigns = AsyncMock(return_value=[campaign])
        crm.list_drip_steps = AsyncMock(return_value=[step])
        crm.get_contact = AsyncMock(return_value=SimpleNamespace(email="lead@test.com"))
        crm.update_drip_step = AsyncMock()

        gmail = DraftOnlyAdapter()
        eng = AutonomousDripEngine(crm=crm, gmail=gmail)

        result = await eng.send_pending_steps()
        assert result["sent"] >= 1
        gmail.create_draft.assert_awaited_once()
        crm.update_drip_step.assert_awaited_once()
        assert crm.update_drip_step.await_args.kwargs["reply_content"] == "thread:thread-123"


# ═════════════════════════════════════════════════════════════════════════════
# 3. check_replies
# ═════════════════════════════════════════════════════════════════════════════


class TestCheckReplies:

    @pytest.mark.asyncio
    async def test_no_replies_when_no_campaigns(self, engine):
        result = await engine.check_replies()
        assert result["replies_detected"] == 0

    @pytest.mark.asyncio
    async def test_no_replies_without_gmail(self, crm_db):
        eng = AutonomousDripEngine(crm=crm_db, gmail=None)
        result = await eng.check_replies()
        assert result["replies_detected"] == 0
        assert "not configured" in result.get("note", "")

    @pytest.mark.asyncio
    async def test_check_replies_fallback_uses_thread_marker(self):
        class ReplyListAdapter:
            def __init__(self) -> None:
                self.check_replies = AsyncMock(return_value=[{"id": "m1"}])

        crm = AsyncMock()
        campaign = SimpleNamespace(id="camp-2", status="ACTIVE", name="Reply Fallback")
        step = SimpleNamespace(
            id="step-2",
            contact_id="contact-2",
            step_number=1,
            email_subject="Follow-up",
            sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
            reply_received=False,
            reply_content="thread:thread-xyz",
        )
        crm.list_campaigns = AsyncMock(return_value=[campaign])
        crm.list_drip_steps = AsyncMock(return_value=[step])
        crm.get_contact = AsyncMock(return_value=SimpleNamespace(email="lead@test.com"))
        crm.update_drip_step = AsyncMock()

        gmail = ReplyListAdapter()
        eng = AutonomousDripEngine(crm=crm, gmail=gmail)

        result = await eng.check_replies()
        assert result["replies_detected"] >= 1
        gmail.check_replies.assert_awaited_once_with("thread-xyz")


# ═════════════════════════════════════════════════════════════════════════════
# 4. run_cycle (full orchestration)
# ═════════════════════════════════════════════════════════════════════════════


class TestRunCycle:

    @pytest.mark.asyncio
    async def test_run_cycle_returns_all_sections(self, engine):
        result = await engine.run_cycle()
        assert "evaluation" in result
        assert "sends" in result
        assert "replies" in result

    @pytest.mark.asyncio
    async def test_run_cycle_calls_all_phases(self, engine):
        with patch.object(engine, "evaluate_campaigns", new_callable=AsyncMock, return_value={"campaigns": 0, "active": 0}) as mock_eval, \
             patch.object(engine, "send_pending_steps", new_callable=AsyncMock, return_value={"sent": 0}) as mock_send, \
             patch.object(engine, "check_replies", new_callable=AsyncMock, return_value={"replies_detected": 0}) as mock_reply:
            await engine.run_cycle()

        mock_eval.assert_called_once()
        mock_send.assert_called_once()
        mock_reply.assert_called_once()
