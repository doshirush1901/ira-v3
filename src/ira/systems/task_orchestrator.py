"""Task orchestrator — server-side plan-execute-report loop.

Provides :class:`TaskOrchestrator`, which drives multi-phase tasks through
the Pantheon.  The flow is:

1. **Clarity check** — Sphinx assesses whether the goal is actionable.
2. **Planning** — Athena generates a structured :class:`TaskPlan`.
3. **Execution** — Each phase runs through the assigned specialist agent.
4. **Reporting** — Calliope formats accumulated results into a document.

Task state is persisted in Redis so that clarification round-trips can
span multiple HTTP requests.  Progress events are emitted via an async
callback (same pattern as :class:`~ira.pipeline.RequestPipeline`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from langfuse.decorators import observe

from ira.schemas.llm_outputs import ClarityAssessment, TaskPlan, TaskPlanPhase

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

_TASK_TTL_SECONDS = 3600
_PHASE_TIMEOUT = 120
_REPORTS_DIR = Path("data/reports")


@dataclass
class TaskResult:
    """Value object returned when a task completes (or pauses for clarification)."""

    task_id: str
    status: str  # "complete", "clarification_needed", "error"
    summary: str = ""
    file_path: str = ""
    file_format: str = ""
    clarification_questions: list[str] = field(default_factory=list)


class TaskOrchestrator:
    """Server-side orchestrator for multi-phase agent tasks."""

    def __init__(
        self,
        *,
        pantheon: Any,
        redis_cache: Any,
        voice: Any | None = None,
        pdfco: Any | None = None,
    ) -> None:
        self._pantheon = pantheon
        self._redis = redis_cache
        self._voice = voice
        self._pdfco = pdfco

    # ── public API ────────────────────────────────────────────────────────

    async def create_task(
        self,
        goal: str,
        user_id: str | None = None,
        output_format: str = "markdown",
    ) -> str:
        """Persist initial task state in Redis and return a task_id."""
        task_id = uuid.uuid4().hex[:12]
        state = {
            "task_id": task_id,
            "goal": goal,
            "user_id": user_id or "anonymous",
            "output_format": output_format,
            "status": "created",
            "plan": None,
            "phase_results": {},
        }
        await self._save_state(task_id, state)
        return task_id

    @observe(name="task_orchestrator.run_task")
    async def run_task(
        self,
        task_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> TaskResult:
        """Execute the full plan-execute-report loop for a task."""
        state = await self._load_state(task_id)
        if state is None:
            return TaskResult(task_id=task_id, status="error", summary="Task not found")

        try:
            await self._emit(on_progress, "task_created", task_id=task_id)

            # 1. Clarity check
            clarity = await self._check_clarity(state["goal"], on_progress)
            if not clarity.clear:
                state["status"] = "awaiting_clarification"
                state["clarification_questions"] = clarity.clarifying_questions
                await self._save_state(task_id, state)
                await self._emit(
                    on_progress, "clarification_needed",
                    questions=clarity.clarifying_questions,
                    reason=clarity.ambiguity_reason,
                    task_id=task_id,
                )
                return TaskResult(
                    task_id=task_id,
                    status="clarification_needed",
                    clarification_questions=clarity.clarifying_questions,
                )

            # 2. Plan
            return await self._plan_and_execute(task_id, state, on_progress)

        except Exception as exc:
            logger.exception("Task %s failed", task_id)
            await self._emit(on_progress, "task_error", error=str(exc))
            return TaskResult(task_id=task_id, status="error", summary=str(exc))

    @observe(name="task_orchestrator.resume_with_clarification")
    async def resume_with_clarification(
        self,
        task_id: str,
        answer: str,
        on_progress: ProgressCallback | None = None,
    ) -> TaskResult:
        """Resume a task that was paused for clarification."""
        state = await self._load_state(task_id)
        if state is None:
            return TaskResult(task_id=task_id, status="error", summary="Task not found")

        original_goal = state["goal"]
        state["goal"] = f"{original_goal}\n\nClarification: {answer}"
        state["status"] = "resumed"
        await self._save_state(task_id, state)

        try:
            return await self._plan_and_execute(task_id, state, on_progress)
        except Exception as exc:
            logger.exception("Task %s failed after clarification", task_id)
            await self._emit(on_progress, "task_error", error=str(exc))
            return TaskResult(task_id=task_id, status="error", summary=str(exc))

    # ── internal orchestration ────────────────────────────────────────────

    async def _plan_and_execute(
        self,
        task_id: str,
        state: dict[str, Any],
        on_progress: ProgressCallback | None,
    ) -> TaskResult:
        """Generate a plan, execute all phases, and produce a report."""
        goal = state["goal"]

        # Plan
        plan = await self._generate_plan(goal, on_progress)
        state["plan"] = plan.model_dump()
        state["status"] = "executing"
        await self._save_state(task_id, state)

        await self._emit(
            on_progress, "plan_created",
            phases=[
                {"id": i, "title": p.title, "agent": p.agent, "description": p.description}
                for i, p in enumerate(plan.phases)
            ],
        )

        # Execute phases
        accumulated: dict[int, dict[str, Any]] = {}
        for idx, phase in enumerate(plan.phases):
            context_summary = self._build_phase_context(accumulated)
            result = await self._execute_phase(idx, phase, context_summary, on_progress, goal=goal)
            accumulated[idx] = {"title": phase.title, "agent": phase.agent, "result": result}
            state["phase_results"][str(idx)] = result
            await self._save_state(task_id, state)

        # Report
        output_format = state.get("output_format", "markdown")
        file_path = await self._generate_report(
            task_id, goal, accumulated, output_format, on_progress,
        )

        state["status"] = "complete"
        state["file_path"] = file_path
        await self._save_state(task_id, state)

        summary = f"Completed {len(plan.phases)} phases. Report saved to {file_path}"
        await self._emit(
            on_progress, "task_complete", task_id=task_id, summary=summary,
        )

        return TaskResult(
            task_id=task_id,
            status="complete",
            summary=summary,
            file_path=file_path,
            file_format=output_format,
        )

    async def _check_clarity(
        self,
        goal: str,
        on_progress: ProgressCallback | None,
    ) -> ClarityAssessment:
        """Ask Sphinx for a structured clarity assessment."""
        await self._emit(on_progress, "clarity_checking")

        sphinx = self._pantheon.get_agent("sphinx")
        if sphinx is None:
            logger.warning("Sphinx not available — assuming query is clear")
            return ClarityAssessment(clear=True)

        try:
            return await asyncio.wait_for(
                sphinx.assess_clarity(goal),
                timeout=_PHASE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Sphinx clarity check timed out — assuming clear")
            return ClarityAssessment(clear=True)
        except Exception:
            logger.exception("Sphinx clarity check failed — assuming clear")
            return ClarityAssessment(clear=True)

    async def _generate_plan(
        self,
        goal: str,
        on_progress: ProgressCallback | None,
    ) -> TaskPlan:
        """Ask Athena to produce a structured execution plan."""
        await self._emit(on_progress, "planning")

        athena = self._pantheon.get_agent("athena")
        if athena is None:
            logger.error("Athena not available — cannot plan")
            return TaskPlan(goal=goal, phases=[])

        plan = await athena.generate_plan(goal)

        if not plan.phases:
            logger.warning("Athena returned empty plan — creating single-agent fallback")
            plan = TaskPlan(
                goal=goal,
                phases=[TaskPlanPhase(title="Research", agent="clio", description=goal)],
                reasoning="Fallback: no phases generated",
            )

        return plan

    async def _execute_phase(
        self,
        phase_id: int,
        phase: TaskPlanPhase,
        context_from_previous: str,
        on_progress: ProgressCallback | None,
        *,
        goal: str = "",
    ) -> str:
        """Run a single phase through the assigned agent."""
        await self._emit(
            on_progress, "phase_started",
            phase_id=phase_id, agent=phase.agent, title=phase.title,
        )

        agent = self._pantheon.get_agent(phase.agent)
        if agent is None:
            result = f"(Agent '{phase.agent}' not found — skipped)"
            logger.warning("Phase %d: agent '%s' not found", phase_id, phase.agent)
        else:
            task_prompt = phase.description
            if goal:
                task_prompt = (
                    f"OVERALL TASK GOAL:\n{goal}\n\n"
                    f"YOUR PHASE ASSIGNMENT:\n{phase.description}"
                )
            if context_from_previous:
                task_prompt += f"\n\nContext from previous phases:\n{context_from_previous}"

            try:
                result = await asyncio.wait_for(
                    agent.handle(task_prompt, {"task_phase": True}),
                    timeout=_PHASE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result = f"(Agent '{phase.agent}' timed out after {_PHASE_TIMEOUT}s)"
                logger.warning("Phase %d: agent '%s' timed out", phase_id, phase.agent)
            except Exception as exc:
                result = f"(Agent '{phase.agent}' error: {exc})"
                logger.exception("Phase %d: agent '%s' failed", phase_id, phase.agent)

        result = result or f"(Agent '{phase.agent}' returned no output)"
        await self._emit(
            on_progress, "phase_done",
            phase_id=phase_id, agent=phase.agent, preview=str(result)[:300],
        )
        return result

    async def _generate_report(
        self,
        task_id: str,
        goal: str,
        accumulated: dict[int, dict[str, Any]],
        output_format: str,
        on_progress: ProgressCallback | None,
    ) -> str:
        """Ask Calliope to format results and save to a file."""
        await self._emit(on_progress, "report_generating")

        compiled = "\n\n---\n\n".join(
            f"## {info['title']} ({info['agent']})\n\n{info['result']}"
            for info in accumulated.values()
        )

        calliope = self._pantheon.get_agent("calliope")
        if calliope is not None:
            try:
                markdown_report = await asyncio.wait_for(
                    calliope.handle(
                        f"Format these research results into a comprehensive, professional "
                        f"report.\n\nGoal: {goal}\n\nResults:\n\n{compiled}",
                    ),
                    timeout=_PHASE_TIMEOUT,
                )
            except Exception:
                logger.exception("Calliope report formatting failed — using raw results")
                markdown_report = f"# Report: {goal}\n\n{compiled}"
        else:
            markdown_report = f"# Report: {goal}\n\n{compiled}"

        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        md_path = _REPORTS_DIR / f"{task_id}.md"
        md_path.write_text(markdown_report, encoding="utf-8")

        file_path = str(md_path)

        if output_format == "pdf" and self._pdfco is not None and self._pdfco.available:
            try:
                html = f"<html><body><pre>{markdown_report}</pre></body></html>"
                pdf_bytes = await self._pdfco.html_to_pdf(html, name=f"{task_id}.pdf")
                pdf_path = _REPORTS_DIR / f"{task_id}.pdf"
                pdf_path.write_bytes(pdf_bytes)
                file_path = str(pdf_path)
            except Exception:
                logger.exception("PDF generation failed — falling back to markdown")

        await self._emit(
            on_progress, "report_ready",
            file_path=file_path, format=output_format,
        )
        return file_path

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_phase_context(self, accumulated: dict[int, dict[str, Any]]) -> str:
        """Summarise completed phases into a context string for the next agent."""
        if not accumulated:
            return ""
        parts = []
        for info in accumulated.values():
            result = str(info.get("result") or "")
            parts.append(f"[{info['title']} — {info['agent']}]: {result[:1000]}")
        return "\n\n".join(parts)

    async def _save_state(self, task_id: str, state: dict[str, Any]) -> None:
        if self._redis is not None and self._redis.available:
            await self._redis.set_json(f"task:{task_id}", state, _TASK_TTL_SECONDS)

    async def _load_state(self, task_id: str) -> dict[str, Any] | None:
        if self._redis is not None and self._redis.available:
            return await self._redis.get_json(f"task:{task_id}")
        return None

    @staticmethod
    async def _emit(
        callback: ProgressCallback | None,
        event_type: str,
        **payload: Any,
    ) -> None:
        if callback is not None:
            await callback({"type": event_type, **payload})
