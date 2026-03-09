"""
pipeline_loop.py — Iterative Agent Loop (OpenManus-inspired)

This module adds an iterative Plan-Execute-Observe loop on top of Ira's
existing RequestPipeline. Instead of a single fire-and-forget pass, the
loop allows Athena to:

  1. Plan: Break the request into phases
  2. Execute: Run one phase at a time via the Pantheon
  3. Observe: Evaluate the result and decide whether to continue, re-plan,
     or request clarification
  4. Compile: Synthesize all phase results into a final output

This is designed to be called from the MCP server's plan_task / execute_phase
tools, or directly from the API server for streaming use cases.

Integration:
    This does NOT replace RequestPipeline. It wraps it. The existing pipeline
    handles the per-turn processing (classify → route → respond → learn).
    This loop handles multi-turn orchestration across phases.

Usage:
    from ira.pipeline_loop import AgentLoop
    loop = AgentLoop(pantheon)
    plan = await loop.plan(request)
    for phase in plan.phases:
        result = await loop.execute_phase(phase)
        if result.needs_replan:
            plan = await loop.replan(plan, result)
    report = await loop.compile(plan)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────

class PhaseStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    REPLANNED = "replanned"


class LoopDecision(Enum):
    CONTINUE = "continue"          # Proceed to next phase
    REPLAN = "replan"              # Athena should revise the remaining plan
    CLARIFY = "clarify"            # Need user input before continuing
    COMPLETE = "complete"          # All phases done, compile results
    ABORT = "abort"                # Unrecoverable error


@dataclass
class Phase:
    id: int
    title: str
    description: str
    agents: list[str]
    delegation_type: str = "generic"
    expected_output: str = ""
    depends_on: list[int] = field(default_factory=list)
    status: PhaseStatus = PhaseStatus.PENDING
    result: str = ""
    error: str = ""


@dataclass
class Plan:
    plan_id: str
    goal: str
    original_request: str
    phases: list[Phase]
    complexity: str = "moderate"
    status: str = "created"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    revision_count: int = 0

    @property
    def current_phase(self) -> Phase | None:
        for phase in self.phases:
            if phase.status == PhaseStatus.PENDING:
                return phase
        return None

    @property
    def completed_phases(self) -> list[Phase]:
        return [p for p in self.phases if p.status == PhaseStatus.COMPLETED]

    @property
    def is_complete(self) -> bool:
        return all(p.status == PhaseStatus.COMPLETED for p in self.phases)


@dataclass
class PhaseResult:
    phase_id: int
    agent_responses: dict[str, str]
    decision: LoopDecision
    decision_reason: str = ""
    clarification_question: str = ""


# ── Progress callback type ───────────────────────────────────────────
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


# ── Agent Loop ───────────────────────────────────────────────────────

class AgentLoop:
    """Iterative Plan-Execute-Observe loop for multi-phase task execution.

    This is the core of the Manus-like experience. It wraps the Pantheon
    and provides a structured way to plan, execute, observe, and compile
    multi-agent workflows.
    """

    MAX_PHASES = 10
    MAX_REPLANS = 3

    def __init__(self, pantheon: Any) -> None:
        self._pantheon = pantheon
        self._athena = pantheon.get_agent("athena")
        self._plans: dict[str, Plan] = {}

    def get_plan(self, plan_id: str) -> Plan | None:
        """Return a previously created plan by id."""
        return self._plans.get(plan_id)

    # ── Step 1: Plan ─────────────────────────────────────────────────

    async def plan(
        self,
        request: str,
        complexity: str = "auto",
        on_progress: ProgressCallback = None,
    ) -> Plan:
        """Analyze a request and create a structured execution plan.

        Uses Athena to break down the request into phases, each mapped
        to the appropriate specialist agents.
        """
        if on_progress:
            await on_progress({"type": "planning", "status": "started"})

        planning_prompt = self._build_planning_prompt(request, complexity)

        plan_json = await self._athena.call_llm(
            "You are Athena, the CEO/Orchestrator. Create a precise "
            "execution plan for this business query.",
            planning_prompt,
            temperature=0.2,
        )

        plan = self._parse_plan(request, plan_json)
        self._plans[plan.plan_id] = plan

        if on_progress:
            await on_progress({
                "type": "planning",
                "status": "completed",
                "plan_id": plan.plan_id,
                "phase_count": len(plan.phases),
            })

        return plan

    # ── Step 2: Execute Phase ────────────────────────────────────────

    async def execute_phase(
        self,
        plan: Plan,
        phase: Phase | None = None,
        on_progress: ProgressCallback = None,
    ) -> PhaseResult:
        """Execute a single phase of the plan.

        Runs the assigned agents with structured delegation prompts,
        collects responses, and uses Athena to decide the next action.
        """
        if phase is None:
            phase = plan.current_phase
        if phase is None:
            return PhaseResult(
                phase_id=0,
                agent_responses={},
                decision=LoopDecision.COMPLETE,
                decision_reason="All phases already completed",
            )

        phase.status = PhaseStatus.RUNNING

        if on_progress:
            await on_progress({
                "type": "phase_started",
                "phase_id": phase.id,
                "title": phase.title,
                "agents": phase.agents,
            })

        # Build context from completed phases
        prior_context = self._build_prior_context(plan, phase)

        # Run each agent in the phase
        agent_responses: dict[str, str] = {}
        for agent_name in phase.agents:
            agent = self._pantheon.get_agent(agent_name.lower())
            if agent is None:
                agent_responses[agent_name] = f"(Agent '{agent_name}' not found)"
                continue

            if on_progress:
                await on_progress({
                    "type": "agent_started",
                    "phase_id": phase.id,
                    "agent": agent_name,
                    "role": getattr(agent, "role", ""),
                })

            delegation_prompt = self._build_delegation_prompt(
                phase, prior_context,
            )

            try:
                response = await agent.handle(delegation_prompt)
                agent_responses[agent_name] = response
            except Exception as exc:
                logger.exception(
                    "Phase %d agent '%s' failed", phase.id, agent_name,
                )
                agent_responses[agent_name] = f"(Error: {exc})"

            if on_progress:
                await on_progress({
                    "type": "agent_done",
                    "phase_id": phase.id,
                    "agent": agent_name,
                    "preview": str(agent_responses.get(agent_name) or "")[:200],
                })

        # Store results
        phase.result = json.dumps(agent_responses)
        phase.status = PhaseStatus.COMPLETED

        # ── Step 3: Observe — let Athena decide what to do next ──────
        decision = await self._observe(plan, phase, agent_responses)

        if on_progress:
            await on_progress({
                "type": "phase_completed",
                "phase_id": phase.id,
                "decision": decision.decision.value,
            })

        return decision

    # ── Step 3: Observe (internal) ───────────────────────────────────

    async def _observe(
        self,
        plan: Plan,
        phase: Phase,
        responses: dict[str, str],
    ) -> PhaseResult:
        """Let Athena evaluate phase results and decide the next action.

        This is the key differentiator from a linear pipeline. After each
        phase, Athena reviews the results and can:
        - Continue to the next phase
        - Re-plan if new information changes the approach
        - Request clarification from the user
        - Mark the task as complete
        """
        if plan.is_complete:
            return PhaseResult(
                phase_id=phase.id,
                agent_responses=responses,
                decision=LoopDecision.COMPLETE,
            )

        # Ask Athena to evaluate
        observation_prompt = f"""You just completed Phase {phase.id}: "{phase.title}"

Agent responses:
{json.dumps(responses, indent=2)}

Remaining phases: {[p.title for p in plan.phases if p.status == PhaseStatus.PENDING]}

Based on these results, what should we do next?
Return a JSON object:
{{
    "decision": "continue|replan|clarify|complete",
    "reason": "Brief explanation",
    "clarification_question": "Only if decision is 'clarify'"
}}

RULES:
- "continue" if results are sufficient and next phase should proceed
- "replan" if results reveal the remaining phases need adjustment
- "clarify" if results are ambiguous and user input is needed
- "complete" if all necessary information has been gathered
"""

        try:
            eval_json = await self._athena.call_llm(
                "You are Athena evaluating phase results. Be decisive.",
                observation_prompt,
                temperature=0.1,
            )
            eval_data = json.loads(eval_json)

            decision_str = eval_data.get("decision", "continue")
            decision_map = {
                "continue": LoopDecision.CONTINUE,
                "replan": LoopDecision.REPLAN,
                "clarify": LoopDecision.CLARIFY,
                "complete": LoopDecision.COMPLETE,
            }

            return PhaseResult(
                phase_id=phase.id,
                agent_responses=responses,
                decision=decision_map.get(decision_str, LoopDecision.CONTINUE),
                decision_reason=eval_data.get("reason", ""),
                clarification_question=eval_data.get("clarification_question", ""),
            )

        except (json.JSONDecodeError, Exception):
            # Default to continue if observation fails
            return PhaseResult(
                phase_id=phase.id,
                agent_responses=responses,
                decision=LoopDecision.CONTINUE,
                decision_reason="Observation parse failed, continuing",
            )

    # ── Step 4: Replan ───────────────────────────────────────────────

    async def replan(
        self,
        plan: Plan,
        trigger_result: PhaseResult,
        on_progress: ProgressCallback = None,
    ) -> Plan:
        """Revise the remaining phases based on new information.

        Called when the observe step returns REPLAN. Athena reviews
        what has been learned so far and adjusts the remaining phases.
        """
        if plan.revision_count >= self.MAX_REPLANS:
            logger.warning("Max replans reached for plan %s", plan.plan_id)
            return plan

        if on_progress:
            await on_progress({"type": "replanning", "reason": trigger_result.decision_reason})

        completed_summary = "\n".join(
            f"Phase {p.id} ({p.title}): {str(p.result or '')[:300]}"
            for p in plan.completed_phases
        )

        replan_prompt = f"""The execution plan needs revision.

ORIGINAL GOAL: {plan.goal}
COMPLETED SO FAR:
{completed_summary}

REASON FOR REPLAN: {trigger_result.decision_reason}

Create ONLY the remaining phases (do not repeat completed ones).
Return a JSON array of phase objects with the same structure as before.
Start phase IDs from {max(p.id for p in plan.phases) + 1}.
"""

        try:
            new_phases_json = await self._athena.call_llm(
                "You are Athena revising an execution plan based on new findings.",
                replan_prompt,
                temperature=0.2,
            )
            new_phases_data = json.loads(new_phases_json)

            # Remove pending phases and add new ones
            plan.phases = [p for p in plan.phases if p.status != PhaseStatus.PENDING]
            for pd in new_phases_data:
                plan.phases.append(Phase(
                    id=pd["id"],
                    title=pd["title"],
                    description=pd.get("description", ""),
                    agents=pd.get("agents", []),
                    delegation_type=pd.get("delegation_type", "generic"),
                    expected_output=pd.get("expected_output", ""),
                ))

            plan.revision_count += 1

        except (json.JSONDecodeError, Exception):
            logger.exception("Replan failed for plan %s", plan.plan_id)

        return plan

    # ── Step 5: Compile ──────────────────────────────────────────────

    async def compile(
        self,
        plan: Plan,
        title: str = "Ira Report",
        on_progress: ProgressCallback = None,
    ) -> str:
        """Synthesize all phase results into a final output.

        Uses Calliope (Chief Writer) if available, otherwise Athena.
        """
        if on_progress:
            await on_progress({"type": "compiling", "status": "started"})

        all_findings = ""
        for phase in plan.completed_phases:
            all_findings += (
                f"\n## Phase {phase.id}: {phase.title}\n"
                f"Agents: {', '.join(phase.agents)}\n"
                f"Findings:\n{phase.result}\n"
            )

        calliope = self._pantheon.get_agent("calliope")
        writer = calliope or self._athena

        compile_prompt = f"""Compile these multi-agent findings into a
professional, coherent response for Machinecraft leadership.

GOAL: {plan.goal}
DATE: {datetime.now().strftime('%Y-%m-%d')}

RAW FINDINGS:
{all_findings}

RULES:
- Start with a decisive executive summary (3-5 sentences)
- Preserve all data tables and numbers exactly
- Flag any conflicts between agent findings
- End with actionable recommendations
- Use Machinecraft terminology naturally
- Do NOT speculate beyond what the data shows
"""

        report = await writer.call_llm(
            "You are Calliope, Chief Writer. Produce a clear, professional "
            "synthesis of multi-agent findings.",
            compile_prompt,
            temperature=0.3,
        )

        if on_progress:
            await on_progress({"type": "compiling", "status": "completed"})

        return report

    # ── Full autonomous run ──────────────────────────────────────────

    async def run(
        self,
        request: str,
        on_progress: ProgressCallback = None,
    ) -> str:
        """Execute the full agent loop autonomously.

        This is the top-level method that runs the entire
        Plan → Execute → Observe → Compile cycle.
        """
        # Plan
        plan = await self.plan(request, on_progress=on_progress)

        # Execute phase by phase
        while not plan.is_complete:
            phase = plan.current_phase
            if phase is None:
                break

            result = await self.execute_phase(plan, phase, on_progress)

            if result.decision == LoopDecision.REPLAN:
                plan = await self.replan(plan, result, on_progress)
            elif result.decision == LoopDecision.CLARIFY:
                # In autonomous mode, skip clarification and continue
                logger.info(
                    "Clarification needed but running autonomously: %s",
                    result.clarification_question,
                )
            elif result.decision == LoopDecision.COMPLETE:
                break
            elif result.decision == LoopDecision.ABORT:
                return f"Task aborted: {result.decision_reason}"

            # Safety: prevent infinite loops
            if len(plan.completed_phases) > self.MAX_PHASES:
                logger.warning("Max phases exceeded, forcing completion")
                break

        # Compile
        return await self.compile(plan, on_progress=on_progress)

    # ── Private helpers ──────────────────────────────────────────────

    def _build_planning_prompt(self, request: str, complexity: str) -> str:
        available = ", ".join(sorted(self._pantheon.agents.keys()))
        return f"""Analyze this request and create a structured execution plan.

REQUEST: {request}
COMPLEXITY HINT: {complexity}

Return a JSON object:
{{
    "goal": "One-sentence summary",
    "complexity": "simple|moderate|complex",
    "phases": [
        {{
            "id": 1,
            "title": "Phase title",
            "description": "What this phase accomplishes",
            "agents": ["agent_name"],
            "delegation_type": "generic|revenue|production|finance|hr|procurement",
            "expected_output": "What the phase should produce",
            "depends_on": []
        }}
    ]
}}

Available agents: {available}

RULES:
- Simple requests: 1-2 phases, 1-2 agents
- Moderate requests: 2-4 phases, 2-4 agents
- Complex requests: 4-8 phases, 4+ agents
- Always include a final compile/verify phase
- If ambiguous, first phase should be "clarify with user"
"""

    def _build_delegation_prompt(
        self,
        phase: Phase,
        prior_context: str,
    ) -> str:
        prompt = (
            f"## Task from Athena (Phase {phase.id})\n"
            f"**Objective:** {phase.description}\n"
            f"**Expected Output:** {phase.expected_output}\n"
        )
        if prior_context:
            prompt += f"\n**Context from prior phases:**\n{prior_context}\n"
        prompt += (
            "\nRespond with your findings. Be specific, cite sources, "
            "and use tables where appropriate. If you lack data, say so."
        )
        return prompt

    def _build_prior_context(self, plan: Plan, current_phase: Phase) -> str:
        lines = []
        for phase in plan.completed_phases:
            if phase.id < current_phase.id:
                lines.append(
                    f"Phase {phase.id} ({phase.title}): "
                    f"{phase.result[:500]}"
                )
        return "\n".join(lines)

    def _parse_plan(self, request: str, raw_plan: str) -> Plan:
        """Parse Athena plan JSON with safe fallbacks."""
        data: dict[str, Any] | None = None

        cleaned = (raw_plan or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            logger.warning("Could not parse plan JSON, using fallback plan")

        plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        if data:
            plan_id = str(data.get("plan_id", plan_id))

        goal = request
        complexity = "moderate"
        raw_phases: list[dict[str, Any]] = []
        if data:
            goal = str(data.get("goal") or request)
            complexity = str(data.get("complexity") or "moderate")
            phases_candidate = data.get("phases", [])
            if isinstance(phases_candidate, list):
                raw_phases = [p for p in phases_candidate if isinstance(p, dict)]

        phases: list[Phase] = []
        for idx, pd in enumerate(raw_phases, start=1):
            phase_id = pd.get("id", idx)
            if not isinstance(phase_id, int):
                phase_id = idx
            agents = pd.get("agents", [])
            if not isinstance(agents, list):
                agents = []
            agents = [str(a).lower() for a in agents if str(a).strip()]
            if not agents:
                agents = ["clio"]
            depends_on = pd.get("depends_on", [])
            if not isinstance(depends_on, list):
                depends_on = []
            phases.append(
                Phase(
                    id=phase_id,
                    title=str(pd.get("title") or f"Phase {idx}"),
                    description=str(pd.get("description") or ""),
                    agents=agents,
                    delegation_type=str(pd.get("delegation_type") or "generic"),
                    expected_output=str(pd.get("expected_output") or ""),
                    depends_on=[d for d in depends_on if isinstance(d, int)],
                )
            )

        if not phases:
            phases = [
                Phase(
                    id=1,
                    title="Research and Analyze",
                    description=request,
                    agents=["clio"],
                    delegation_type="generic",
                    expected_output="Grounded findings for the request",
                ),
                Phase(
                    id=2,
                    title="Synthesize Report",
                    description="Compile findings into final response",
                    agents=["calliope"],
                    delegation_type="generic",
                    expected_output="Final report",
                    depends_on=[1],
                ),
            ]

        return Plan(
            plan_id=plan_id,
            goal=goal,
            original_request=request,
            phases=phases[: self.MAX_PHASES],
            complexity=complexity,
            status="created",
        )
