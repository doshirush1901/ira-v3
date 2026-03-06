"""Tests for the Phase 5 business layer.

Covers CRMDatabase CRUD and analytics, QuoteManager lifecycle, and
AutonomousDripEngine campaign management.  Uses an in-memory SQLite
database so the suite runs without a running PostgreSQL instance.
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
    CompanyModel,
    ContactModel,
    DealModel,
    DripCampaignModel,
    DripStepModel,
    InteractionModel,
)
from ira.data.models import Channel, DealStage, Direction, WarmthLevel
from ira.data.quotes import QuoteManager, QuoteModel, QuoteStatus
from ira.systems.drip_engine import AutonomousDripEngine


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
async def crm_db():
    """In-memory SQLite CRMDatabase for testing."""
    with patch("ira.data.crm.get_settings") as mock_settings:
        mock_settings.return_value.database.url = "sqlite+aiosqlite://"
        db = CRMDatabase(database_url="sqlite+aiosqlite://")
    await db.create_tables()
    yield db
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await db._engine.dispose()


@pytest.fixture()
async def quote_manager(crm_db):
    return QuoteManager(crm_db.session_factory)


@pytest.fixture()
async def drip_engine(crm_db, quote_manager):
    mock_bus = AsyncMock()
    mock_bus.send = AsyncMock(
        return_value=MagicMock(
            response=json.dumps({"subject": "Test Subject", "body": "Test Body"})
        )
    )
    mock_gmail = AsyncMock()
    mock_gmail.create_draft = AsyncMock(return_value={"id": "draft_123"})
    mock_gmail.send_notification = AsyncMock()
    mock_gmail.check_replies = AsyncMock(return_value=[])

    with patch("ira.systems.drip_engine.get_settings") as mock_settings:
        mock_llm = MagicMock()
        mock_llm.openai_api_key.get_secret_value.return_value = ""
        mock_llm.openai_model = "gpt-4.1"
        mock_settings.return_value.llm = mock_llm
        mock_settings.return_value.google.ira_email = "ira@machinecraft.org"

        engine = AutonomousDripEngine(
            crm=crm_db,
            quotes=quote_manager,
            message_bus=mock_bus,
            gmail=mock_gmail,
        )

    return engine, mock_bus, mock_gmail


async def _make_company(crm_db, **overrides):
    defaults = {"id": str(uuid4()), "name": f"Company-{uuid4().hex[:6]}", "region": "EU"}
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


async def _make_deal(crm_db, contact_id, **overrides):
    defaults = {
        "id": str(uuid4()),
        "contact_id": str(contact_id),
        "title": "Test Deal",
        "value": Decimal("10000.00"),
        "stage": DealStage.NEW,
    }
    defaults.update(overrides)
    return await crm_db.create_deal(**defaults)


# ═════════════════════════════════════════════════════════════════════════════
# 1. CRMDatabase — CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestCRMDatabase:

    @pytest.mark.asyncio
    async def test_create_and_get_company(self, crm_db):
        company = await _make_company(crm_db, name="Acme Corp", region="EU", industry="Manufacturing")
        fetched = await crm_db.get_company(company.id)

        assert fetched is not None
        assert fetched.name == "Acme Corp"
        assert fetched.region == "EU"
        assert fetched.industry == "Manufacturing"

    @pytest.mark.asyncio
    async def test_create_and_get_contact(self, crm_db):
        company = await _make_company(crm_db, name="ContactCo")
        contact = await _make_contact(
            crm_db,
            name="Alice Smith",
            email="alice@contactco.com",
            company_id=str(company.id),
        )

        by_id = await crm_db.get_contact(contact.id)
        assert by_id is not None
        assert by_id.name == "Alice Smith"
        assert by_id.company_id == str(company.id)

        by_email = await crm_db.get_contact_by_email("alice@contactco.com")
        assert by_email is not None
        assert by_email.id == contact.id

    @pytest.mark.asyncio
    async def test_update_contact(self, crm_db):
        contact = await _make_contact(crm_db, lead_score=10.0, tags={"role": "buyer"})

        updated = await crm_db.update_contact(
            contact.id, lead_score=85.0, tags={"role": "buyer", "priority": "high"}
        )

        assert updated is not None
        assert updated.lead_score == 85.0
        assert updated.tags["priority"] == "high"

    @pytest.mark.asyncio
    async def test_list_contacts_with_filters(self, crm_db):
        eu_co = await _make_company(crm_db, name="EU-Co", region="EU")
        mena_co = await _make_company(crm_db, name="MENA-Co", region="MENA")

        await _make_contact(crm_db, name="EU-1", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="EU-2", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="MENA-1", company_id=str(mena_co.id))

        eu_contacts = await crm_db.list_contacts(filters={"region": "EU"})
        assert len(eu_contacts) == 2
        assert all(c.company_id == str(eu_co.id) for c in eu_contacts)

    @pytest.mark.asyncio
    async def test_create_and_get_deal(self, crm_db):
        contact = await _make_contact(crm_db)
        deal = await _make_deal(crm_db, contact.id, title="Big Deal", value=Decimal("50000"))

        fetched = await crm_db.get_deal(deal.id)
        assert fetched is not None
        assert fetched.title == "Big Deal"
        assert float(fetched.value) == 50000.0
        assert fetched.stage == DealStage.NEW

    @pytest.mark.asyncio
    async def test_update_deal_stage(self, crm_db):
        contact = await _make_contact(crm_db)
        deal = await _make_deal(crm_db, contact.id)
        original_updated = deal.updated_at

        updated = await crm_db.update_deal(deal.id, stage=DealStage.QUALIFIED)
        assert updated is not None
        assert updated.stage == DealStage.QUALIFIED

    @pytest.mark.asyncio
    async def test_create_and_list_interactions(self, crm_db):
        contact = await _make_contact(crm_db)

        await crm_db.create_interaction(
            contact_id=str(contact.id),
            channel=Channel.EMAIL,
            direction=Direction.OUTBOUND,
            subject="Hello",
            content="First email",
        )
        await crm_db.create_interaction(
            contact_id=str(contact.id),
            channel=Channel.PHONE,
            direction=Direction.INBOUND,
            subject="Call",
            content="Phone call",
        )

        interactions = await crm_db.list_interactions(
            filters={"contact_id": str(contact.id)}
        )
        assert len(interactions) == 2

    @pytest.mark.asyncio
    async def test_create_interaction_with_deal(self, crm_db):
        contact = await _make_contact(crm_db)
        deal = await _make_deal(crm_db, contact.id)

        interaction = await crm_db.create_interaction(
            contact_id=str(contact.id),
            deal_id=str(deal.id),
            channel=Channel.MEETING,
            direction=Direction.OUTBOUND,
            subject="Demo meeting",
        )

        assert interaction.deal_id == str(deal.id)

    @pytest.mark.asyncio
    async def test_search_contacts_by_name(self, crm_db):
        await _make_contact(crm_db, name="Friedrich Mueller")
        await _make_contact(crm_db, name="Jane Doe")

        results = await crm_db.search_contacts("Friedrich")
        assert len(results) == 1
        assert results[0]["name"] == "Friedrich Mueller"

    @pytest.mark.asyncio
    async def test_search_contacts_by_email(self, crm_db):
        await _make_contact(crm_db, name="A", email="alice@acme.com")
        await _make_contact(crm_db, name="B", email="bob@other.com")

        results = await crm_db.search_contacts("acme.com")
        assert len(results) == 1
        assert results[0]["email"] == "alice@acme.com"

    @pytest.mark.asyncio
    async def test_search_contacts_by_company(self, crm_db):
        company = await _make_company(crm_db, name="Siemens AG")
        await _make_contact(crm_db, name="Hans", company_id=str(company.id))
        await _make_contact(crm_db, name="Unrelated")

        results = await crm_db.search_contacts("Siemens")
        assert len(results) == 1
        assert results[0]["name"] == "Hans"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Pipeline Summary
# ═════════════════════════════════════════════════════════════════════════════


class TestPipelineSummary:

    @pytest.mark.asyncio
    async def test_pipeline_summary_groups_by_stage(self, crm_db):
        contact = await _make_contact(crm_db)
        await _make_deal(crm_db, contact.id, value=Decimal("10000"), stage=DealStage.NEW)
        await _make_deal(crm_db, contact.id, value=Decimal("20000"), stage=DealStage.NEW)
        await _make_deal(crm_db, contact.id, value=Decimal("50000"), stage=DealStage.QUALIFIED)
        await _make_deal(crm_db, contact.id, value=Decimal("100000"), stage=DealStage.WON)

        summary = await crm_db.get_pipeline_summary()

        assert summary["total_count"] == 4
        assert summary["total_value"] == 180000.0
        assert summary["stages"]["NEW"]["count"] == 2
        assert summary["stages"]["NEW"]["total_value"] == 30000.0
        assert summary["stages"]["QUALIFIED"]["count"] == 1
        assert summary["stages"]["WON"]["count"] == 1

    @pytest.mark.asyncio
    async def test_pipeline_summary_with_filters(self, crm_db):
        contact = await _make_contact(crm_db)
        await _make_deal(
            crm_db, contact.id,
            value=Decimal("10000"), stage=DealStage.NEW, machine_model="PF1-C",
        )
        await _make_deal(
            crm_db, contact.id,
            value=Decimal("20000"), stage=DealStage.NEW, machine_model="AM-200",
        )

        summary = await crm_db.get_pipeline_summary(filters={"machine_model": "PF1-C"})

        assert summary["total_count"] == 1
        assert summary["total_value"] == 10000.0

    @pytest.mark.asyncio
    async def test_pipeline_summary_empty(self, crm_db):
        summary = await crm_db.get_pipeline_summary()

        assert summary["total_count"] == 0
        assert summary["total_value"] == 0.0
        assert summary["stages"] == {}


# ═════════════════════════════════════════════════════════════════════════════
# 3. Stale Leads
# ═════════════════════════════════════════════════════════════════════════════


class TestStaleLeads:

    @pytest.mark.asyncio
    async def test_stale_leads_returns_contacts_with_old_interactions(self, crm_db):
        stale_contact = await _make_contact(crm_db, name="Stale Lead")
        recent_contact = await _make_contact(crm_db, name="Active Lead")

        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        recent_time = datetime.now(timezone.utc) - timedelta(days=1)

        await crm_db.create_interaction(
            contact_id=str(stale_contact.id),
            channel=Channel.EMAIL,
            direction=Direction.OUTBOUND,
            subject="Old email",
            created_at=old_time,
        )
        await crm_db.create_interaction(
            contact_id=str(recent_contact.id),
            channel=Channel.EMAIL,
            direction=Direction.OUTBOUND,
            subject="Recent email",
            created_at=recent_time,
        )

        stale = await crm_db.get_stale_leads(days=14)
        stale_ids = {s["id"] for s in stale}

        assert str(stale_contact.id) in stale_ids
        assert str(recent_contact.id) not in stale_ids

    @pytest.mark.asyncio
    async def test_stale_leads_returns_contacts_with_no_interactions(self, crm_db):
        no_interaction = await _make_contact(crm_db, name="Ghost Lead")

        stale = await crm_db.get_stale_leads(days=14)
        stale_ids = {s["id"] for s in stale}

        assert str(no_interaction.id) in stale_ids

    @pytest.mark.asyncio
    async def test_stale_leads_empty_when_all_recent(self, crm_db):
        contact = await _make_contact(crm_db, name="Fresh Lead")
        await crm_db.create_interaction(
            contact_id=str(contact.id),
            channel=Channel.EMAIL,
            direction=Direction.OUTBOUND,
            subject="Just now",
            created_at=datetime.now(timezone.utc),
        )

        stale = await crm_db.get_stale_leads(days=14)
        assert len(stale) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 4. QuoteManager
# ═════════════════════════════════════════════════════════════════════════════


class TestQuoteManager:

    @pytest.mark.asyncio
    async def test_create_quote_from_inquiry(self, crm_db, quote_manager):
        contact_model = await _make_contact(crm_db, name="Buyer", email="buyer@co.com")

        from ira.data.models import Contact

        pydantic_contact = Contact(
            id=contact_model.id,
            name=contact_model.name,
            email=contact_model.email,
            company="BuyerCo",
            source="web_form",
        )

        mock_engine = AsyncMock()
        mock_engine.estimate_price = AsyncMock(
            return_value={
                "estimated_price": {"low": 40000, "mid": 50000, "high": 60000, "currency": "USD"}
            }
        )

        with patch.object(
            quote_manager,
            "_extract_machine_info",
            new_callable=AsyncMock,
            return_value={"machine_model": "PF1-C", "configuration": {"speed": "high"}},
        ):
            quote = await quote_manager.create_quote_from_inquiry(
                contact=pydantic_contact,
                inquiry_text="I need a PF1-C with high speed configuration",
                pricing_engine=mock_engine,
            )

        assert quote.status == QuoteStatus.DRAFT
        assert quote.machine_model == "PF1-C"
        assert float(quote.estimated_value) == 50000.0
        assert quote.configuration == {"speed": "high"}

    @pytest.mark.asyncio
    async def test_advance_quote_to_sent(self, crm_db, quote_manager):
        contact = await _make_contact(crm_db)
        quote = await quote_manager.create_quote(
            contact_id=str(contact.id), machine_model="AM-200", status=QuoteStatus.DRAFT
        )

        advanced = await quote_manager.advance_quote(quote.id, QuoteStatus.SENT)
        assert advanced is not None
        assert advanced.status == QuoteStatus.SENT
        assert advanced.sent_at is not None

    @pytest.mark.asyncio
    async def test_advance_quote_to_follow_up(self, crm_db, quote_manager):
        contact = await _make_contact(crm_db)
        quote = await quote_manager.create_quote(
            contact_id=str(contact.id), status=QuoteStatus.SENT
        )

        advanced = await quote_manager.advance_quote(quote.id, QuoteStatus.FOLLOW_UP_1)
        assert advanced is not None
        assert advanced.status == QuoteStatus.FOLLOW_UP_1
        assert advanced.last_follow_up_at is not None

    @pytest.mark.asyncio
    async def test_advance_quote_to_won(self, crm_db, quote_manager):
        contact = await _make_contact(crm_db)
        quote = await quote_manager.create_quote(
            contact_id=str(contact.id), status=QuoteStatus.SENT
        )

        advanced = await quote_manager.advance_quote(
            quote.id, QuoteStatus.WON, notes="Customer signed"
        )
        assert advanced is not None
        assert advanced.status == QuoteStatus.WON
        assert advanced.closed_at is not None
        assert "Customer signed" in (advanced.notes or "")

    @pytest.mark.asyncio
    async def test_get_quotes_due_for_followup(self, crm_db, quote_manager):
        contact = await _make_contact(crm_db)

        old_quote = await quote_manager.create_quote(
            contact_id=str(contact.id), status=QuoteStatus.SENT
        )
        await quote_manager.update_quote(
            old_quote.id, sent_at=datetime.now(timezone.utc) - timedelta(days=10)
        )

        recent_quote = await quote_manager.create_quote(
            contact_id=str(contact.id), status=QuoteStatus.SENT
        )
        await quote_manager.update_quote(
            recent_quote.id, sent_at=datetime.now(timezone.utc) - timedelta(days=2)
        )

        due = await quote_manager.get_quotes_due_for_followup(days_since_last=7)
        due_ids = {str(q.id) for q in due}

        assert str(old_quote.id) in due_ids
        assert str(recent_quote.id) not in due_ids

    @pytest.mark.asyncio
    async def test_link_quote_to_deal(self, crm_db, quote_manager):
        contact = await _make_contact(crm_db)
        deal = await _make_deal(crm_db, contact.id)
        quote = await quote_manager.create_quote(contact_id=str(contact.id))

        linked = await quote_manager.link_quote_to_deal(quote.id, deal.id)
        assert linked is not None
        assert linked.deal_id == str(deal.id)


# ═════════════════════════════════════════════════════════════════════════════
# 5. AutonomousDripEngine
# ═════════════════════════════════════════════════════════════════════════════


class TestDripEngine:

    @pytest.mark.asyncio
    async def test_create_campaign_selects_matching_contacts(self, crm_db, drip_engine):
        engine, mock_bus, mock_gmail = drip_engine

        eu_co = await _make_company(crm_db, name="EU-Firm", region="EU")
        mena_co = await _make_company(crm_db, name="MENA-Firm", region="MENA")

        await _make_contact(crm_db, name="EU-A", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="EU-B", company_id=str(eu_co.id))
        await _make_contact(crm_db, name="MENA-A", company_id=str(mena_co.id))

        campaign = await engine.create_campaign(
            name="EU Test",
            target_segment={"region": "EU"},
            steps=[{"step_number": 1, "delay_days": 0}],
        )

        steps = await crm_db.list_drip_steps(
            filters={"campaign_id": str(campaign.id)}
        )
        contact_ids = {s.contact_id for s in steps}
        assert len(contact_ids) == 2

    @pytest.mark.asyncio
    async def test_create_campaign_creates_steps_per_contact(self, crm_db, drip_engine):
        engine, _, _ = drip_engine

        co = await _make_company(crm_db, name="StepCo", region="EU")
        await _make_contact(crm_db, name="C1", company_id=str(co.id))
        await _make_contact(crm_db, name="C2", company_id=str(co.id))

        campaign = await engine.create_campaign(
            name="Multi-step",
            target_segment={"region": "EU"},
            steps=[
                {"step_number": 1, "delay_days": 0},
                {"step_number": 2, "delay_days": 5},
                {"step_number": 3, "delay_days": 10},
            ],
        )

        steps = await crm_db.list_drip_steps(
            filters={"campaign_id": str(campaign.id)}
        )
        assert len(steps) == 6  # 2 contacts x 3 steps

    @pytest.mark.asyncio
    async def test_create_campaign_schedules_steps(self, crm_db, drip_engine):
        engine, _, _ = drip_engine

        co = await _make_company(crm_db, name="SchedCo", region="EU")
        await _make_contact(crm_db, name="Sched-C", company_id=str(co.id))

        campaign = await engine.create_campaign(
            name="Scheduled",
            target_segment={"region": "EU"},
            steps=[
                {"step_number": 1, "delay_days": 0},
                {"step_number": 2, "delay_days": 7},
            ],
        )

        steps = await crm_db.list_drip_steps(
            filters={"campaign_id": str(campaign.id)}
        )
        steps_sorted = sorted(steps, key=lambda s: s.step_number)

        assert steps_sorted[0].scheduled_at is not None
        assert steps_sorted[1].scheduled_at is not None

        delta = steps_sorted[1].scheduled_at - steps_sorted[0].scheduled_at
        assert abs(delta.days - 7) <= 1

    @pytest.mark.asyncio
    async def test_run_campaign_cycle_sends_due_steps(self, crm_db, drip_engine):
        engine, mock_bus, mock_gmail = drip_engine

        co = await _make_company(crm_db, name="SendCo", region="EU")
        contact = await _make_contact(
            crm_db, name="Send-C", email="send@test.com", company_id=str(co.id)
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

        sent_count = await engine.run_campaign_cycle()

        assert sent_count >= 1
        mock_bus.send.assert_called()
        msg = mock_bus.send.call_args[0][0]
        assert msg.to_agent == "hermes"

        mock_gmail.create_draft.assert_called()
        call_kwargs = mock_gmail.create_draft.call_args
        assert call_kwargs[1]["to"] == "send@test.com" or call_kwargs[0][0] == "send@test.com"

        interactions = await crm_db.list_interactions(
            filters={"contact_id": str(contact.id)}
        )
        assert len(interactions) >= 1

    @pytest.mark.asyncio
    async def test_run_campaign_cycle_skips_future_steps(self, crm_db, drip_engine):
        engine, mock_bus, mock_gmail = drip_engine

        co = await _make_company(crm_db, name="FutureCo", region="EU")
        contact = await _make_contact(crm_db, name="Future-C", company_id=str(co.id))

        campaign = await crm_db.create_campaign(
            name="Future Test", target_segment={}, status=CampaignStatus.ACTIVE
        )
        future = datetime.now(timezone.utc) + timedelta(days=7)
        await crm_db.create_drip_step(
            campaign_id=str(campaign.id),
            contact_id=str(contact.id),
            step_number=1,
            scheduled_at=future,
        )

        sent_count = await engine.run_campaign_cycle()

        assert sent_count == 0
        mock_gmail.create_draft.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_campaign_cycle_checks_replies(self, crm_db, drip_engine):
        engine, mock_bus, mock_gmail = drip_engine

        co = await _make_company(crm_db, name="ReplyCo", region="EU")
        contact = await _make_contact(crm_db, name="Reply-C", company_id=str(co.id))

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
            return_value=[{"body": "Yes, I'm interested!", "from": contact.email}]
        )

        await engine.run_campaign_cycle()

        updated_step = await crm_db.get_drip_step(step.id)
        assert updated_step is not None
        assert updated_step.reply_received is True
        assert updated_step.reply_content == "Yes, I'm interested!"
