"""Behavior tests for required-skill wiring in priority agents."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.message_bus import MessageBus


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.app.react_max_iterations = 3
    s.app.max_delegation_depth = 5
    s.firecrawl.api_key.get_secret_value.return_value = ""
    s.search.tavily_api_key.get_secret_value.return_value = ""
    s.search.serper_api_key.get_secret_value.return_value = ""
    s.search.searchapi_api_key.get_secret_value.return_value = ""
    s.external_apis.api_key.get_secret_value.return_value = ""
    return s


@pytest.fixture()
def retriever() -> AsyncMock:
    r = AsyncMock()
    r.search = AsyncMock(return_value=[])
    r.search_by_category = AsyncMock(return_value=[])
    return r


@pytest.fixture()
def bus() -> MessageBus:
    return MessageBus()


@pytest.fixture()
def mock_llm() -> MagicMock:
    client = MagicMock()
    client.generate_text_with_fallback = AsyncMock(return_value="ok")
    client.generate_text = AsyncMock(return_value="ok")
    return client


@pytest.fixture(autouse=True)
def _patch_base(mock_llm: MagicMock):
    with patch("ira.agents.base_agent.get_llm_client", return_value=mock_llm), patch(
        "ira.agents.base_agent.get_settings",
        return_value=_make_settings(),
    ):
        yield


class TestRequiredSkillBehaviors:
    async def test_hera_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.hera import Hera

        agent = Hera(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="risk-ok")) as mock_use:
            result = await agent._tool_evaluate_vendor_risk("Acme Supplies", "late shipments")
        assert result == "risk-ok"
        mock_use.assert_awaited_once()

    async def test_hera_missing_vendor_db_fallback(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.hera import Hera

        agent = Hera(retriever=retriever, bus=bus)
        result = await agent._tool_list_vendors()
        assert "not available" in result.lower()

    async def test_asclepius_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.asclepius import Asclepius

        agent = Asclepius(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="triaged")) as mock_use:
            out = await agent._tool_triage_punch_list('[{"id": 1, "severity": "MAJOR"}]')
        assert out == "triaged"
        mock_use.assert_awaited_once()

    async def test_athena_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.athena import Athena

        agent = Athena(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="governed")) as mock_use:
            out = await agent._tool_run_governance_check("draft response", "external")
        assert out == "governed"
        mock_use.assert_awaited_once()

    async def test_athena_missing_immune_fallback(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.athena import Athena

        agent = Athena(retriever=retriever, bus=bus)
        out = await agent._tool_system_health()
        assert "not available" in out.lower()

    async def test_sphinx_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.sphinx import Sphinx

        agent = Sphinx(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="checked")) as mock_use:
            out = await agent._tool_run_governance_check("clarification text")
        assert out == "checked"
        mock_use.assert_awaited_once()

    async def test_vera_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.vera import Vera

        agent = Vera(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="audited")) as mock_use:
            out = await agent._tool_audit_decision_log("decision", "evidence")
        assert out == "audited"
        mock_use.assert_awaited_once()

    async def test_vera_missing_pantheon_fallback(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.vera import Vera

        agent = Vera(retriever=retriever, bus=bus)
        out = await agent._tool_ask_iris("verify this claim")
        assert "not available" in out.lower()

    async def test_mnemon_required_skill_invocation(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.mnemon import Mnemon

        agent = Mnemon(retriever=retriever, bus=bus)
        with patch.object(agent, "use_skill", AsyncMock(return_value="consistent")) as mock_use:
            out = await agent._tool_validate_correction_consistency("statement")
        assert out == "consistent"
        mock_use.assert_awaited_once()

    async def test_mnemon_graceful_lookup_fallback(self, retriever: AsyncMock, bus: MessageBus):
        from ira.agents.mnemon import Mnemon

        agent = Mnemon(retriever=retriever, bus=bus)
        out = await agent._tool_lookup_correction("nonexistent entity")
        assert "no correction found" in out.lower()
