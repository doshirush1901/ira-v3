"""Tests for the CRM Enricher system.

Covers CRMEnricher with mocked CRM and Qdrant. No LLM or live DB required.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ira.data.models import ContactType, DealStage, WarmthLevel
from ira.systems.crm_enricher import CRMEnricher


def _make_contact(
    *,
    email: str = "test@acme.com",
    name: str = "Test User",
    company_id: str | None = "cid-1",
    role: str | None = None,
    contact_type: ContactType = ContactType.LEAD_WITH_INTERACTIONS,
    lead_score: float | None = None,
    warmth_level: WarmthLevel | None = None,
    tags: list[str] | None = None,
    source: str = "web",
) -> SimpleNamespace:
    c = SimpleNamespace()
    c.id = str(uuid4())
    c.email = email
    c.name = name
    c.company_id = company_id
    c.role = role
    c.contact_type = contact_type
    c.lead_score = lead_score
    c.warmth_level = warmth_level
    c.tags = tags
    c.source = source
    return c


def _make_company(*, region: str | None = None, industry: str | None = None) -> SimpleNamespace:
    c = SimpleNamespace()
    c.region = region
    c.industry = industry
    c.name = "Acme Corp"
    return c


@pytest.fixture
def mock_crm():
    crm = AsyncMock()
    crm.list_contacts = AsyncMock(return_value=[])
    crm.get_company = AsyncMock(return_value=None)
    crm.update_company = AsyncMock()
    crm.update_contact = AsyncMock()
    crm.get_deals_for_contact = AsyncMock(return_value=[])
    crm.create_deal = AsyncMock()
    return crm


@pytest.fixture
def mock_qdrant():
    qdrant = AsyncMock()
    qdrant.search = AsyncMock(return_value=[])
    return qdrant


@pytest.fixture
def enricher(mock_crm, mock_qdrant):
    return CRMEnricher(crm=mock_crm, qdrant=mock_qdrant, dry_run=True)


@pytest.mark.asyncio
async def test_enrich_all_empty_contacts(enricher, mock_crm, mock_qdrant):
    mock_crm.list_contacts.return_value = []
    result = await enricher.enrich_all()
    assert result["stats"]["contacts_processed"] == 0
    assert result["dry_run"] is True
    mock_qdrant.search.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_company_happy_path_region_industry(mock_crm, mock_qdrant):
    enricher = CRMEnricher(crm=mock_crm, qdrant=mock_qdrant, dry_run=False)
    contact = _make_contact(company_id="cid-1")
    company = _make_company(region=None, industry=None)
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_qdrant.search.return_value = [
        {"content": "Acme Corp is based in Germany and operates in the automotive industry.", "source": "kb"},
    ]
    await enricher.enrich_all()
    assert enricher.stats["contacts_processed"] == 1
    assert enricher.stats["companies_enriched"] == 1
    mock_crm.update_company.assert_called_once()
    call_args = mock_crm.update_company.call_args
    assert call_args[0][0] == "cid-1"
    call_kw = call_args[1]
    assert call_kw.get("region") == "Germany"
    assert call_kw.get("industry") == "Automotive"


@pytest.mark.asyncio
async def test_enrich_company_no_evidence_no_update(enricher, mock_crm, mock_qdrant):
    contact = _make_contact(company_id="cid-1")
    company = _make_company(region=None, industry=None)
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_qdrant.search.return_value = []
    await enricher.enrich_all()
    assert enricher.stats["contacts_processed"] == 1
    assert enricher.stats["companies_enriched"] == 0
    mock_crm.update_company.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_company_already_has_region_industry(enricher, mock_crm, mock_qdrant):
    contact = _make_contact(company_id="cid-1")
    company = _make_company(region="UK", industry="Packaging")
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_qdrant.search.return_value = [{"content": "Acme UK packaging.", "source": "kb"}]
    await enricher.enrich_all()
    assert enricher.stats["contacts_processed"] == 1
    assert enricher.stats["companies_enriched"] == 0
    mock_crm.update_company.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_contact_role_from_evidence(mock_crm, mock_qdrant):
    enricher = CRMEnricher(crm=mock_crm, qdrant=mock_qdrant, dry_run=False)
    contact = _make_contact(role=None, company_id="cid-1")
    company = _make_company()
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_qdrant.search.return_value = [
        {"content": "Test User, Engineering Manager at Acme, requested a quote.", "source": "kb"},
    ]
    await enricher.enrich_all()
    assert enricher.stats["roles_found"] == 1
    mock_crm.update_contact.assert_called()
    calls = mock_crm.update_contact.call_args_list
    role_calls = [c for c in calls if c[1].get("role")]
    assert len(role_calls) >= 1
    assert "role" in role_calls[0][1]


@pytest.mark.asyncio
async def test_enrich_deals_creates_deal_when_evidence_has_machine(mock_crm, mock_qdrant):
    enricher = CRMEnricher(crm=mock_crm, qdrant=mock_qdrant, dry_run=False)
    contact = _make_contact(
        contact_type=ContactType.LEAD_WITH_INTERACTIONS,
        company_id="cid-1",
    )
    company = _make_company()
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_crm.get_deals_for_contact.return_value = []
    mock_qdrant.search.side_effect = [
        [{"content": "Acme Corp ordered PF1-500 for thermoforming.", "source": "order"}],
        [{"content": "Acme Corp PF1-500 1200x800 forming area.", "source": "order"}],
        [{"content": "Quote for Acme Corp value: 450000 USD.", "source": "quotes"}],
    ]
    await enricher.enrich_all()
    assert enricher.stats["deals_created"] == 1
    assert enricher.stats["deals_valued"] == 1
    mock_crm.create_deal.assert_called_once()
    call_kw = mock_crm.create_deal.call_args[1]
    assert "PF1-500" in call_kw["title"]
    assert call_kw["machine_model"] == "PF1-500"
    assert call_kw["value"] == Decimal("450000")


@pytest.mark.asyncio
async def test_enrich_score_sets_lead_score(mock_crm, mock_qdrant):
    enricher = CRMEnricher(crm=mock_crm, qdrant=mock_qdrant, dry_run=False)
    contact = _make_contact(
        contact_type=ContactType.LEAD_WITH_INTERACTIONS,
        lead_score=None,
        company_id="cid-1",
    )
    company = _make_company()
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.return_value = company
    mock_qdrant.search.return_value = [
        {"content": "Acme Corp Germany automotive.", "source": "kb"},
        {"content": "Acme PF1-500 order.", "source": "kb"},
        {"content": "Quote Acme $100k.", "source": "kb"},
    ]
    await enricher.enrich_all()
    assert enricher.stats["scores_set"] == 1
    mock_crm.update_contact.assert_called()
    call_kw = mock_crm.update_contact.call_args[1]
    assert "lead_score" in call_kw


@pytest.mark.asyncio
async def test_enrich_all_handles_contact_error(enricher, mock_crm, mock_qdrant):
    contact = _make_contact(company_id="cid-1")
    mock_crm.list_contacts.return_value = [contact]
    mock_crm.get_company.side_effect = RuntimeError("DB error")
    await enricher.enrich_all()
    assert enricher.stats["errors"] == 1
    assert enricher.stats["contacts_processed"] == 0


def test_extract_region():
    content = "Acme Corp is based in the netherlands and serves Europe."
    assert CRMEnricher._extract_region(content, "Acme") == "Netherlands"


def test_extract_industry():
    content = "The company operates in the automotive and thermoforming sectors."
    assert CRMEnricher._extract_industry(content) == "Automotive"


def test_extract_machine_model():
    content = "Order for PF1-500-XL delivered to Acme."
    assert CRMEnricher._extract_machine_model(content) == "PF1-500-XL"


def test_extract_value():
    content = "Order value: 250000.00 USD."
    val, cur = CRMEnricher._extract_value(content)
    assert val == 250000.0
    assert cur == "USD"
