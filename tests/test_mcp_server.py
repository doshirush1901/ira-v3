"""Tests for the MCP server tool functions.

Validates that each MCP tool correctly wraps its underlying service,
returns valid JSON on success, handles missing services gracefully,
and catches exceptions.

Run with::

    poetry run pytest tests/test_mcp_server.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ira.interfaces.mcp_server as mcp_mod
from ira.pipeline_loop import AgentLoop, Plan, Phase, PhaseResult, PhaseStatus, LoopDecision


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _skip_init(monkeypatch):
    """Bypass _ensure_initialized for all tests."""
    monkeypatch.setattr(mcp_mod, "_initialized", True)


@pytest.fixture()
def mock_pipeline(monkeypatch):
    pipeline = AsyncMock()
    pipeline.process_request = AsyncMock(return_value=("Pipeline response.", ["clio", "prometheus"]))
    monkeypatch.setattr(mcp_mod, "_pipeline", pipeline)
    return pipeline


@pytest.fixture()
def mock_retriever(monkeypatch):
    retriever = AsyncMock()
    retriever.search = AsyncMock(return_value=[
        {"content": "Machine specs for PF1", "score": 0.95, "source": "specs.pdf", "source_type": "pdf"},
    ])
    monkeypatch.setattr(mcp_mod, "_retriever", retriever)
    return retriever


@pytest.fixture()
def mock_crm(monkeypatch):
    crm = AsyncMock()
    crm.search_contacts = AsyncMock(return_value=[
        {"name": "John Doe", "email": "john@acme.com", "company_name": "Acme Corp", "role": "CEO"},
    ])
    crm.list_companies = AsyncMock(return_value=[])
    crm.get_pipeline_summary = AsyncMock(return_value={"total_deals": 5, "total_value": 500000})
    deal_data = {
        "id": "deal-1", "title": "PF1 for Acme", "value": 100000, "stage": "proposal",
        "contact_id": "c-1", "machine_model": "PF1", "notes": "Hot lead",
        "created_at": datetime(2025, 1, 1), "updated_at": datetime(2025, 6, 1),
        "expected_close_date": None, "actual_close_date": None, "currency": "USD",
    }
    deal_mock = MagicMock(**deal_data)
    deal_mock.model_dump = MagicMock(return_value=deal_data)
    crm.get_deal = AsyncMock(return_value=deal_mock)
    crm.list_deals = AsyncMock(return_value=[])
    contact_data = {
        "id": "c-new", "name": "Jane Smith", "email": "jane@corp.com", "role": "VP",
        "created_at": datetime(2025, 1, 1),
    }
    contact_mock = MagicMock(**contact_data)
    contact_mock.model_dump = MagicMock(return_value=contact_data)
    crm.create_contact = AsyncMock(return_value=contact_mock)
    updated_deal_data = {
        "id": "deal-1", "title": "PF1 for Acme", "value": 120000, "stage": "negotiation",
        "notes": "Updated", "created_at": datetime(2025, 1, 1), "updated_at": datetime(2025, 6, 1),
        "contact_id": "c-1", "machine_model": "PF1",
        "expected_close_date": None, "actual_close_date": None, "currency": "USD",
    }
    updated_deal_mock = MagicMock(**updated_deal_data)
    updated_deal_mock.model_dump = MagicMock(return_value=updated_deal_data)
    crm.update_deal = AsyncMock(return_value=updated_deal_mock)
    crm.get_stale_leads = AsyncMock(return_value=[
        {"name": "Old Lead", "email": "old@co.com", "days_since_activity": 30},
    ])
    monkeypatch.setattr(mcp_mod, "_crm", crm)
    return crm


@pytest.fixture()
def mock_pantheon(monkeypatch):
    pantheon = MagicMock()

    agent = AsyncMock()
    agent.handle = AsyncMock(return_value="Agent response.")
    agent.role = "Test Role"
    agent.description = "Test agent"
    agent.name = "test_agent"
    agent.web_search = AsyncMock(return_value=[
        {"title": "Result 1", "url": "https://example.com", "snippet": "A snippet"},
    ])
    agent.scrape_url = AsyncMock(return_value="# Page Content\nSome markdown text.")

    pantheon.get_agent = MagicMock(return_value=agent)
    pantheon.agents = {"test_agent": agent}

    monkeypatch.setattr(mcp_mod, "_pantheon", pantheon)
    return pantheon


@pytest.fixture()
def mock_email_processor(monkeypatch):
    ep = AsyncMock()
    email = MagicMock()
    email.model_dump = MagicMock(return_value={
        "id": "msg-1",
        "from_address": "sender@co.com",
        "to_address": "ira@machinecraft.com",
        "subject": "Quote request",
        "body": "Please send a quote.",
        "received_at": "2025-06-01T10:00:00",
        "thread_id": "thread-1",
        "labels": ["INBOX"],
    })
    ep.search_emails = AsyncMock(return_value=[email])
    ep.get_thread = AsyncMock(return_value=[email, email])
    monkeypatch.setattr(mcp_mod, "_email_processor", ep)
    return ep


@pytest.fixture()
def mock_long_term_memory(monkeypatch):
    ltm = AsyncMock()
    ltm.search = AsyncMock(return_value=[
        {"id": "m-1", "memory": "PF1 lead time is 12 weeks", "score": 0.9, "metadata": {}, "created_at": "2025-01-01"},
    ])
    ltm.store = AsyncMock(return_value=[{"id": "m-new"}])
    monkeypatch.setattr(mcp_mod, "_long_term_memory", ltm)
    return ltm


@pytest.fixture()
def mock_conversation_memory(monkeypatch):
    cm = AsyncMock()
    cm.get_history = AsyncMock(return_value=[
        {"role": "user", "content": "What is PF1?", "timestamp": "2025-06-01T10:00:00"},
        {"role": "assistant", "content": "PF1 is a press.", "timestamp": "2025-06-01T10:00:05"},
    ])
    monkeypatch.setattr(mcp_mod, "_conversation_memory", cm)
    return cm


@pytest.fixture()
def mock_relationship_memory(monkeypatch):
    rm = AsyncMock()
    rel = MagicMock()
    rel.model_dump = MagicMock(return_value={
        "contact_id": "john_doe",
        "warmth_level": "WARM",
        "interaction_count": 15,
        "memorable_moments": ["Visited factory in Jan"],
        "learned_preferences": {"communication": "email"},
    })
    rm.get_relationship = AsyncMock(return_value=rel)
    monkeypatch.setattr(mcp_mod, "_relationship_memory", rm)
    return rm


@pytest.fixture()
def mock_goal_manager(monkeypatch):
    gm = AsyncMock()
    goal = MagicMock()
    goal.model_dump = MagicMock(return_value={
        "id": "g-1",
        "goal_type": "QUOTE_FOLLOW_UP",
        "contact_id": "john_doe",
        "status": "ACTIVE",
        "required_slots": {"machine_model": "PF1"},
        "progress": 0.5,
    })
    gm.get_active_goal = AsyncMock(return_value=goal)
    monkeypatch.setattr(mcp_mod, "_goal_manager", gm)
    return gm


@pytest.fixture()
def mock_knowledge_graph(monkeypatch):
    kg = AsyncMock()
    kg.find_related_entities = AsyncMock(return_value={
        "nodes": [{"name": "Acme Corp", "type": "Company"}],
        "relationships": [{"from": "John Doe", "to": "Acme Corp", "type": "WORKS_AT"}],
    })
    kg.find_company_contacts = AsyncMock(return_value=[
        {"name": "John Doe", "email": "john@acme.com", "role": "CEO"},
    ])
    kg.find_company_quotes = AsyncMock(return_value=[
        {"quote_id": "q-1", "value": 100000, "date": "2025-01-01", "status": "sent", "machine": "PF1"},
    ])
    monkeypatch.setattr(mcp_mod, "_knowledge_graph", kg)
    return kg


@pytest.fixture()
def mock_task_orchestrator(monkeypatch):
    orchestrator = AsyncMock()
    orchestrator.get_task_state = AsyncMock(return_value={"task_id": "t1", "status": "executing"})
    orchestrator.abort_task = AsyncMock(return_value=True)
    orchestrator.list_tasks = AsyncMock(return_value=[
        {"task_id": "t2", "status": "complete"},
        {"task_id": "t1", "status": "executing"},
    ])
    orchestrator.get_task_events = AsyncMock(return_value=[
        {"type": "task_created"},
        {"type": "phase_started", "phase_index": 1},
    ])
    orchestrator.retry_task = AsyncMock(return_value=MagicMock(
        task_id="t1",
        status="complete",
        summary="Retry completed",
        file_path="data/reports/t1.md",
        file_format="markdown",
    ))
    monkeypatch.setattr(mcp_mod, "_task_orchestrator", orchestrator)
    return orchestrator


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline & Agent tests
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryIra:
    async def test_success(self, mock_pipeline):
        result = await mcp_mod.query_ira("What is PF1?")
        assert "Pipeline response." in result
        assert "clio" in result
        mock_pipeline.process_request.assert_awaited_once()

    async def test_pipeline_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pipeline", None)
        result = await mcp_mod.query_ira("test")
        assert result == "Ira pipeline not available."

    async def test_error_handling(self, monkeypatch):
        pipeline = AsyncMock()
        pipeline.process_request = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(mcp_mod, "_pipeline", pipeline)
        result = await mcp_mod.query_ira("test")
        assert result.startswith("Error:")


class TestSearchKnowledge:
    async def test_success(self, mock_retriever):
        result = await mcp_mod.search_knowledge("PF1 specs")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["source"] == "specs.pdf"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_retriever", None)
        result = await mcp_mod.search_knowledge("test")
        assert result == "Retriever not available."


class TestSearchCrm:
    async def test_success(self, mock_crm):
        result = await mcp_mod.search_crm("Acme")
        parsed = json.loads(result)
        assert len(parsed["contacts"]) == 1
        assert parsed["contacts"][0]["name"] == "John Doe"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_crm", None)
        result = await mcp_mod.search_crm("test")
        assert result == "CRM not available."


class TestAskAgent:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.ask_agent("clio", "What is PF1?")
        assert result == "Agent response."
        mock_pantheon.get_agent.assert_called_with("clio")

    async def test_agent_not_found(self, mock_pantheon):
        mock_pantheon.get_agent.return_value = None
        result = await mcp_mod.ask_agent("nonexistent", "test")
        assert "not found" in result

    async def test_pantheon_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pantheon", None)
        result = await mcp_mod.ask_agent("clio", "test")
        assert result == "Pantheon not available."


# ═══════════════════════════════════════════════════════════════════════════
# Email tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchEmails:
    async def test_success(self, mock_email_processor):
        result = await mcp_mod.search_emails(from_address="sender@co.com")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["subject"] == "Quote request"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_email_processor", None)
        result = await mcp_mod.search_emails()
        assert result == "Email processor not available."

    async def test_error_handling(self, monkeypatch):
        ep = AsyncMock()
        ep.search_emails = AsyncMock(side_effect=RuntimeError("Gmail error"))
        monkeypatch.setattr(mcp_mod, "_email_processor", ep)
        result = await mcp_mod.search_emails()
        assert result.startswith("Error:")


class TestReadEmailThread:
    async def test_success(self, mock_email_processor):
        result = await mcp_mod.read_email_thread("thread-1")
        parsed = json.loads(result)
        assert parsed["thread_id"] == "thread-1"
        assert parsed["message_count"] == 2

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_email_processor", None)
        result = await mcp_mod.read_email_thread("t-1")
        assert result == "Email processor not available."


# ═══════════════════════════════════════════════════════════════════════════
# Memory tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRecallMemory:
    async def test_success(self, mock_long_term_memory):
        result = await mcp_mod.recall_memory("PF1 lead time")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert "12 weeks" in parsed[0]["memory"]

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_long_term_memory", None)
        result = await mcp_mod.recall_memory("test")
        assert result == "Long-term memory not available."


class TestStoreMemory:
    async def test_success(self, mock_long_term_memory):
        result = await mcp_mod.store_memory("PF1 lead time is 10 weeks now")
        parsed = json.loads(result)
        assert parsed[0]["id"] == "m-new"

    async def test_with_metadata(self, mock_long_term_memory):
        result = await mcp_mod.store_memory(
            "New fact",
            metadata='{"source": "meeting"}',
        )
        mock_long_term_memory.store.assert_awaited_once()
        call_kwargs = mock_long_term_memory.store.call_args
        assert call_kwargs[1]["metadata"] == {"source": "meeting"}

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_long_term_memory", None)
        result = await mcp_mod.store_memory("test")
        assert result == "Long-term memory not available."


class TestGetConversationHistory:
    async def test_success(self, mock_conversation_memory):
        result = await mcp_mod.get_conversation_history("rushabh")
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["role"] == "user"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_conversation_memory", None)
        result = await mcp_mod.get_conversation_history("rushabh")
        assert result == "Conversation memory not available."


class TestCheckRelationship:
    async def test_success(self, mock_relationship_memory):
        result = await mcp_mod.check_relationship("john_doe")
        parsed = json.loads(result)
        assert parsed["warmth_level"] == "WARM"
        assert parsed["interaction_count"] == 15

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_relationship_memory", None)
        result = await mcp_mod.check_relationship("test")
        assert result == "Relationship memory not available."


class TestCheckGoals:
    async def test_success(self, mock_goal_manager):
        result = await mcp_mod.check_goals("john_doe")
        parsed = json.loads(result)
        assert parsed["goal_type"] == "QUOTE_FOLLOW_UP"
        assert parsed["status"] == "ACTIVE"

    async def test_no_active_goal(self, monkeypatch):
        gm = AsyncMock()
        gm.get_active_goal = AsyncMock(return_value=None)
        monkeypatch.setattr(mcp_mod, "_goal_manager", gm)
        result = await mcp_mod.check_goals("nobody")
        parsed = json.loads(result)
        assert parsed["active_goal"] is None

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_goal_manager", None)
        result = await mcp_mod.check_goals("test")
        assert result == "Goal manager not available."


# ═══════════════════════════════════════════════════════════════════════════
# CRM operation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGetDeal:
    async def test_success(self, mock_crm):
        result = await mcp_mod.get_deal("deal-1")
        parsed = json.loads(result)
        assert parsed["title"] == "PF1 for Acme"
        assert parsed["value"] == 100000

    async def test_not_found(self, mock_crm):
        mock_crm.get_deal.return_value = None
        result = await mcp_mod.get_deal("nonexistent")
        assert "not found" in result

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_crm", None)
        result = await mcp_mod.get_deal("deal-1")
        assert result == "CRM not available."


class TestListDeals:
    async def test_success(self, mock_crm):
        result = await mcp_mod.list_deals()
        parsed = json.loads(result)
        assert isinstance(parsed, list)

    async def test_with_filters(self, mock_crm):
        await mcp_mod.list_deals(stage="proposal", contact_id="c-1")
        call_kwargs = mock_crm.list_deals.call_args[1]
        assert call_kwargs["filters"]["stage"] == "proposal"
        assert call_kwargs["filters"]["contact_id"] == "c-1"


class TestCreateContact:
    async def test_success(self, mock_crm):
        result = await mcp_mod.create_contact("Jane Smith", "jane@corp.com", role="VP")
        parsed = json.loads(result)
        assert parsed["name"] == "Jane Smith"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_crm", None)
        result = await mcp_mod.create_contact("Test", "test@test.com")
        assert result == "CRM not available."


class TestUpdateDeal:
    async def test_success(self, mock_crm):
        result = await mcp_mod.update_deal("deal-1", stage="negotiation")
        parsed = json.loads(result)
        assert parsed["stage"] == "negotiation"

    async def test_no_fields(self, mock_crm):
        result = await mcp_mod.update_deal("deal-1")
        assert "No fields to update" in result

    async def test_not_found(self, mock_crm):
        mock_crm.update_deal.return_value = None
        result = await mcp_mod.update_deal("bad-id", stage="won")
        assert "not found" in result


class TestGetStaleLeads:
    async def test_success(self, mock_crm):
        result = await mcp_mod.get_stale_leads(days=30)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Old Lead"


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge graph tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFindRelatedEntities:
    async def test_success(self, mock_knowledge_graph):
        result = await mcp_mod.find_related_entities("Acme Corp")
        parsed = json.loads(result)
        assert len(parsed["nodes"]) == 1
        assert parsed["nodes"][0]["name"] == "Acme Corp"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_knowledge_graph", None)
        result = await mcp_mod.find_related_entities("test")
        assert result == "Knowledge graph not available."


class TestFindCompanyContacts:
    async def test_success(self, mock_knowledge_graph):
        result = await mcp_mod.find_company_contacts("Acme Corp")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "John Doe"


class TestFindCompanyQuotes:
    async def test_success(self, mock_knowledge_graph):
        result = await mcp_mod.find_company_quotes("Acme Corp")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["machine"] == "PF1"


# ═══════════════════════════════════════════════════════════════════════════
# Web tool tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWebSearch:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.web_search("Machinecraft news")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "Result 1"

    async def test_pantheon_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pantheon", None)
        result = await mcp_mod.web_search("test")
        assert result == "Pantheon not available."

    async def test_iris_not_found(self, mock_pantheon):
        mock_pantheon.get_agent.return_value = None
        result = await mcp_mod.web_search("test")
        assert "not found" in result


class TestScrapeUrl:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.scrape_url("https://example.com")
        assert "Page Content" in result

    async def test_pantheon_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pantheon", None)
        result = await mcp_mod.scrape_url("https://example.com")
        assert result == "Pantheon not available."


# ═══════════════════════════════════════════════════════════════════════════
# Project tool tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGetProjectStatus:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.get_project_status("PF1 Build")
        assert result == "Agent response."

    async def test_atlas_not_found(self, mock_pantheon):
        mock_pantheon.get_agent.return_value = None
        result = await mcp_mod.get_project_status("test")
        assert "not found" in result


class TestGetOverdueMilestones:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.get_overdue_milestones()
        assert result == "Agent response."


# ═══════════════════════════════════════════════════════════════════════════
# Remaining existing tool tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGetPipelineSummary:
    async def test_success(self, mock_crm):
        result = await mcp_mod.get_pipeline_summary()
        parsed = json.loads(result)
        assert parsed["total_deals"] == 5

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_crm", None)
        result = await mcp_mod.get_pipeline_summary()
        assert result == "CRM not available."


class TestDraftEmail:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.draft_email("john@acme.com", "Follow up", "Discuss PF1 quote")
        assert result == "Agent response."

    async def test_pantheon_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pantheon", None)
        result = await mcp_mod.draft_email("a@b.com", "test", "test")
        assert result == "Pantheon not available."


class TestGetAgentList:
    async def test_success(self, mock_pantheon):
        result = await mcp_mod.get_agent_list()
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "test_agent"

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_pantheon", None)
        result = await mcp_mod.get_agent_list()
        assert result == "Pantheon not available."


# ═══════════════════════════════════════════════════════════════════════════
# Agent Loop tool tests (plan_task, execute_phase, generate_report)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def mock_agent_loop(monkeypatch):
    """Provide a mock AgentLoop with a pre-built plan."""
    loop = AsyncMock(spec=AgentLoop)
    loop._plans = {}

    plan = Plan(
        plan_id="plan_20260308_120000",
        goal="Analyze PF1 sales pipeline",
        original_request="Give me a full PF1 pipeline analysis",
        complexity="moderate",
        phases=[
            Phase(
                id=1,
                title="Gather CRM data",
                description="Pull all PF1 deals from CRM",
                agents=["prometheus"],
                delegation_type="revenue",
                expected_output="Deal list with stages and values",
            ),
            Phase(
                id=2,
                title="Compile report",
                description="Synthesize findings into a report",
                agents=["calliope"],
                delegation_type="generic",
                expected_output="Professional report",
            ),
        ],
    )

    async def mock_plan(request, complexity="auto", on_progress=None):
        loop._plans[plan.plan_id] = plan
        return plan

    loop.plan = AsyncMock(side_effect=mock_plan)
    loop.get_plan = MagicMock(side_effect=lambda pid: loop._plans.get(pid))

    async def mock_execute(p, phase=None, on_progress=None):
        target = phase or p.current_phase
        if target:
            target.status = PhaseStatus.COMPLETED
            target.result = json.dumps({"prometheus": "Found 5 active PF1 deals worth $500K"})
        return PhaseResult(
            phase_id=target.id if target else 0,
            agent_responses={"prometheus": "Found 5 active PF1 deals worth $500K"},
            decision=LoopDecision.CONTINUE,
            decision_reason="Results sufficient, proceeding",
        )

    loop.execute_phase = AsyncMock(side_effect=mock_execute)
    loop.replan = AsyncMock(return_value=plan)
    loop.compile = AsyncMock(return_value="# PF1 Pipeline Report\n\n## Executive Summary\n5 active deals worth $500K.")

    monkeypatch.setattr(mcp_mod, "_agent_loop", loop)
    return loop, plan


class TestPlanTask:
    async def test_success(self, mock_agent_loop):
        loop, plan = mock_agent_loop
        result = await mcp_mod.plan_task("Analyze PF1 pipeline")
        parsed = json.loads(result)
        assert parsed["plan_id"] == "plan_20260308_120000"
        assert parsed["goal"] == "Analyze PF1 sales pipeline"
        assert len(parsed["phases"]) == 2
        assert parsed["phases"][0]["agents"] == ["prometheus"]
        loop.plan.assert_awaited_once()

    async def test_with_complexity(self, mock_agent_loop):
        loop, _ = mock_agent_loop
        await mcp_mod.plan_task("Simple lookup", complexity="simple")
        loop.plan.assert_awaited_once_with("Simple lookup", complexity="simple")

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_agent_loop", None)
        result = await mcp_mod.plan_task("test")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_error_handling(self, monkeypatch):
        loop = AsyncMock(spec=AgentLoop)
        loop.plan = AsyncMock(side_effect=RuntimeError("LLM down"))
        monkeypatch.setattr(mcp_mod, "_agent_loop", loop)
        result = await mcp_mod.plan_task("test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "LLM down" in parsed["error"]


class TestExecutePhase:
    async def test_success(self, mock_agent_loop):
        loop, plan = mock_agent_loop
        loop._plans[plan.plan_id] = plan
        result = await mcp_mod.execute_phase(plan.plan_id, 1)
        parsed = json.loads(result)
        assert parsed["phase_id"] == 1
        assert parsed["phase_title"] == "Gather CRM data"
        assert "prometheus" in parsed["agents_consulted"]
        assert parsed["decision"] == "continue"

    async def test_plan_not_found(self, mock_agent_loop):
        result = await mcp_mod.execute_phase("nonexistent_plan", 1)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    async def test_phase_not_found(self, mock_agent_loop):
        loop, plan = mock_agent_loop
        loop._plans[plan.plan_id] = plan
        result = await mcp_mod.execute_phase(plan.plan_id, 99)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Phase 99" in parsed["error"]

    async def test_replan_triggered(self, mock_agent_loop):
        loop, plan = mock_agent_loop
        loop._plans[plan.plan_id] = plan

        async def replan_execute(p, phase=None, on_progress=None):
            target = phase or p.current_phase
            if target:
                target.status = PhaseStatus.COMPLETED
            return PhaseResult(
                phase_id=target.id if target else 0,
                agent_responses={"prometheus": "Insufficient data"},
                decision=LoopDecision.REPLAN,
                decision_reason="Need different agents",
            )

        loop.execute_phase = AsyncMock(side_effect=replan_execute)
        result = await mcp_mod.execute_phase(plan.plan_id, 1)
        parsed = json.loads(result)
        assert parsed["decision"] == "replan"
        loop.replan.assert_awaited_once()

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_agent_loop", None)
        result = await mcp_mod.execute_phase("plan_1", 1)
        parsed = json.loads(result)
        assert "error" in parsed


class TestGenerateReport:
    async def test_success(self, mock_agent_loop, tmp_path, monkeypatch):
        loop, plan = mock_agent_loop
        loop._plans[plan.plan_id] = plan
        monkeypatch.chdir(tmp_path)
        result = await mcp_mod.generate_report(plan.plan_id, title="PF1 Analysis")
        parsed = json.loads(result)
        assert parsed["format"] == "markdown"
        assert "PF1 Pipeline Report" in parsed["content_preview"]
        loop.compile.assert_awaited_once()

    async def test_plan_not_found(self, mock_agent_loop):
        result = await mcp_mod.generate_report("nonexistent_plan")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    async def test_unavailable(self, monkeypatch):
        monkeypatch.setattr(mcp_mod, "_agent_loop", None)
        result = await mcp_mod.generate_report("plan_1")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_custom_title(self, mock_agent_loop, tmp_path, monkeypatch):
        loop, plan = mock_agent_loop
        loop._plans[plan.plan_id] = plan
        monkeypatch.chdir(tmp_path)
        await mcp_mod.generate_report(plan.plan_id, title="Q1 Revenue Report")
        loop.compile.assert_awaited_once_with(plan, title="Q1 Revenue Report")


class TestTaskControlTools:
    async def test_get_task_status_success(self, mock_task_orchestrator):
        result = await mcp_mod.get_task_status("t1")
        parsed = json.loads(result)
        assert parsed["task_id"] == "t1"
        assert parsed["status"] == "executing"

    async def test_get_task_status_not_found(self, mock_task_orchestrator):
        mock_task_orchestrator.get_task_state.return_value = None
        result = await mcp_mod.get_task_status("missing")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_abort_task_success(self, mock_task_orchestrator):
        result = await mcp_mod.abort_task("t1", reason="operator stop")
        parsed = json.loads(result)
        assert parsed["status"] == "aborting"
        mock_task_orchestrator.abort_task.assert_awaited_once_with("t1", reason="operator stop")

    async def test_abort_task_not_found(self, mock_task_orchestrator):
        mock_task_orchestrator.abort_task.return_value = False
        result = await mcp_mod.abort_task("missing")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_list_tasks_success(self, mock_task_orchestrator):
        result = await mcp_mod.list_tasks(limit=10)
        parsed = json.loads(result)
        assert parsed["count"] == 2
        assert parsed["tasks"][0]["task_id"] == "t2"

    async def test_get_task_events_success(self, mock_task_orchestrator):
        result = await mcp_mod.get_task_events("t1", limit=20)
        parsed = json.loads(result)
        assert parsed["task_id"] == "t1"
        assert parsed["count"] == 2
        assert parsed["events"][0]["type"] == "task_created"

    async def test_retry_task_success(self, mock_task_orchestrator):
        result = await mcp_mod.retry_task("t1", from_phase=1)
        parsed = json.loads(result)
        assert parsed["task_id"] == "t1"
        assert parsed["status"] == "complete"
        mock_task_orchestrator.retry_task.assert_awaited_once_with("t1", from_phase=1)
