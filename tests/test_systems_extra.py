"""Tests for previously-untested systems modules.

Covers: data_event_bus, musculoskeletal, circulatory, crm_populator.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── DataEventBus ─────────────────────────────────────────────────────────


class TestDataEventBus:
    def _make_bus(self):
        from ira.systems.data_event_bus import DataEventBus
        return DataEventBus(maxsize=100)

    def _make_event(self, event_type_str: str = "contact_created"):
        from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
        return DataEvent(
            event_type=EventType(event_type_str),
            entity_type="contact",
            entity_id="test-123",
            payload={"name": "Test User"},
            source_store=SourceStore.CRM,
        )

    def test_subscribe_registers_handler(self):
        from ira.systems.data_event_bus import EventType
        bus = self._make_bus()
        handler = AsyncMock()
        bus.subscribe(EventType.CONTACT_CREATED, handler)
        assert len(bus._handlers[EventType.CONTACT_CREATED]) == 1

    @pytest.mark.asyncio
    async def test_emit_and_dispatch(self):
        bus = self._make_bus()
        handler = AsyncMock()
        from ira.systems.data_event_bus import EventType
        bus.subscribe(EventType.CONTACT_CREATED, handler)

        await bus.start()
        event = self._make_event()
        await bus.emit(event)
        await asyncio.sleep(0.1)
        await bus.stop()

        handler.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_global_handler_receives_all(self):
        bus = self._make_bus()
        handler = AsyncMock()
        bus.subscribe_all(handler)

        await bus.start()
        await bus.emit(self._make_event("contact_created"))
        await bus.emit(self._make_event("deal_created"))
        await asyncio.sleep(0.1)
        await bus.stop()

        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        bus = self._make_bus()
        await bus.start()
        assert bus._running is True
        await bus.stop()
        assert bus._running is False

    @pytest.mark.asyncio
    async def test_pending_count(self):
        bus = self._make_bus()
        assert bus.pending_count == 0

        await bus.emit(self._make_event("contact_created"))
        await bus.emit(self._make_event("deal_created"))
        assert bus.pending_count == 2

        await bus.start()
        await asyncio.sleep(0.15)
        await bus.stop()
        assert bus.pending_count == 0


# ── MusculoskeletalSystem ────────────────────────────────────────────────


class TestMusculoskeletal:
    """Uses in-memory SQLite for isolated tests."""

    IN_MEMORY_DB = "sqlite+aiosqlite:///:memory:"

    @pytest.fixture()
    def mock_settings(self):
        s = MagicMock()
        s.database.url = self.IN_MEMORY_DB
        return s

    @pytest.fixture()
    async def system(self, mock_settings):
        with patch("ira.systems.musculoskeletal.get_settings", return_value=mock_settings):
            from ira.systems.musculoskeletal import MusculoskeletalSystem
            ms = MusculoskeletalSystem(database_url=self.IN_MEMORY_DB)
            await ms.create_tables()
            yield ms

    @pytest.mark.asyncio
    async def test_create_tables(self, system):
        assert system is not None

    @pytest.mark.asyncio
    async def test_record_and_get_action(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        action = ActionRecord(
            action_type=ActionType.EMAIL_SENT,
            target="test@example.com",
            details={"subject": "Follow up"},
        )
        action_id = await system.record_action(action)
        assert action_id is not None

        actions = await system.get_actions(action_type="EMAIL_SENT", since_days=1)
        assert len(actions) >= 1
        assert actions[0]["target"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_update_outcome(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        action = ActionRecord(
            action_type=ActionType.LEAD_QUALIFIED,
            target="lead@example.com",
        )
        action_id = await system.record_action(action)
        updated = await system.update_outcome(action_id, "SUCCESS", {"note": "converted"})
        assert updated is True

    @pytest.mark.asyncio
    async def test_extract_myokines(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        await system.record_action(ActionRecord(
            action_type=ActionType.EMAIL_SENT, target="a@test.com",
        ))
        await system.record_action(ActionRecord(
            action_type=ActionType.EMAIL_SENT, target="b@test.com",
        ))
        myokines = await system.extract_myokines(period_days=1)
        assert isinstance(myokines, dict)
        assert "total_actions" in myokines
        assert myokines["total_actions"] == 2
        assert "email_metrics" in myokines
        assert "quote_metrics" in myokines
        assert "lead_metrics" in myokines
        assert "top_strategies" in myokines
        assert "recommendations" in myokines

    @pytest.mark.asyncio
    async def test_extract_myokines_empty_period(self, system):
        """extract_myokines returns empty structure when no actions in period."""
        myokines = await system.extract_myokines(period_days=1)
        assert myokines["total_actions"] == 0
        assert myokines["outcomes"] == {}
        assert myokines["email_metrics"] == {}
        assert myokines["quote_metrics"] == {}
        assert myokines["lead_metrics"] == {}
        assert myokines["top_strategies"] == []
        assert myokines["recommendations"] == []

    @pytest.mark.asyncio
    async def test_get_actions_filter_by_action_type(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        await system.record_action(ActionRecord(
            action_type=ActionType.EMAIL_SENT, target="email@test.com",
        ))
        await system.record_action(ActionRecord(
            action_type=ActionType.QUOTE_GENERATED, target="quote@test.com",
        ))
        await system.record_action(ActionRecord(
            action_type=ActionType.EMAIL_SENT, target="email2@test.com",
        ))

        email_actions = await system.get_actions(action_type="EMAIL_SENT", since_days=1)
        assert len(email_actions) == 2
        assert all(a["action_type"] == "EMAIL_SENT" for a in email_actions)

        quote_actions = await system.get_actions(action_type="QUOTE_GENERATED", since_days=1)
        assert len(quote_actions) == 1
        assert quote_actions[0]["target"] == "quote@test.com"

    @pytest.mark.asyncio
    async def test_get_actions_filter_by_outcome(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        a1 = ActionRecord(action_type=ActionType.LEAD_QUALIFIED, target="lead1@test.com")
        a2 = ActionRecord(action_type=ActionType.LEAD_QUALIFIED, target="lead2@test.com")
        id1 = await system.record_action(a1)
        id2 = await system.record_action(a2)
        await system.update_outcome(id1, "SUCCESS", {"note": "converted"})
        await system.update_outcome(id2, "FAILURE", {"reason": "no budget"})

        success_actions = await system.get_actions(outcome="SUCCESS", since_days=1)
        assert len(success_actions) == 1
        assert success_actions[0]["target"] == "lead1@test.com"

        failure_actions = await system.get_actions(outcome="FAILURE", since_days=1)
        assert len(failure_actions) == 1
        assert failure_actions[0]["target"] == "lead2@test.com"

    @pytest.mark.asyncio
    async def test_get_actions_filter_by_since_days(self, system):
        from ira.systems.musculoskeletal import ActionRecord, ActionType
        await system.record_action(ActionRecord(
            action_type=ActionType.EMAIL_SENT, target="recent@test.com",
        ))

        recent = await system.get_actions(since_days=30)
        assert len(recent) >= 1

        old = await system.get_actions(since_days=0)
        assert len(old) == 0


# ── CirculatorySystem ────────────────────────────────────────────────────


class TestCirculatory:
    def test_constructor_registers_handlers(self, tmp_path: Path):
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEventBus
            from ira.systems.circulatory import CirculatorySystem
            bus = DataEventBus()
            crm = AsyncMock()
            graph = AsyncMock()
            cs = CirculatorySystem(bus, crm=crm, graph=graph)
            assert len(bus._global_handlers) >= 1

    @pytest.mark.asyncio
    async def test_ledger_handler_writes_file(self, tmp_path: Path):
        ledger_path = tmp_path / "ledger.jsonl"
        with patch("ira.systems.circulatory._LEDGER_PATH", ledger_path):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem
            bus = DataEventBus()
            cs = CirculatorySystem(bus)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={"name": "Test"},
                source_store=SourceStore.CRM,
            )
            await cs._ledger_handler(event)

            lines = ledger_path.read_text().strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["entity_id"] == "c-1"

    @pytest.mark.asyncio
    async def test_event_subscription_wiring(self, tmp_path: Path):
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEventBus, EventType
            from ira.systems.circulatory import CirculatorySystem
            bus = DataEventBus()
            crm = AsyncMock()
            graph = AsyncMock()
            qdrant = AsyncMock()
            embedding = AsyncMock()
            cs = CirculatorySystem(bus, crm=crm, graph=graph, qdrant=qdrant, embedding=embedding)
            assert EventType.CONTACT_CREATED in bus._handlers

    @pytest.mark.asyncio
    async def test_crm_to_neo4j_contact_sync_handler(self, tmp_path: Path):
        """CRM-to-Neo4j contact sync handler adds person and optionally contact_type."""
        ledger_path = tmp_path / "ledger.jsonl"
        with patch("ira.systems.circulatory._LEDGER_PATH", ledger_path):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            graph = AsyncMock()
            graph._run_cypher_write = AsyncMock()
            cs = CirculatorySystem(bus, graph=graph)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={
                    "email": "alice@acme.com",
                    "name": "Alice",
                    "company": "Acme Corp",
                    "role": "Engineer",
                    "contact_type": "lead",
                    "lead_score": 75,
                },
                source_store=SourceStore.CRM,
            )
            await cs._crm_to_neo4j_contact(event)

            graph.add_person.assert_awaited_once_with(
                name="Alice",
                email="alice@acme.com",
                company_name="Acme Corp",
                role="Engineer",
            )
            graph._run_cypher_write.assert_awaited_once_with(
                "MATCH (p:Person {email: $email}) "
                "SET p.contact_type = $ct, p.lead_score = $score",
                {"email": "alice@acme.com", "ct": "lead", "score": 75},
            )

    @pytest.mark.asyncio
    async def test_crm_to_neo4j_contact_skips_neo4j_source(self, tmp_path: Path):
        """CRM-to-Neo4j handler skips events from Neo4j to avoid feedback loops."""
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            graph = AsyncMock()
            cs = CirculatorySystem(bus, graph=graph)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={"email": "bob@test.com", "name": "Bob"},
                source_store=SourceStore.NEO4J,
            )
            await cs._crm_to_neo4j_contact(event)

            graph.add_person.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_crm_to_neo4j_contact_skips_empty_email(self, tmp_path: Path):
        """CRM-to-Neo4j handler skips contacts without email."""
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            graph = AsyncMock()
            cs = CirculatorySystem(bus, graph=graph)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={"name": "No Email", "company": "Acme"},
                source_store=SourceStore.CRM,
            )
            await cs._crm_to_neo4j_contact(event)

            graph.add_person.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_crm_to_qdrant_sync_handler(self, tmp_path: Path):
        """CRM-to-Qdrant sync handler upserts contact as KnowledgeItem."""
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            qdrant = AsyncMock()
            cs = CirculatorySystem(bus, qdrant=qdrant)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={
                    "email": "carol@widgets.com",
                    "name": "Carol",
                    "company": "Widgets Inc",
                    "contact_type": "qualified",
                    "role": "CTO",
                    "lead_score": 90,
                    "source": "linkedin",
                },
                source_store=SourceStore.CRM,
            )
            await cs._crm_to_qdrant(event)

            qdrant.upsert_items.assert_awaited_once()
            items = qdrant.upsert_items.call_args[0][0]
            assert len(items) == 1
            item = items[0]
            assert item.source == "crm:contact:carol@widgets.com"
            assert item.source_category == "crm_contact"
            assert "Carol" in item.content
            assert "carol@widgets.com" in item.content
            assert "Widgets Inc" in item.content
            assert item.metadata["email"] == "carol@widgets.com"
            assert item.metadata["contact_type"] == "qualified"
            assert item.metadata["lead_score"] == 90

    @pytest.mark.asyncio
    async def test_crm_to_qdrant_skips_qdrant_source(self, tmp_path: Path):
        """CRM-to-Qdrant handler skips events from Qdrant to avoid feedback loops."""
        with patch("ira.systems.circulatory._LEDGER_PATH", tmp_path / "ledger.jsonl"):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            qdrant = AsyncMock()
            cs = CirculatorySystem(bus, qdrant=qdrant)

            event = DataEvent(
                event_type=EventType.CONTACT_CREATED,
                entity_type="contact",
                entity_id="c-1",
                payload={"email": "dave@test.com", "name": "Dave"},
                source_store=SourceStore.QDRANT,
            )
            await cs._crm_to_qdrant(event)

            qdrant.upsert_items.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ledger_logging_multiple_events(self, tmp_path: Path):
        """Ledger handler appends multiple events to JSONL file."""
        ledger_path = tmp_path / "ledger.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with patch("ira.systems.circulatory._LEDGER_PATH", ledger_path):
            from ira.systems.data_event_bus import DataEvent, DataEventBus, EventType, SourceStore
            from ira.systems.circulatory import CirculatorySystem

            bus = DataEventBus()
            cs = CirculatorySystem(bus)

            for i in range(3):
                event = DataEvent(
                    event_type=EventType.CONTACT_CREATED,
                    entity_type="contact",
                    entity_id=f"c-{i}",
                    payload={"name": f"User {i}"},
                    source_store=SourceStore.CRM,
                )
                await cs._ledger_handler(event)

            lines = ledger_path.read_text().strip().split("\n")
            assert len(lines) == 3
            for i, line in enumerate(lines):
                record = json.loads(line)
                assert record["entity_id"] == f"c-{i}"
                assert record["event_type"] == "contact_created"
                assert record["source_store"] == "crm"


# ── CRMPopulator ─────────────────────────────────────────────────────────


class TestCRMPopulator:
    @pytest.fixture()
    def mock_settings(self):
        s = MagicMock()
        s.google.credentials_path = ""
        s.google.token_path = ""
        s.qdrant.url = "http://localhost:6333"
        s.qdrant.collection = "test"
        s.neo4j.uri = "bolt://localhost:7687"
        s.neo4j.user = "neo4j"
        s.neo4j.password.get_secret_value.return_value = "test"
        s.llm.openai_api_key.get_secret_value.return_value = "test-key"
        s.llm.openai_model = "gpt-test"
        s.llm.anthropic_api_key.get_secret_value.return_value = ""
        s.llm.anthropic_model = "claude-test"
        s.external_apis.api_key.get_secret_value.return_value = ""
        s.embedding.api_key.get_secret_value.return_value = "test-key"
        s.embedding.model = "voyage-3"
        return s

    @pytest.mark.asyncio
    async def test_dry_run_skips_insert(self, mock_settings):
        with patch("ira.systems.crm_populator.get_settings", return_value=mock_settings), \
             patch("ira.config.get_settings", return_value=mock_settings):
            delphi = AsyncMock()
            crm = AsyncMock()
            crm.find_contact_by_email = AsyncMock(return_value=None)

            from ira.systems.crm_populator import CRMPopulator
            pop = CRMPopulator(delphi=delphi, crm=crm, dry_run=True)
            pop._extract_from_gmail = AsyncMock(return_value=[])
            pop._extract_from_qdrant = AsyncMock(return_value=[])
            pop._extract_from_neo4j = AsyncMock(return_value=[])

            await pop.populate(sources=["gmail"])
            crm.create_contact.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_populate_with_no_sources(self, mock_settings):
        with patch("ira.systems.crm_populator.get_settings", return_value=mock_settings), \
             patch("ira.config.get_settings", return_value=mock_settings):
            delphi = AsyncMock()
            crm = AsyncMock()

            from ira.systems.crm_populator import CRMPopulator
            pop = CRMPopulator(delphi=delphi, crm=crm, dry_run=True)
            pop._extract_from_gmail = AsyncMock(return_value=[])
            pop._extract_from_qdrant = AsyncMock(return_value=[])
            pop._extract_from_neo4j = AsyncMock(return_value=[])

            await pop.populate(sources=["gmail"])
            pop._extract_from_gmail.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_event_bus_wiring(self, mock_settings):
        with patch("ira.systems.crm_populator.get_settings", return_value=mock_settings), \
             patch("ira.config.get_settings", return_value=mock_settings):
            delphi = AsyncMock()
            crm = AsyncMock()
            event_bus = AsyncMock()

            from ira.systems.crm_populator import CRMPopulator
            pop = CRMPopulator(delphi=delphi, crm=crm, event_bus=event_bus)
            assert pop._event_bus is event_bus
