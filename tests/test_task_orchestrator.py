"""Tests for the TaskOrchestrator — multi-phase agent task loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.schemas.llm_outputs import (
    ClarityAssessment,
    TaskPlan,
    TaskPlanPhase,
)
from ira.systems.task_orchestrator import TaskOrchestrator, TaskResult


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _mock_redis(state_store: dict | None = None):
    """Return a mock RedisCache backed by an in-memory dict."""
    store = state_store if state_store is not None else {}
    redis = MagicMock()
    redis.available = True

    async def _set_json(key: str, value, ttl=None):
        store[key] = json.dumps(value, default=str)
        return True

    async def _get_json(key: str):
        raw = store.get(key)
        return json.loads(raw) if raw else None

    redis.set_json = AsyncMock(side_effect=_set_json)
    redis.get_json = AsyncMock(side_effect=_get_json)
    return redis, store


def _mock_agent(name: str, response: str = "Agent response"):
    """Return a mock agent with a canned handle() response."""
    agent = MagicMock()
    agent.name = name
    agent.role = f"{name} role"
    agent.description = f"{name} description"
    agent.handle = AsyncMock(return_value=response)
    return agent


def _mock_sphinx(*, clear: bool = True, questions: list[str] | None = None):
    """Return a mock Sphinx agent with assess_clarity()."""
    sphinx = _mock_agent("sphinx")
    assessment = ClarityAssessment(
        clear=clear,
        ambiguity_reason="" if clear else "Ambiguous request",
        clarifying_questions=questions or [],
    )
    sphinx.assess_clarity = AsyncMock(return_value=assessment)
    return sphinx


def _mock_athena(phases: list[TaskPlanPhase] | None = None):
    """Return a mock Athena agent with generate_plan()."""
    athena = _mock_agent("athena")
    plan = TaskPlan(
        goal="test goal",
        phases=phases or [
            TaskPlanPhase(title="Research", agent="clio", description="Research the topic"),
            TaskPlanPhase(title="Analyze", agent="prometheus", description="Analyze the data"),
        ],
        reasoning="Test plan",
    )
    athena.generate_plan = AsyncMock(return_value=plan)
    return athena


def _mock_pantheon(agents: dict[str, MagicMock] | None = None):
    """Return a mock Pantheon with configurable agents."""
    pantheon = MagicMock()
    agent_map = agents or {}
    pantheon.get_agent = MagicMock(side_effect=lambda name: agent_map.get(name))
    pantheon.agents = agent_map
    return pantheon


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def redis_and_store():
    return _mock_redis()


@pytest.fixture()
def clio():
    return _mock_agent("clio", "Clio found relevant documents about PF1 machines.")


@pytest.fixture()
def prometheus():
    return _mock_agent("prometheus", "Prometheus reports 3 active deals in pipeline.")


@pytest.fixture()
def calliope():
    return _mock_agent("calliope", "# Final Report\n\nComprehensive analysis complete.")


@pytest.fixture()
def orchestrator(redis_and_store, clio, prometheus, calliope):
    redis, _ = redis_and_store
    sphinx = _mock_sphinx(clear=True)
    athena = _mock_athena()

    agents = {
        "sphinx": sphinx,
        "athena": athena,
        "clio": clio,
        "prometheus": prometheus,
        "calliope": calliope,
    }
    pantheon = _mock_pantheon(agents)

    return TaskOrchestrator(
        pantheon=pantheon,
        redis_cache=redis,
        voice=MagicMock(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimpleTaskFlow:
    """Happy path: clear query -> plan -> execute -> report."""

    async def test_full_task_completes(self, orchestrator, tmp_path):
        events: list[dict] = []

        async def on_progress(event):
            events.append(event)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Analyze the PF1 pipeline")
            result = await orchestrator.run_task(task_id, on_progress=on_progress)

        assert result.status == "complete"
        assert result.file_path
        assert Path(result.file_path).exists()

        event_types = [e["type"] for e in events]
        assert "task_created" in event_types
        assert "clarity_checking" in event_types
        assert "plan_created" in event_types
        assert "phase_started" in event_types
        assert "phase_done" in event_types
        assert "report_generating" in event_types
        assert "report_ready" in event_types
        assert "task_complete" in event_types

    async def test_plan_created_event_contains_phases(self, orchestrator, tmp_path):
        events: list[dict] = []

        async def on_progress(event):
            events.append(event)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Test")
            await orchestrator.run_task(task_id, on_progress=on_progress)

        plan_events = [e for e in events if e["type"] == "plan_created"]
        assert len(plan_events) == 1
        phases = plan_events[0]["phases"]
        assert len(phases) == 2
        assert phases[0]["agent"] == "clio"
        assert phases[1]["agent"] == "prometheus"
        assert "depends_on" in phases[0]

    async def test_agents_called_with_accumulated_context(
        self, orchestrator, clio, prometheus, tmp_path,
    ):
        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Test")
            await orchestrator.run_task(task_id)

        clio.handle.assert_called_once()
        prometheus.handle.assert_called_once()

        prometheus_prompt = prometheus.handle.call_args[0][0]
        assert "Context from previous phases" in prometheus_prompt
        assert "clio" in prometheus_prompt.lower()

    async def test_phase_progress_event_contains_metrics(self, orchestrator, tmp_path):
        events: list[dict] = []

        async def on_progress(event):
            events.append(event)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Analyze task progress metrics")
            await orchestrator.run_task(task_id, on_progress=on_progress)

        progress_events = [e for e in events if e["type"] == "phase_progress"]
        assert progress_events
        first = progress_events[0]
        assert "phase_index" in first
        assert "total_phases" in first
        assert "progress_pct" in first
        assert "elapsed_ms" in first
        assert "eta_ms" in first

    async def test_report_file_written(self, orchestrator, tmp_path):
        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Test")
            result = await orchestrator.run_task(task_id)

        report_path = Path(result.file_path)
        assert report_path.exists()
        content = report_path.read_text()
        assert len(content) > 0


class TestClarificationFlow:
    """Sphinx detects ambiguity -> pause -> resume with answer."""

    async def test_clarification_needed_pauses_task(self, redis_and_store):
        redis, store = redis_and_store
        sphinx = _mock_sphinx(
            clear=False,
            questions=["Which machine model?", "What configuration?"],
        )
        athena = _mock_athena()
        agents = {"sphinx": sphinx, "athena": athena}
        pantheon = _mock_pantheon(agents)

        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        events: list[dict] = []

        async def on_progress(event):
            events.append(event)

        task_id = await orch.create_task("How much does it cost?")
        result = await orch.run_task(task_id, on_progress=on_progress)

        assert result.status == "clarification_needed"
        assert len(result.clarification_questions) == 2
        assert "Which machine model?" in result.clarification_questions

        event_types = [e["type"] for e in events]
        assert "clarification_needed" in event_types
        assert "plan_created" not in event_types

    async def test_resume_after_clarification(self, redis_and_store, tmp_path):
        redis, store = redis_and_store
        sphinx_ambiguous = _mock_sphinx(
            clear=False,
            questions=["Which machine?"],
        )
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="Research", agent="clio", description="Look up specs"),
        ])
        clio = _mock_agent("clio", "PF1-C specs found.")
        calliope = _mock_agent("calliope", "# Report\n\nPF1-C analysis.")

        agents_first = {
            "sphinx": sphinx_ambiguous,
            "athena": athena,
            "clio": clio,
            "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents_first)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        task_id = await orch.create_task("How much?")
        result1 = await orch.run_task(task_id)
        assert result1.status == "clarification_needed"

        sphinx_clear = _mock_sphinx(clear=True)
        agents_second = {
            "sphinx": sphinx_clear,
            "athena": athena,
            "clio": clio,
            "calliope": calliope,
        }
        pantheon.get_agent = MagicMock(side_effect=lambda n: agents_second.get(n))

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            result2 = await orch.resume_with_clarification(
                task_id, "The PF1-C model",
            )

        assert result2.status == "complete"
        assert result2.file_path

    async def test_redis_state_persisted_during_clarification(self, redis_and_store):
        redis, store = redis_and_store
        sphinx = _mock_sphinx(clear=False, questions=["Which one?"])
        agents = {"sphinx": sphinx, "athena": _mock_athena()}
        pantheon = _mock_pantheon(agents)

        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)
        task_id = await orch.create_task("Vague request")
        await orch.run_task(task_id)

        redis.set_json.assert_called()
        state = await redis.get_json(f"task:{task_id}")
        assert state is not None
        assert state["status"] == "awaiting_clarification"


class TestPhaseFailureHandling:
    """One agent fails or times out — orchestrator continues."""

    async def test_agent_not_found_skipped(self, redis_and_store, tmp_path):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="Research", agent="nonexistent", description="Do something"),
            TaskPlanPhase(title="Write", agent="calliope", description="Write report"),
        ])
        calliope = _mock_agent("calliope", "# Report\n\nDone.")

        agents = {"sphinx": sphinx, "athena": athena, "calliope": calliope}
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        events: list[dict] = []

        async def on_progress(event):
            events.append(event)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Test")
            result = await orch.run_task(task_id, on_progress=on_progress)

        assert result.status == "complete"

        phase_done_events = [e for e in events if e["type"] == "phase_done"]
        assert len(phase_done_events) == 2
        assert "not found" in phase_done_events[0]["preview"]

    async def test_agent_exception_captured(self, redis_and_store, tmp_path):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)

        failing_agent = _mock_agent("clio")
        failing_agent.handle = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        calliope = _mock_agent("calliope", "# Report")
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="Research", agent="clio", description="Research"),
            TaskPlanPhase(title="Write", agent="calliope", description="Write"),
        ])

        agents = {
            "sphinx": sphinx,
            "athena": athena,
            "clio": failing_agent,
            "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Test")
            result = await orch.run_task(task_id)

        assert result.status == "complete"
        # Calliope is called twice: once as a phase agent, once for report formatting
        assert calliope.handle.call_count == 2

    async def test_dependency_cycle_returns_error(self, redis_and_store):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        # Cyclic dependencies: phase 0 depends on 2, phase 1 depends on 1
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="P1", agent="clio", description="Do P1", depends_on=[2]),
            TaskPlanPhase(title="P2", agent="prometheus", description="Do P2", depends_on=[1]),
        ])
        clio = _mock_agent("clio", "P1")
        prometheus = _mock_agent("prometheus", "P2")
        calliope = _mock_agent("calliope", "# Report")

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "prometheus": prometheus, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        task_id = await orch.create_task("Cyclic dependency task")
        result = await orch.run_task(task_id)
        assert result.status == "error"
        assert "Dependency cycle" in result.summary

    async def test_dependency_ordering_respected(self, redis_and_store, tmp_path):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="P2", agent="prometheus", description="Do second", depends_on=[1]),
            TaskPlanPhase(title="P1", agent="clio", description="Do first", depends_on=[]),
        ])
        clio = _mock_agent("clio", "first-result")
        prometheus = _mock_agent("prometheus", "second-result")
        calliope = _mock_agent("calliope", "# Report")

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "prometheus": prometheus, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Dependency order task")
            result = await orch.run_task(task_id)

        assert result.status == "complete"
        clio.handle.assert_called_once()
        prometheus.handle.assert_called_once()


class TestRedisStatePersistence:
    """Task state round-trips through Redis correctly."""

    async def test_state_saved_after_each_phase(self, redis_and_store, tmp_path):
        redis, store = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="P1", agent="clio", description="Do P1"),
            TaskPlanPhase(title="P2", agent="prometheus", description="Do P2"),
        ])
        clio = _mock_agent("clio", "P1 result")
        prometheus = _mock_agent("prometheus", "P2 result")
        calliope = _mock_agent("calliope", "# Report")

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "prometheus": prometheus, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Test")
            await orch.run_task(task_id)

        final_state = await redis.get_json(f"task:{task_id}")
        assert final_state["status"] == "complete"
        assert "0" in final_state["phase_results"]
        assert "1" in final_state["phase_results"]

    async def test_no_redis_graceful_degradation(self, tmp_path):
        redis = MagicMock()
        redis.available = False
        redis.set_json = AsyncMock(return_value=False)
        redis.get_json = AsyncMock(return_value=None)

        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena()
        clio = _mock_agent("clio", "result")
        prometheus = _mock_agent("prometheus", "result")
        calliope = _mock_agent("calliope", "# Report")

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "prometheus": prometheus, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Test")
            result = await orch.run_task(task_id)

        assert result.status == "complete"
        assert result.file_path

        state = await orch.get_task_state(task_id)
        assert state is not None
        assert state["status"] == "complete"

        tasks = await orch.list_tasks(limit=10)
        assert tasks
        assert tasks[0]["task_id"] == task_id

    async def test_events_available_without_redis(self):
        redis = MagicMock()
        redis.available = False
        redis.set_json = AsyncMock(return_value=False)
        redis.get_json = AsyncMock(return_value=None)

        orch = TaskOrchestrator(pantheon=_mock_pantheon({}), redis_cache=redis)
        task_id = await orch.create_task("Event fallback")
        await orch.append_task_event(task_id, {"type": "phase_started"})
        await orch.append_task_event(task_id, {"type": "phase_done"})

        events = await orch.get_task_events(task_id, limit=10)
        assert len(events) == 2
        assert events[0]["type"] == "phase_started"
        assert events[1]["type"] == "phase_done"

    async def test_get_task_state_returns_persisted_state(self, orchestrator):
        task_id = await orchestrator.create_task("Status check task")
        state = await orchestrator.get_task_state(task_id)
        assert state is not None
        assert state["task_id"] == task_id
        assert state["status"] == "created"

    async def test_abort_task_updates_state(self, orchestrator):
        task_id = await orchestrator.create_task("Abort this task")
        ok = await orchestrator.abort_task(task_id, reason="operator requested stop")
        assert ok is True
        state = await orchestrator.get_task_state(task_id)
        assert state is not None
        assert state["abort_requested"] is True
        assert state["status"] == "aborting"
        assert state["abort_reason"] == "operator requested stop"

    async def test_list_tasks_returns_recent_first(self, orchestrator):
        t1 = await orchestrator.create_task("Task one")
        t2 = await orchestrator.create_task("Task two")
        tasks = await orchestrator.list_tasks(limit=10)
        assert len(tasks) == 2
        assert tasks[0]["task_id"] == t2
        assert tasks[1]["task_id"] == t1

    async def test_retry_task_from_phase_uses_existing_phase_results(
        self, redis_and_store, tmp_path,
    ):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="P1", agent="clio", description="Do first"),
            TaskPlanPhase(title="P2", agent="prometheus", description="Do second"),
        ])
        clio = _mock_agent("clio", "first-result")
        prometheus = _mock_agent("prometheus", "second-result")
        calliope = _mock_agent("calliope", "# Report")

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "prometheus": prometheus, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(pantheon=pantheon, redis_cache=redis)

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Retry test task")
            first = await orch.run_task(task_id)
            assert first.status == "complete"

            # Reset call counters; retry from phase 1 should not re-run phase 0.
            clio.handle.reset_mock()
            prometheus.handle.reset_mock()
            calliope.handle.reset_mock()

            retried = await orch.retry_task(task_id, from_phase=1)

        assert retried.status == "complete"
        clio.handle.assert_not_called()
        prometheus.handle.assert_called_once()


class TestReportGeneration:
    """Report formatting and file output."""

    async def test_markdown_report_saved(self, orchestrator, tmp_path):
        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Test", output_format="markdown")
            result = await orchestrator.run_task(task_id)

        assert result.file_format == "markdown"
        assert result.file_path.endswith(".md")
        assert Path(result.file_path).exists()

    async def test_pdf_fallback_when_pdfco_unavailable(self, redis_and_store, tmp_path):
        redis, _ = redis_and_store
        sphinx = _mock_sphinx(clear=True)
        athena = _mock_athena(phases=[
            TaskPlanPhase(title="Research", agent="clio", description="Research"),
        ])
        clio = _mock_agent("clio", "Research results")
        calliope = _mock_agent("calliope", "# Report")

        pdfco = MagicMock()
        pdfco.available = False

        agents = {
            "sphinx": sphinx, "athena": athena,
            "clio": clio, "calliope": calliope,
        }
        pantheon = _mock_pantheon(agents)
        orch = TaskOrchestrator(
            pantheon=pantheon, redis_cache=redis, pdfco=pdfco,
        )

        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orch.create_task("Test", output_format="pdf")
            result = await orch.run_task(task_id)

        assert result.status == "complete"
        assert result.file_path.endswith(".md")

    async def test_calliope_called_with_accumulated_results(
        self, orchestrator, calliope, tmp_path,
    ):
        with patch("ira.systems.task_orchestrator._REPORTS_DIR", tmp_path):
            task_id = await orchestrator.create_task("Test")
            await orchestrator.run_task(task_id)

        calliope.handle.assert_called_once()
        prompt = calliope.handle.call_args[0][0]
        assert "clio" in prompt.lower() or "Research" in prompt
        assert "prometheus" in prompt.lower() or "Analyze" in prompt
