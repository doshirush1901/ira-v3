"""Tests for ira.brain.knowledge_graph.KnowledgeGraph."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.brain.knowledge_graph import KnowledgeGraph


# ── Fixtures ──────────────────────────────────────────────────────────────


class _AsyncResultEmpty:
    """Async-iterable that yields no records (default mock result)."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _AsyncResultRows:
    """Async-iterable that yields a predetermined list of record dicts."""

    def __init__(self, rows: list[dict]) -> None:
        self._iter = iter(rows)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _AsyncSessionCtx:
    """Mimics the Neo4j driver's session(): a sync call returning an async context manager."""

    def __init__(self, session: AsyncMock) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture()
def mock_driver():
    """Build a mock Neo4j async driver with a mock session."""
    driver = MagicMock()
    session = AsyncMock()

    session.run.return_value = _AsyncResultEmpty()
    session.execute_write = AsyncMock()

    driver.session.return_value = _AsyncSessionCtx(session)
    driver.close = AsyncMock()

    return driver, session


@pytest.fixture()
def kg(mock_driver):
    driver, _ = mock_driver
    with patch("ira.brain.knowledge_graph.AsyncGraphDatabase") as mock_agd, \
         patch("ira.brain.knowledge_graph.get_settings") as mock_settings:
        cfg = MagicMock()
        cfg.neo4j.uri = "bolt://localhost:7687"
        cfg.neo4j.user = "neo4j"
        cfg.neo4j.password.get_secret_value.return_value = "test"
        cfg.llm.openai_api_key.get_secret_value.return_value = "sk-test"
        cfg.llm.openai_model = "gpt-4o-mini"
        mock_settings.return_value = cfg
        mock_agd.driver.return_value = driver

        graph = KnowledgeGraph()
    return graph


# ── add_relationship ──────────────────────────────────────────────────────


class TestAddRelationship:
    async def test_valid_company_to_person(self, kg, mock_driver):
        driver, session = mock_driver
        result = await kg.add_relationship(
            from_type="Company",
            from_key="Acme Corp",
            rel_type="CONTACTED_BY",
            to_type="Person",
            to_key="alice@acme.com",
        )
        assert result is True
        session.run.assert_awaited_once()
        query = session.run.call_args[0][0]
        assert "MERGE (a:Company {name: $from_key})" in query
        assert "MERGE (b:Person {email: $to_key})" in query
        assert "MERGE (a)-[r:CONTACTED_BY]->(b)" in query

    async def test_valid_person_to_machine(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.add_relationship(
            from_type="Person",
            from_key="bob@example.com",
            rel_type="INTERESTED_IN",
            to_type="Machine",
            to_key="CNC-5000",
        )
        assert result is True
        query = session.run.call_args[0][0]
        assert "MERGE (a:Person {email: $from_key})" in query
        assert "MERGE (b:Machine {model: $to_key})" in query

    async def test_invalid_from_type_returns_false(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.add_relationship(
            from_type="InvalidType",
            from_key="foo",
            rel_type="WORKS_AT",
            to_type="Company",
            to_key="bar",
        )
        assert result is False
        session.run.assert_not_awaited()

    async def test_invalid_rel_type_returns_false(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.add_relationship(
            from_type="Company",
            from_key="Acme",
            rel_type="TOTALLY_MADE_UP",
            to_type="Person",
            to_key="alice@acme.com",
        )
        assert result is False
        session.run.assert_not_awaited()

    async def test_empty_from_key_returns_false(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.add_relationship(
            from_type="Company",
            from_key="",
            rel_type="WORKS_AT",
            to_type="Person",
            to_key="alice@acme.com",
        )
        assert result is False
        session.run.assert_not_awaited()

    async def test_empty_to_key_returns_false(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.add_relationship(
            from_type="Company",
            from_key="Acme",
            rel_type="WORKS_AT",
            to_type="Person",
            to_key="",
        )
        assert result is False
        session.run.assert_not_awaited()

    async def test_properties_use_parameterised_set(self, kg, mock_driver):
        """SET r += $props must be used -- never f-string interpolation of property keys."""
        _, session = mock_driver
        await kg.add_relationship(
            from_type="Company",
            from_key="Acme",
            rel_type="SUPPLIES",
            to_type="Machine",
            to_key="CNC-5000",
            properties={"since": "2024", "volume": 10},
        )
        query = session.run.call_args[0][0]
        assert "SET r += $props" in query
        params = session.run.call_args[0][1]
        assert params["props"] == {"since": "2024", "volume": 10}

    async def test_no_properties_omits_set_clause(self, kg, mock_driver):
        _, session = mock_driver
        await kg.add_relationship(
            from_type="Company",
            from_key="Acme",
            rel_type="SUPPLIES",
            to_type="Machine",
            to_key="CNC-5000",
        )
        query = session.run.call_args[0][0]
        assert "SET" not in query


# ── run_cypher ────────────────────────────────────────────────────────────


class TestRunCypher:
    async def test_read_only_query_succeeds(self, kg, mock_driver):
        _, session = mock_driver
        result = await kg.run_cypher("MATCH (n) RETURN n LIMIT 10")
        assert isinstance(result, list)
        session.run.assert_awaited_once()

    async def test_write_query_with_delete_raises(self, kg):
        with pytest.raises(ValueError, match="Write operations not allowed"):
            await kg.run_cypher("MATCH (n) DELETE n")

    async def test_write_query_with_set_raises(self, kg):
        with pytest.raises(ValueError, match="Write operations not allowed"):
            await kg.run_cypher("MATCH (n) SET n.name = 'x'")

    async def test_write_query_with_create_raises(self, kg):
        with pytest.raises(ValueError, match="Write operations not allowed"):
            await kg.run_cypher("CREATE (n:Test {name: 'x'})")

    async def test_write_query_with_remove_raises(self, kg):
        with pytest.raises(ValueError, match="Write operations not allowed"):
            await kg.run_cypher("MATCH (n) REMOVE n.name")

    async def test_write_query_with_drop_raises(self, kg):
        with pytest.raises(ValueError, match="Write operations not allowed"):
            await kg.run_cypher("DROP CONSTRAINT my_constraint")


# ── find_related_entities ─────────────────────────────────────────────────


class TestFindRelatedEntities:
    async def test_returns_nodes_and_relationships(self, kg, mock_driver):
        _, session = mock_driver

        row = {
            "nodes": [{"name": "Acme"}, {"name": "Bob"}],
            "relationships": [{"type": "WORKS_AT", "from": "Bob", "to": "Acme"}],
        }
        session.run.return_value = _AsyncResultRows([row])

        result = await kg.find_related_entities("Acme", max_hops=2)
        assert "nodes" in result
        assert "relationships" in result
        assert len(result["nodes"]) == 2
        assert len(result["relationships"]) == 1

    async def test_no_results_returns_empty(self, kg, mock_driver):
        _, session = mock_driver
        session.run.return_value = _AsyncResultEmpty()

        result = await kg.find_related_entities("NonExistent")
        assert result == {"nodes": [], "relationships": []}


# ── close ─────────────────────────────────────────────────────────────────


class TestAddMachineEmitsEvent:
    """Verify that add_machine() emits an ENTITY_ADDED event via the DataEventBus."""

    async def test_add_machine_emits_entity_added(self, kg, mock_driver):
        mock_bus = AsyncMock()
        mock_bus.emit = AsyncMock()
        kg.set_event_bus(mock_bus)

        await kg.add_machine(model="PF1-C", category="Packaging", description="Compact line")

        mock_bus.emit.assert_awaited_once()
        event = mock_bus.emit.call_args[0][0]
        assert event.event_type.value == "entity_added"
        assert event.entity_type == "machine"
        assert event.entity_id == "PF1-C"
        assert event.payload["model"] == "PF1-C"
        assert event.payload["category"] == "Packaging"
        assert event.source_store.value == "neo4j"

    async def test_add_machine_works_without_event_bus(self, kg, mock_driver):
        """add_machine() should succeed even when no event bus is configured."""
        await kg.add_machine(model="AM-200", category="Assembly")
        _, session = mock_driver
        session.execute_write.assert_awaited_once()


class TestClose:
    async def test_close_calls_driver_close(self, kg, mock_driver):
        driver, _ = mock_driver
        await kg.close()
        driver.close.assert_awaited_once()

    async def test_context_manager_calls_close(self, kg, mock_driver):
        driver, _ = mock_driver
        async with kg:
            pass
        driver.close.assert_awaited_once()
