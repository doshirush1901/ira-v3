"""Tests for the BaseAgent ReAct (Reason-Act-Observe) loop.

Covers: direct answers, single tool use, multi-tool chains, max-iteration
fallback, tool execution errors, invalid tool names, and dynamic service
injection from context.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.data.models import AgentMessage
from ira.schemas.llm_outputs import ReActDecision, ToolCall


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_settings():
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-test"
    s.llm.anthropic_api_key.get_secret_value.return_value = ""
    s.llm.anthropic_model = "claude-test"
    s.external_apis.api_key.get_secret_value.return_value = ""
    s.app.react_max_iterations = 8
    return s


def _make_mock_llm_client():
    """Create a mock LLMClient with generate_structured and generate_text."""
    client = MagicMock()
    client.generate_structured = AsyncMock()
    client.generate_text = AsyncMock(return_value="")
    client.generate_text_with_fallback = AsyncMock(return_value="")
    client.generate_structured_with_fallback = AsyncMock()
    return client


@pytest.fixture(autouse=True)
def mock_settings():
    settings = _make_settings()
    with patch("ira.config.get_settings", return_value=settings), \
         patch("ira.agents.base_agent.get_settings", return_value=settings):
        yield


@pytest.fixture(autouse=True)
def mock_llm_client():
    """Patch get_llm_client globally so BaseAgent uses our mock."""
    client = _make_mock_llm_client()
    with patch("ira.services.llm_client.get_llm_client", return_value=client), \
         patch("ira.agents.base_agent.get_llm_client", return_value=client):
        yield client


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


def _make_agent(retriever, bus, *, services=None, llm_client=None):
    """Create a Clio agent (concrete subclass) for testing the base loop."""
    from ira.agents.clio import Clio
    agent = Clio(retriever=retriever, bus=bus)
    if llm_client is not None:
        agent._llm = llm_client
    if services:
        agent.inject_services(services)
    return agent


def _setup_reason_sequence(mock_llm_client, decisions: list[ReActDecision]):
    """Configure the mock to return JSON strings for _reason() calls via generate_text_with_fallback."""
    json_responses = []
    for d in decisions:
        obj: dict[str, Any] = {"thought": d.thought}
        if d.final_answer is not None:
            obj["final_answer"] = d.final_answer
        if d.tool_to_use is not None:
            obj["tool_to_use"] = {"name": d.tool_to_use.name, "input": d.tool_to_use.input}
        json_responses.append(json.dumps(obj))
    mock_llm_client.generate_text_with_fallback.side_effect = list(json_responses)


def _setup_forced_answer(mock_llm_client, decisions: list[ReActDecision], forced: str):
    """Configure mock for loops that hit max iterations then force a final answer."""
    json_responses = []
    for d in decisions:
        obj: dict[str, Any] = {"thought": d.thought}
        if d.tool_to_use is not None:
            obj["tool_to_use"] = {"name": d.tool_to_use.name, "input": d.tool_to_use.input}
        json_responses.append(json.dumps(obj))
    json_responses.append(forced)
    mock_llm_client.generate_text_with_fallback.side_effect = list(json_responses)


# ── Direct Answer ─────────────────────────────────────────────────────────


class TestDirectAnswer:
    """Agent answers immediately without using any tools."""

    async def test_direct_answer_returns_final_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="I know the answer already.",
                final_answer="Machinecraft makes industrial machines.",
            ),
        ])

        result = await agent.run("What does Machinecraft do?")

        assert result == "Machinecraft makes industrial machines."

    async def test_direct_answer_completes_in_one_iteration(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Simple question.", final_answer="42"),
        ])

        result = await agent.run("What is the answer?")
        assert agent.state.value == "responding"


# ── Single Tool Use ───────────────────────────────────────────────────────


class TestSingleToolUse:
    """Agent uses one tool, then provides a final answer."""

    async def test_single_tool_call_then_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="I need to search the knowledge base.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "PF1-C specs", "limit": "5"}),
            ),
            ReActDecision(
                thought="I found the specs.",
                final_answer="The PF1-C handles up to 1.2mm steel.",
            ),
        ])

        result = await agent.run("What are PF1-C specs?")

        assert "1.2mm" in result
        mock_retriever.search.assert_awaited_once()

    async def test_tool_result_is_passed_in_scratchpad(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        mock_retriever.search.return_value = [
            {"content": "PF1-C max thickness: 1.2mm", "source": "specs.pdf"},
        ]

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="Search for specs.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "PF1-C"}),
            ),
            ReActDecision(
                thought="Got the specs from the observation.",
                final_answer="PF1-C max thickness is 1.2mm per specs.pdf.",
            ),
        ])

        result = await agent.run("PF1-C specs?")

        assert "1.2mm" in result


# ── Multi-Tool Use ────────────────────────────────────────────────────────


class TestMultiToolUse:
    """Agent chains 2-3 tool calls before answering."""

    async def test_two_tool_calls_then_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus, llm_client=mock_llm_client)
        mock_retriever.search.return_value = [
            {"content": "PF1-C is a panel former", "source": "catalog.pdf"},
        ]

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="First search for PF1-C.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "PF1-C overview"}),
            ),
            ReActDecision(
                thought="Now search for pricing.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "PF1-C pricing"}),
            ),
            ReActDecision(
                thought="I have both overview and pricing.",
                final_answer="PF1-C is a panel former. Contact sales for pricing.",
            ),
        ])

        result = await agent.run("Tell me about PF1-C and its price")

        assert "panel former" in result
        assert mock_retriever.search.await_count == 2

    async def test_three_tool_chain(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus, llm_client=mock_llm_client)

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="Step 1",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "q1"}),
            ),
            ReActDecision(
                thought="Step 2",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "q2"}),
            ),
            ReActDecision(
                thought="Step 3",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "q3"}),
            ),
            ReActDecision(
                thought="Done.",
                final_answer="Comprehensive answer from 3 searches.",
            ),
        ])

        result = await agent.run("Complex multi-part question")

        assert "Comprehensive" in result
        assert mock_retriever.search.await_count == 3


# ── Max Iterations ────────────────────────────────────────────────────────


class TestMaxIterations:
    """Agent hits max_iterations and falls back to _force_final_answer."""

    async def test_max_iterations_forces_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        agent.max_iterations = 3

        tool_decision = ReActDecision(
            thought="Keep searching.",
            tool_to_use=ToolCall(name="search_knowledge", input={"query": "loop"}),
        )
        _setup_forced_answer(mock_llm_client, [tool_decision] * 3, "Synthesised from partial results.")

        result = await agent.run("Infinite loop query")

        assert mock_retriever.search.await_count == 3
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_max_iterations_with_custom_limit(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        agent.max_iterations = 2

        tool_decision = ReActDecision(
            thought="Searching again.",
            tool_to_use=ToolCall(name="search_knowledge", input={"query": "x"}),
        )
        _setup_forced_answer(mock_llm_client, [tool_decision] * 2, "Forced answer after 2 iterations.")

        result = await agent.run("Query that loops")

        assert mock_retriever.search.await_count == 2


# ── Tool Execution Error ──────────────────────────────────────────────────


class TestToolExecutionError:
    """Tool raises an exception; agent continues reasoning."""

    async def test_tool_error_is_caught_and_reported(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        mock_retriever.search.side_effect = RuntimeError("Connection refused")

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="Search the knowledge base.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "test"}),
            ),
            ReActDecision(
                thought="The search failed. I'll answer from what I know.",
                final_answer="I couldn't access the knowledge base, but based on general knowledge...",
            ),
        ])

        result = await agent.run("Test query")

        assert "knowledge base" in result.lower()

    async def test_tool_error_does_not_crash_loop(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        mock_retriever.search.side_effect = [
            RuntimeError("Timeout"),
            [{"content": "Success on retry", "source": "doc.pdf"}],
        ]

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="First search.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "q1"}),
            ),
            ReActDecision(
                thought="Error occurred, try again.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "q1 retry"}),
            ),
            ReActDecision(
                thought="Got it.",
                final_answer="Found the answer on retry.",
            ),
        ])

        result = await agent.run("Retry query")

        assert "retry" in result.lower()


# ── Invalid Tool Name ─────────────────────────────────────────────────────


class TestInvalidToolName:
    """LLM hallucinates a tool name that doesn't exist."""

    async def test_unknown_tool_returns_error_message(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(
                thought="I'll use the database tool.",
                tool_to_use=ToolCall(name="query_database", input={"sql": "SELECT *"}),
            ),
            ReActDecision(
                thought="That tool doesn't exist. I'll use search_knowledge instead.",
                tool_to_use=ToolCall(name="search_knowledge", input={"query": "data"}),
            ),
            ReActDecision(
                thought="Found what I need.",
                final_answer="Here's the data from the knowledge base.",
            ),
        ])

        result = await agent.run("Get database info")

        assert isinstance(result, str)
        assert len(result) > 0

    async def test_execute_tool_returns_unknown_for_bad_name(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        agent._register_default_tools()

        result = await agent._execute_tool("nonexistent_tool", {"param": "value"})
        assert "Unknown tool" in result


# ── Dynamic Service Injection via Context ─────────────────────────────────


class TestDynamicServiceInjection:
    """Services passed in context['services'] are merged into agent._services."""

    async def test_services_from_context_are_injected(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        assert "relationship_memory" not in agent._services

        mock_rel = AsyncMock()
        context = {
            "services": {"relationship_memory": mock_rel},
        }

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Simple answer.", final_answer="Done."),
        ])

        await agent.run("test", context)

        assert agent._services["relationship_memory"] is mock_rel

    async def test_existing_services_not_overwritten(self, mock_retriever, bus, mock_llm_client):
        original_crm = MagicMock()
        agent = _make_agent(mock_retriever, bus, services={"crm": original_crm})

        new_crm = MagicMock()
        context = {"services": {"crm": new_crm}}

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Answer.", final_answer="Done."),
        ])

        await agent.run("test", context)

        assert agent._services["crm"] is original_crm

    async def test_none_services_are_skipped(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        context = {"services": {"goal_manager": None}}

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Answer.", final_answer="Done."),
        ])

        await agent.run("test", context)

        assert "goal_manager" not in agent._services

    async def test_injected_services_enable_new_tools(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        tool_names_before = {t.name for t in agent.tools}

        mock_rel = AsyncMock()
        context = {"services": {"relationship_memory": mock_rel}}

        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Answer.", final_answer="Done."),
        ])

        await agent.run("test", context)

        tool_names_after = {t.name for t in agent.tools}
        assert "check_relationship" in tool_names_after


# ── Default Tool Registration ─────────────────────────────────────────────


class TestDefaultToolRegistration:
    """Verify that default tools register based on available services."""

    async def test_no_services_registers_only_search_knowledge(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}
        assert "search_knowledge" in tool_names
        assert "recall_memory" not in tool_names
        assert "check_relationship" not in tool_names

    async def test_all_services_registers_all_default_tools(self, mock_retriever, bus, mock_llm_client):
        services = {
            "long_term_memory": AsyncMock(),
            "conversation_memory": AsyncMock(),
            "relationship_memory": AsyncMock(),
            "goal_manager": AsyncMock(),
            "pantheon": MagicMock(),
        }
        agent = _make_agent(mock_retriever, bus, services=services)
        agent._register_default_tools()
        tool_names = {t.name for t in agent.tools}

        expected = {
            "search_knowledge", "recall_memory", "store_memory",
            "get_conversation_history", "check_relationship",
            "check_goals", "ask_agent",
        }
        assert expected.issubset(tool_names)

    async def test_register_default_tools_is_idempotent(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        agent._register_default_tools()
        count1 = len(agent.tools)
        agent._register_default_tools()
        count2 = len(agent.tools)
        assert count1 == count2


# ── Unparseable LLM Response ─────────────────────────────────────────────


class TestUnparseableLLMResponse:
    """When structured parsing returns defaults, agent treats it as final answer."""

    async def test_empty_decision_becomes_final_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="Just a plain text answer."),
        ])

        result = await agent.run("Simple question")

        assert isinstance(result, str)
        assert len(result) > 0

    async def test_thought_only_becomes_final_answer(self, mock_retriever, bus, mock_llm_client):
        agent = _make_agent(mock_retriever, bus)
        _setup_reason_sequence(mock_llm_client, [
            ReActDecision(thought="I have the answer directly."),
        ])

        result = await agent.run("Question")

        assert isinstance(result, str)
