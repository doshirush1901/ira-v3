"""Tests for ira.systems.circulatory.CirculatorySystem."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.circulatory import CirculatorySystem
from ira.systems.data_event_bus import (
    DataEvent,
    DataEventBus,
    EventType,
    SourceStore,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_services():
    return {
        "crm": AsyncMock(),
        "graph": AsyncMock(),
        "qdrant": AsyncMock(),
        "embedding": AsyncMock(),
    }


@pytest.fixture()
def event_bus():
    return DataEventBus()


@pytest.fixture()
def system(event_bus, mock_services, tmp_path):
    with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
        cs = CirculatorySystem(
            event_bus,
            crm=mock_services["crm"],
            graph=mock_services["graph"],
            qdrant=mock_services["qdrant"],
            embedding=mock_services["embedding"],
        )
    return cs


def _make_event(
    event_type: EventType,
    entity_type: str = "contact",
    entity_id: str = "test-1",
    payload: dict | None = None,
    source_store: SourceStore = SourceStore.CRM,
) -> DataEvent:
    return DataEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
        source_store=source_store,
    )


# ── Construction ──────────────────────────────────────────────────────────


class TestConstruction:
    def test_registers_handlers_with_all_services(self, event_bus, mock_services, tmp_path):
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            cs = CirculatorySystem(
                event_bus,
                crm=mock_services["crm"],
                graph=mock_services["graph"],
                qdrant=mock_services["qdrant"],
                embedding=mock_services["embedding"],
            )
        assert len(event_bus._global_handlers) == 1  # ledger handler
        assert EventType.CONTACT_CREATED in event_bus._handlers
        assert EventType.COMPANY_CREATED in event_bus._handlers
        assert EventType.DEAL_CREATED in event_bus._handlers
        assert EventType.ENTITY_ADDED in event_bus._handlers

    def test_no_graph_skips_neo4j_handlers(self, event_bus, tmp_path):
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            CirculatorySystem(event_bus, crm=AsyncMock())
        assert EventType.CONTACT_CREATED not in event_bus._handlers

    def test_no_qdrant_skips_qdrant_handlers(self, event_bus, mock_services, tmp_path):
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            CirculatorySystem(event_bus, graph=mock_services["graph"])
        handlers_for_contact = event_bus._handlers.get(EventType.CONTACT_CREATED, [])
        handler_names = [h.__name__ for h in handlers_for_contact]
        assert "_crm_to_qdrant" not in handler_names


# ── CRM → Neo4j: contact ─────────────────────────────────────────────────


class TestCrmToNeo4jContact:
    async def test_calls_add_person(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CREATED,
            payload={
                "email": "alice@acme.com",
                "name": "Alice",
                "company": "Acme",
                "role": "CTO",
            },
        )
        await system._crm_to_neo4j_contact(event)

        mock_services["graph"].add_person.assert_awaited_once_with(
            name="Alice",
            email="alice@acme.com",
            company_name="Acme",
            role="CTO",
        )

    async def test_sets_contact_type_via_cypher_write(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CLASSIFIED,
            payload={
                "email": "bob@acme.com",
                "name": "Bob",
                "contact_type": "hot_lead",
                "lead_score": 85,
            },
        )
        await system._crm_to_neo4j_contact(event)

        mock_services["graph"].add_person.assert_awaited_once()
        mock_services["graph"]._run_cypher_write.assert_awaited_once()
        cypher_args = mock_services["graph"]._run_cypher_write.call_args
        query = cypher_args[0][0]
        assert "SET p.contact_type = $ct" in query
        params = cypher_args[0][1]
        assert params["ct"] == "hot_lead"
        assert params["score"] == 85

    async def test_no_contact_type_skips_cypher_write(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CREATED,
            payload={"email": "carol@acme.com", "name": "Carol"},
        )
        await system._crm_to_neo4j_contact(event)

        mock_services["graph"].add_person.assert_awaited_once()
        mock_services["graph"]._run_cypher_write.assert_not_awaited()

    async def test_missing_email_is_noop(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CREATED,
            payload={"name": "No-Email"},
        )
        await system._crm_to_neo4j_contact(event)
        mock_services["graph"].add_person.assert_not_awaited()


# ── CRM → Neo4j: company ─────────────────────────────────────────────────


class TestCrmToNeo4jCompany:
    async def test_calls_add_company(self, system, mock_services):
        event = _make_event(
            EventType.COMPANY_CREATED,
            entity_type="company",
            payload={"name": "Acme Corp", "region": "EMEA", "industry": "Manufacturing"},
        )
        await system._crm_to_neo4j_company(event)

        mock_services["graph"].add_company.assert_awaited_once_with(
            name="Acme Corp",
            region="EMEA",
            industry="Manufacturing",
        )

    async def test_missing_name_is_noop(self, system, mock_services):
        event = _make_event(
            EventType.COMPANY_CREATED,
            entity_type="company",
            payload={},
        )
        await system._crm_to_neo4j_company(event)
        mock_services["graph"].add_company.assert_not_awaited()


# ── CRM → Neo4j: deal ────────────────────────────────────────────────────


class TestCrmToNeo4jDeal:
    async def test_machine_merge_via_cypher_write(self, system, mock_services):
        event = _make_event(
            EventType.DEAL_CREATED,
            entity_type="deal",
            entity_id="deal-42",
            payload={
                "id": "deal-42",
                "company": "Acme Corp",
                "machine_model": "CNC-5000",
                "value": 150_000,
            },
        )
        await system._crm_to_neo4j_deal(event)

        mock_services["graph"].add_company.assert_awaited_once_with(name="Acme Corp")

        write_calls = mock_services["graph"]._run_cypher_write.call_args_list
        assert len(write_calls) == 2

        merge_query = write_calls[0][0][0]
        assert "MERGE (m:Machine {model: $model})" in merge_query

        link_query = write_calls[1][0][0]
        assert "INTERESTED_IN" in link_query

    async def test_deal_without_machine_skips_machine_merge(self, system, mock_services):
        event = _make_event(
            EventType.DEAL_CREATED,
            entity_type="deal",
            payload={"company": "Acme Corp"},
        )
        await system._crm_to_neo4j_deal(event)

        mock_services["graph"].add_company.assert_awaited_once()
        mock_services["graph"]._run_cypher_write.assert_not_awaited()

    async def test_deal_without_company_skips_add_company(self, system, mock_services):
        event = _make_event(
            EventType.DEAL_CREATED,
            entity_type="deal",
            payload={"machine_model": "CNC-5000"},
        )
        await system._crm_to_neo4j_deal(event)

        mock_services["graph"].add_company.assert_not_awaited()
        mock_services["graph"]._run_cypher_write.assert_awaited_once()


# ── Dedup: same-source events are skipped ─────────────────────────────────


class TestSourceDedup:
    async def test_neo4j_source_skipped_for_contact(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CREATED,
            payload={"email": "alice@acme.com", "name": "Alice"},
            source_store=SourceStore.NEO4J,
        )
        await system._crm_to_neo4j_contact(event)
        mock_services["graph"].add_person.assert_not_awaited()

    async def test_neo4j_source_skipped_for_company(self, system, mock_services):
        event = _make_event(
            EventType.COMPANY_CREATED,
            entity_type="company",
            payload={"name": "Acme"},
            source_store=SourceStore.NEO4J,
        )
        await system._crm_to_neo4j_company(event)
        mock_services["graph"].add_company.assert_not_awaited()

    async def test_neo4j_source_skipped_for_deal(self, system, mock_services):
        event = _make_event(
            EventType.DEAL_CREATED,
            entity_type="deal",
            payload={"company": "Acme", "machine_model": "CNC-5000"},
            source_store=SourceStore.NEO4J,
        )
        await system._crm_to_neo4j_deal(event)
        mock_services["graph"].add_company.assert_not_awaited()
        mock_services["graph"]._run_cypher_write.assert_not_awaited()

    async def test_crm_source_skipped_for_neo4j_to_crm(self, system, mock_services):
        event = _make_event(
            EventType.ENTITY_ADDED,
            entity_type="person",
            payload={"email": "alice@acme.com", "entity_type": "person"},
            source_store=SourceStore.CRM,
        )
        await system._neo4j_to_crm(event)
        mock_services["crm"].get_contact_by_email.assert_not_awaited()

    async def test_qdrant_source_skipped_for_crm_to_qdrant(self, system, mock_services):
        event = _make_event(
            EventType.CONTACT_CREATED,
            payload={"email": "alice@acme.com", "name": "Alice"},
            source_store=SourceStore.QDRANT,
        )
        await system._crm_to_qdrant(event)
        mock_services["qdrant"].upsert_items.assert_not_awaited()
