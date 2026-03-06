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
        routing_json = json.dumps({"agents": ["clio"], "reasoning": "research"})
        with self._mock_llm(routing_json):
            result = await agent.handle("What is our best machine?")
        assert "clio" in result

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
        classification = json.dumps({
            "intent": "QUOTE_REQUEST", "urgency": "HIGH",
            "suggested_agent": "prometheus", "summary": "Wants a quote",
        })
        with self._mock_llm(classification):
            result = await agent.handle("I need pricing for PF1-C")
        parsed = json.loads(result)
        assert parsed["intent"] == "QUOTE_REQUEST"

    async def test_sphinx_evaluates_clarity(self):
        from ira.agents.sphinx import Sphinx
        agent = Sphinx(retriever=self.retriever, bus=self.bus)
        with self._mock_llm('{"clear": true, "query": "test"}'):
            result = await agent.handle("Show me PF1-C specs")
        assert "clear" in result

    async def test_vera_checks_facts(self):
        from ira.agents.vera import Vera
        agent = Vera(retriever=self.retriever, bus=self.bus)
        with self._mock_llm("VERIFIED: PF1-C max thickness is 1.2mm"):
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
    def board(self, mock_settings, tmp_path):
        from ira.systems.board_meeting import BoardMeeting

        async def fake_handler(agent_name: str, topic: str) -> str:
            return f"{agent_name} says: noted on '{topic[:20]}'"

        return BoardMeeting(
            agent_handler=fake_handler,
            db_path=str(tmp_path / "meetings.db"),
        )

    async def test_run_meeting_returns_minutes(self, board):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "All aligned", "action_items": ["A1"]}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            minutes = await board.run_meeting("Budget review", ["clio", "plutus"])

        assert minutes.topic == "Budget review"
        assert "clio" in minutes.contributions
        assert "plutus" in minutes.contributions
        assert minutes.synthesis == "All aligned"
        assert minutes.action_items == ["A1"]

    async def test_run_meeting_default_participants(self, board):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "ok", "action_items": []}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            minutes = await board.run_meeting("General topic")

        assert len(minutes.contributions) == 6

    async def test_run_focused_meeting(self, board):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "focused", "action_items": []}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            minutes = await board.run_focused_meeting(
                "Pricing strategy", "plutus", ["prometheus", "hermes"],
            )

        assert "plutus" in minutes.contributions
        assert "prometheus" in minutes.contributions

    async def test_get_past_meetings(self, board):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "ok", "action_items": []}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            await board.run_meeting("Topic A", ["clio"])
            await board.run_meeting("Topic B", ["clio"])

        past = await board.get_past_meetings()
        assert len(past) == 2
        assert past[0].topic == "Topic B"

    async def test_get_past_meetings_with_filter(self, board):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"synthesis": "ok", "action_items": []}'}}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            await board.run_meeting("Budget review", ["clio"])
            await board.run_meeting("Sales strategy", ["clio"])

        past = await board.get_past_meetings(topic_filter="Budget")
        assert len(past) == 1
        assert "Budget" in past[0].topic

    async def test_meeting_without_llm_key(self, tmp_path):
        s = _make_settings()
        s.llm.openai_api_key.get_secret_value.return_value = ""

        async def handler(name: str, topic: str) -> str:
            return f"{name}: ok"

        with patch("ira.config.get_settings", return_value=s):
            from ira.systems.board_meeting import BoardMeeting
            board = BoardMeeting(
                agent_handler=handler,
                db_path=str(tmp_path / "m.db"),
            )

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.HTTPError("401")):
                minutes = await board.run_meeting("test", ["clio"])

        assert "failed" in minutes.synthesis.lower()
