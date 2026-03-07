"""Tests for Phase 2: Pantheon — agents, MessageBus, Pantheon orchestrator, and BoardMeeting."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ira.data.models import AgentMessage, BoardMeetingMinutes


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _make_settings():
    """Return a fake Settings object sufficient for BaseAgent / Pantheon."""
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-test"
    s.llm.anthropic_api_key.get_secret_value.return_value = ""
    s.llm.anthropic_model = "claude-test"
    s.external_apis.api_key.get_secret_value.return_value = ""
    return s


@pytest.fixture()
def mock_settings():
    with patch("ira.config.get_settings", return_value=_make_settings()) as m:
        yield m


@pytest.fixture()
def mock_retriever():
    r = AsyncMock()
    r.search = AsyncMock(return_value=[])
    r.search_by_category = AsyncMock(return_value=[])
    r.decompose_and_search = AsyncMock(return_value=[])
    return r


@pytest.fixture()
def bus():
    from ira.message_bus import MessageBus
    return MessageBus()


# ═══════════════════════════════════════════════════════════════════════════════
# MessageBus
# ═══════════════════════════════════════════════════════════════════════════════

class TestMessageBus:
    async def test_subscribe_and_dispatch(self, bus: "MessageBus"):
        received: list[AgentMessage] = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        bus.subscribe("clio", handler)
        await bus.start()

        await bus.send("athena", "clio", "hello")
        await asyncio.sleep(0.05)

        await bus.stop()
        assert len(received) == 1
        assert received[0].from_agent == "athena"
        assert received[0].query == "hello"

    async def test_broadcast_reaches_broadcast_subscribers(self, bus: "MessageBus"):
        received: list[AgentMessage] = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        bus.subscribe_broadcast(handler)
        await bus.start()

        await bus.broadcast("athena", "all-hands topic")
        await asyncio.sleep(0.05)

        await bus.stop()
        assert len(received) == 1
        assert received[0].query == "all-hands topic"

    async def test_message_log_records_all_messages(self, bus: "MessageBus"):
        bus.subscribe("clio", AsyncMock())
        await bus.start()

        await bus.send("athena", "clio", "q1")
        await bus.send("athena", "clio", "q2")
        await asyncio.sleep(0.05)

        await bus.stop()
        assert len(bus.message_log) == 2

    async def test_pending_count(self, bus: "MessageBus"):
        assert bus.pending_count == 0

    async def test_handler_exception_does_not_crash_bus(self, bus: "MessageBus"):
        async def bad_handler(msg: AgentMessage) -> None:
            raise RuntimeError("boom")

        bus.subscribe("clio", bad_handler)
        await bus.start()

        await bus.send("athena", "clio", "crash me")
        await asyncio.sleep(0.05)

        await bus.stop()
        assert len(bus.message_log) == 1

    async def test_start_is_idempotent(self, bus: "MessageBus"):
        await bus.start()
        await bus.start()
        await bus.stop()

    async def test_send_builds_agent_message(self, bus: "MessageBus"):
        received: list[AgentMessage] = []
        bus.subscribe("plutus", lambda m: received.append(m) or asyncio.sleep(0))
        await bus.start()
        await bus.send("athena", "plutus", "revenue?", {"period": "Q1"})
        await asyncio.sleep(0.05)
        await bus.stop()
        assert received[0].context == {"period": "Q1"}


# ═══════════════════════════════════════════════════════════════════════════════
# BaseAgent
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseAgent:
    async def test_call_llm_openai(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio

        agent = Clio(retriever=mock_retriever, bus=bus)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "test answer"}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await agent.call_llm("system", "user")

        assert result == "test answer"

    async def test_call_llm_handles_missing_key_gracefully(self, mock_retriever, bus):
        s = _make_settings()
        s.llm.openai_api_key.get_secret_value.return_value = ""
        with patch("ira.config.get_settings", return_value=s):
            from ira.agents.clio import Clio
            agent = Clio(retriever=mock_retriever, bus=bus)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.HTTPError("401")):
            result = await agent.call_llm("system", "user")
        assert "failed" in result.lower()

    async def test_search_knowledge_delegates_to_retriever(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio
        agent = Clio(retriever=mock_retriever, bus=bus)

        mock_retriever.search.return_value = [{"content": "fact", "source": "doc.pdf"}]
        results = await agent.search_knowledge("test query")
        mock_retriever.search.assert_awaited_once()
        assert len(results) == 1

    async def test_format_context_empty(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio
        agent = Clio(retriever=mock_retriever, bus=bus)
        assert "No relevant context" in agent._format_context([])

    async def test_format_context_with_results(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio
        agent = Clio(retriever=mock_retriever, bus=bus)
        ctx = agent._format_context([{"content": "hello", "source": "s.pdf"}])
        assert "hello" in ctx
        assert "s.pdf" in ctx

    async def test_parse_json_response_strips_fences(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio
        agent = Clio(retriever=mock_retriever, bus=bus)
        raw = '```json\n{"key": "value"}\n```'
        parsed = agent._parse_json_response(raw)
        assert parsed == {"key": "value"}

    async def test_send_to_publishes_on_bus(self, mock_settings, mock_retriever, bus):
        from ira.agents.clio import Clio
        agent = Clio(retriever=mock_retriever, bus=bus)

        received: list[AgentMessage] = []
        bus.subscribe("prometheus", lambda m: received.append(m) or asyncio.sleep(0))
        await bus.start()
        await agent.send_to("prometheus", "pipeline update?")
        await asyncio.sleep(0.05)
        await bus.stop()
        assert received[0].from_agent == "clio"


# ═══════════════════════════════════════════════════════════════════════════════
# Individual Agents (handle method)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentHandle:
    """Verify that each agent's handle() calls the LLM and returns a string."""

    @pytest.fixture(autouse=True)
    def _patch(self, mock_settings, mock_retriever, bus):
        self.retriever = mock_retriever
        self.bus = bus

    def _mock_llm(self, response_text: str = "agent response"):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": response_text}}],
        }
        mock_resp.raise_for_status = MagicMock()
        return patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp)

    async def test_clio_handle(self):
        from ira.agents.clio import Clio
        agent = Clio(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Clio's research"):
            result = await agent.handle("What is PF1-C?")
        assert result == "Clio's research"

    async def test_prometheus_handle(self):
        from ira.agents.prometheus import Prometheus
        agent = Prometheus(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Pipeline looks strong"):
            result = await agent.handle("Show pipeline")
        assert "Pipeline" in result

    async def test_athena_routes(self):
        from ira.agents.athena import Athena
        agent = Athena(retriever=self.retriever, bus=self.bus)
        react_response = json.dumps({
            "thought": "This is a knowledge question. I should delegate to Clio.",
            "final_answer": "Based on our catalog, the PF1-C is our flagship machine.",
        })
        with self._mock_llm(react_response):
            result = await agent.handle("What is our best machine?")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_athena_synthesises(self):
        from ira.agents.athena import Athena
        agent = Athena(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Combined answer"):
            result = await agent.handle(
                "complex query",
                {"agent_responses": {"clio": "fact A", "prometheus": "deal B"}},
            )
        assert result == "Combined answer"

    async def test_delphi_classifies_email(self):
        from ira.agents.delphi import Delphi
        agent = Delphi(retriever=self.retriever, bus=self.bus)
        react_response = json.dumps({
            "thought": "This is a pricing inquiry. I should classify it.",
            "final_answer": "Classification: QUOTE_REQUEST, urgency HIGH. Suggested agent: prometheus.",
        })
        with self._mock_llm(react_response):
            result = await agent.handle("I need pricing for PF1-C")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_sphinx_evaluates_clarity(self):
        from ira.agents.sphinx import Sphinx
        agent = Sphinx(retriever=self.retriever, bus=self.bus)
        react_response = json.dumps({
            "thought": "The query is clear and specific.",
            "final_answer": "The query is clear. No clarification needed.",
        })
        with self._mock_llm(react_response):
            result = await agent.handle("Show me PF1-C specs")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_vera_checks_facts(self):
        from ira.agents.vera import Vera
        agent = Vera(retriever=self.retriever, bus=self.bus)
        react_response = json.dumps({
            "thought": "I need to verify this claim against the knowledge base.",
            "final_answer": "VERIFIED: PF1-C max thickness is 1.2mm based on specs.pdf.",
        })
        with self._mock_llm(react_response):
            result = await agent.handle("PF1-C handles 1.2mm steel")
        assert "VERIFIED" in result

    async def test_calliope_drafts(self):
        from ira.agents.calliope import Calliope
        agent = Calliope(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Dear Customer, ..."):
            result = await agent.handle(
                "Draft follow-up email",
                {"draft_type": "email", "tone": "formal"},
            )
        assert "Dear" in result

    async def test_iris_handle(self):
        from ira.agents.iris import Iris
        agent = Iris(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Industry report: ..."):
            result = await agent.handle("construction industry trends")
        assert "Industry" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Untested Agents — handle() and tool registration
# ═══════════════════════════════════════════════════════════════════════════════

class TestUntestedAgents:
    """Tests for the 16 agents that previously had no test coverage.

    Each test verifies:
    - The agent can be instantiated
    - handle() returns a string
    - Agent-specific tools are registered when services are available
    """

    @pytest.fixture(autouse=True)
    def _patch(self, mock_settings, mock_retriever, bus):
        self.retriever = mock_retriever
        self.bus = bus

    def _mock_llm(self, response_text: str = "agent response"):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": response_text}}],
        }
        mock_resp.raise_for_status = MagicMock()
        return patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp)

    # ── Alexandros ────────────────────────────────────────────────────

    async def test_alexandros_handle(self):
        from ira.agents.alexandros import Alexandros
        agent = Alexandros(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Archive contains 700+ documents."):
            result = await agent.handle("What's in the archive?")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_alexandros_registers_archive_tools(self):
        from ira.agents.alexandros import Alexandros
        agent = Alexandros(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "search_archive" in tool_names

    # ── Arachne ───────────────────────────────────────────────────────

    async def test_arachne_handle(self):
        from ira.agents.arachne import Arachne
        agent = Arachne(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Newsletter draft ready."):
            result = await agent.handle("Draft this week's newsletter")
        assert isinstance(result, str)

    async def test_arachne_registers_content_tools(self):
        from ira.agents.arachne import Arachne
        agent = Arachne(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "draft_newsletter" in tool_names

    # ── Asclepius ─────────────────────────────────────────────────────

    async def test_asclepius_handle(self):
        from ira.agents.asclepius import Asclepius
        agent = Asclepius(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Quality dashboard: 0 open items."):
            result = await agent.handle("Show quality dashboard")
        assert isinstance(result, str)

    async def test_asclepius_registers_quality_tools(self):
        from ira.agents.asclepius import Asclepius
        agent = Asclepius(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "log_punch_item" in tool_names
        assert "quality_dashboard" in tool_names

    # ── Atlas ─────────────────────────────────────────────────────────

    async def test_atlas_handle(self, tmp_path):
        from ira.agents.atlas import Atlas
        agent = Atlas(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Project Alpha is on track."), \
             patch("ira.agents.atlas._DB_PATH", tmp_path / "atlas.db"):
            result = await agent.handle("Status of Project Alpha")
        assert isinstance(result, str)

    async def test_atlas_registers_project_tools(self):
        from ira.agents.atlas import Atlas
        agent = Atlas(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "get_project_status" in tool_names
        assert "log_project_event" in tool_names
        assert "get_overdue_milestones" in tool_names

    # ── Cadmus ────────────────────────────────────────────────────────

    async def test_cadmus_handle(self):
        from ira.agents.cadmus import Cadmus
        agent = Cadmus(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Case study: Project Alpha delivered 30% efficiency gains."):
            result = await agent.handle("Build a case study for Project Alpha")
        assert isinstance(result, str)

    async def test_cadmus_registers_content_tools(self):
        from ira.agents.cadmus import Cadmus
        agent = Cadmus(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "find_case_studies" in tool_names
        assert "draft_linkedin_post" in tool_names

    # ── Chiron ────────────────────────────────────────────────────────

    async def test_chiron_handle(self):
        from ira.agents.chiron import Chiron
        agent = Chiron(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Sales coaching: lead with value proposition."):
            result = await agent.handle("Give me coaching notes for cold outreach")
        assert isinstance(result, str)

    async def test_chiron_registers_training_tools(self):
        from ira.agents.chiron import Chiron
        agent = Chiron(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "log_pattern" in tool_names
        assert "get_coaching_notes" in tool_names

    # ── Hephaestus ────────────────────────────────────────────────────

    async def test_hephaestus_handle(self):
        from ira.agents.hephaestus import Hephaestus
        agent = Hephaestus(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("PF1-C: max 1.2mm, 30m/min line speed."):
            result = await agent.handle("What are PF1-C machine specs?")
        assert isinstance(result, str)

    async def test_hephaestus_registers_production_tools(self):
        from ira.agents.hephaestus import Hephaestus
        agent = Hephaestus(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "lookup_machine_spec" in tool_names
        assert "search_manuals" in tool_names

    # ── Hera ──────────────────────────────────────────────────────────

    async def test_hera_handle(self):
        from ira.agents.hera import Hera
        agent = Hera(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Vendor ABC: lead time 6 weeks, reliability 95%."):
            result = await agent.handle("Check vendor ABC status")
        assert isinstance(result, str)

    async def test_hera_registers_vendor_tools(self):
        from ira.agents.hera import Hera
        agent = Hera(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "check_vendor_status" in tool_names
        assert "get_component_lead_time" in tool_names

    # ── Hermes ────────────────────────────────────────────────────────

    async def test_hermes_handle(self):
        from ira.agents.hermes import Hermes
        agent = Hermes(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Drip campaign drafted for MENA region."):
            result = await agent.handle("Create a drip campaign for MENA leads")
        assert isinstance(result, str)

    async def test_hermes_registers_marketing_tools(self):
        from ira.agents.hermes import Hermes
        agent = Hermes(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "draft_email" in tool_names
        assert "create_drip_sequence" in tool_names

    # ── Mnemosyne ─────────────────────────────────────────────────────

    async def test_mnemosyne_handle(self):
        from ira.agents.mnemosyne import Mnemosyne
        agent = Mnemosyne(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Memory stored: customer prefers email communication."):
            result = await agent.handle("Remember that John prefers email")
        assert isinstance(result, str)

    async def test_mnemosyne_registers_memory_tools_with_services(self):
        from ira.agents.mnemosyne import Mnemosyne
        agent = Mnemosyne(retriever=self.retriever, bus=self.bus)
        agent.inject_services({
            "long_term_memory": AsyncMock(),
            "episodic_memory": AsyncMock(),
            "relationship_memory": AsyncMock(),
            "goal_manager": AsyncMock(),
        })
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "recall_long_term" in tool_names
        assert "store_long_term" in tool_names
        assert "get_episodic_memory" in tool_names
        assert "get_relationship" in tool_names
        assert "get_goals" in tool_names

    # ── Nemesis ───────────────────────────────────────────────────────

    async def test_nemesis_handle(self):
        from ira.agents.nemesis import Nemesis
        agent = Nemesis(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Training cycle complete: 3 corrections ingested."):
            result = await agent.handle("Run a training cycle")
        assert isinstance(result, str)

    async def test_nemesis_registers_training_tools(self):
        from ira.agents.nemesis import Nemesis
        agent = Nemesis(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "ingest_correction" in tool_names
        assert "get_training_stats" in tool_names

    # ── Plutus ────────────────────────────────────────────────────────

    async def test_plutus_handle(self):
        from ira.agents.plutus import Plutus
        agent = Plutus(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Revenue analysis: Q1 up 15% YoY."):
            result = await agent.handle("What's our revenue trend?")
        assert isinstance(result, str)

    async def test_plutus_registers_finance_tools_with_services(self):
        from ira.agents.plutus import Plutus
        agent = Plutus(retriever=self.retriever, bus=self.bus)
        agent.inject_services({
            "pricing_engine": AsyncMock(),
            "crm": AsyncMock(),
            "quotes": AsyncMock(),
            "pantheon": MagicMock(),
        })
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "estimate_price" in tool_names
        assert "search_financial_docs" in tool_names
        assert "ask_prometheus" in tool_names

    # ── Quotebuilder ──────────────────────────────────────────────────

    async def test_quotebuilder_handle(self):
        from ira.agents.quotebuilder import Quotebuilder
        agent = Quotebuilder(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Quote generated: PF1-C, $45,000 USD."):
            result = await agent.handle("Generate a quote for PF1-C")
        assert isinstance(result, str)

    async def test_quotebuilder_registers_quote_tools(self):
        from ira.agents.quotebuilder import Quotebuilder
        agent = Quotebuilder(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "lookup_machine_specs" in tool_names
        assert "generate_quote_document" in tool_names

    # ── Sophia ────────────────────────────────────────────────────────

    async def test_sophia_handle(self):
        from ira.agents.sophia import Sophia
        agent = Sophia(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Reflection: response quality was high, tone matched."):
            result = await agent.handle("Reflect on the last interaction")
        assert isinstance(result, str)

    async def test_sophia_registers_reflection_tools(self):
        from ira.agents.sophia import Sophia
        agent = Sophia(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "suggest_improvement" in tool_names

    # ── Themis ────────────────────────────────────────────────────────

    async def test_themis_handle(self):
        from ira.agents.themis import Themis
        agent = Themis(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Employee count: 45. Engineering: 20."):
            result = await agent.handle("How many employees do we have?")
        assert isinstance(result, str)

    async def test_themis_registers_hr_tools(self):
        from ira.agents.themis import Themis
        agent = Themis(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "lookup_employee" in tool_names
        assert "search_hr_policies" in tool_names

    # ── Tyche ─────────────────────────────────────────────────────────

    async def test_tyche_handle(self):
        from ira.agents.tyche import Tyche
        agent = Tyche(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("Forecast: 70% probability of closing $2M in Q2."):
            result = await agent.handle("Forecast Q2 revenue")
        assert isinstance(result, str)

    async def test_tyche_registers_forecast_tools(self):
        from ira.agents.tyche import Tyche
        agent = Tyche(retriever=self.retriever, bus=self.bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "get_pipeline_data" in tool_names

    # ── Prometheus tool registration with services ────────────────────

    async def test_prometheus_registers_crm_tools_with_services(self):
        from ira.agents.prometheus import Prometheus
        agent = Prometheus(retriever=self.retriever, bus=self.bus)
        agent.inject_services({
            "crm": AsyncMock(),
            "quotes": AsyncMock(),
            "pantheon": MagicMock(),
        })
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "search_contacts" in tool_names
        assert "get_deal" in tool_names
        assert "get_pipeline_summary" in tool_names
        assert "get_quote_analytics" in tool_names
        assert "ask_quotebuilder" in tool_names

    # ── Atlas tool registration with services ─────────────────────────

    async def test_atlas_registers_delegation_tool_with_pantheon(self):
        from ira.agents.atlas import Atlas
        agent = Atlas(retriever=self.retriever, bus=self.bus)
        agent.inject_services({"pantheon": MagicMock()})
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "ask_hephaestus" in tool_names


# ═══════════════════════════════════════════════════════════════════════════════
# Pantheon orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class TestPantheon:
    @pytest.fixture()
    def pantheon(self, mock_settings, mock_retriever, bus):
        from ira.pantheon import Pantheon
        return Pantheon(retriever=mock_retriever, bus=bus)

    async def test_all_agents_registered(self, pantheon):
        assert "athena" in pantheon.agents
        assert "clio" in pantheon.agents
        assert "prometheus" in pantheon.agents
        assert len(pantheon.agents) >= 17

    async def test_get_agent(self, pantheon):
        assert pantheon.get_agent("clio") is not None
        assert pantheon.get_agent("nonexistent") is None

    async def test_process_deterministic_route(self, pantheon):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Pipeline is healthy"}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await pantheon.process("Show me the sales pipeline and active deals")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_process_llm_route_fallback(self, pantheon):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "General answer"}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await pantheon.process("Tell me something interesting")
        assert isinstance(result, str)

    async def test_board_meeting(self, pantheon):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "We agree", "action_items": ["do X"]}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            minutes = await pantheon.board_meeting(
                "Q1 strategy", participants=["clio", "prometheus"],
            )
        assert isinstance(minutes, BoardMeetingMinutes)
        assert "athena" in minutes.participants
        assert minutes.topic == "Q1 strategy"

    async def test_board_meeting_excludes_athena_from_contributors(self, pantheon):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "synthesis"}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            minutes = await pantheon.board_meeting("topic", participants=["athena", "clio"])
        assert "athena" in minutes.participants
        assert "clio" in minutes.contributions


# ═══════════════════════════════════════════════════════════════════════════════
# BoardMeeting system
# ═══════════════════════════════════════════════════════════════════════════════

class TestBoardMeetingSystem:
    @pytest.fixture()
    def board(self, mock_settings):
        from ira.systems.board_meeting import BoardMeeting

        async def fake_handler(agent_name: str, topic: str) -> str:
            return f"{agent_name} says: noted on '{topic[:20]}'"

        return BoardMeeting(agent_handler=fake_handler)

    async def test_run_meeting_returns_minutes(self, board):
        minutes = await board.run_meeting("Budget review", ["clio", "plutus"])

        assert minutes.topic == "Budget review"
        assert "clio" in minutes.contributions
        assert "plutus" in minutes.contributions
        assert "athena" in minutes.participants
        assert isinstance(minutes.synthesis, str)
        assert len(minutes.synthesis) > 0

    async def test_run_meeting_default_participants(self, board):
        minutes = await board.run_meeting("General topic")

        assert len(minutes.contributions) == 8
        assert "clio" in minutes.contributions
        assert "prometheus" in minutes.contributions

    async def test_run_meeting_custom_participants(self, board):
        minutes = await board.run_meeting(
            "Pricing strategy", ["plutus", "prometheus", "hermes"],
        )

        assert "plutus" in minutes.contributions
        assert "prometheus" in minutes.contributions
        assert "hermes" in minutes.contributions

    async def test_meeting_synthesis_uses_athena(self, board):
        minutes = await board.run_meeting("test", ["clio"])

        assert "athena" in minutes.participants
        assert "athena says:" in minutes.synthesis

    async def test_meeting_handler_exception_is_caught(self, mock_settings):
        from ira.systems.board_meeting import BoardMeeting

        async def failing_handler(name: str, topic: str) -> str:
            if name == "clio":
                raise RuntimeError("Agent crashed")
            return f"{name}: ok"

        board = BoardMeeting(agent_handler=failing_handler)
        minutes = await board.run_meeting("test", ["clio", "plutus"])

        assert "error" in minutes.contributions["clio"].lower()
        assert minutes.contributions["plutus"] == "plutus: ok"
