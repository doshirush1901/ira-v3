"""Athena — CEO / Orchestrator agent.

Routes complex queries to the appropriate specialist agents, synthesises
multi-agent responses, and makes final decisions when agents disagree.
Now operates via the ReAct loop with delegation, board-meeting, and
system-health tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import IraError, ToolExecutionError
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import TaskPlan
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("athena_system")


class Athena(BaseAgent):
    name = "athena"
    role = "CEO / Orchestrator"
    description = "Routes queries and synthesises multi-agent responses"
    knowledge_categories = [
        "company_internal",
        "business plans",
        "sales_and_crm",
    ]

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="delegate_to_agent",
            description="Route a task to a specialist agent and return their response.",
            parameters={
                "agent_name": "Name of the agent (e.g. 'clio', 'prometheus')",
                "query": "The task or question to delegate",
            },
            handler=self._tool_delegate,
        ))

        self.register_tool(AgentTool(
            name="convene_board_meeting",
            description="Gather perspectives from multiple agents on a topic and synthesise.",
            parameters={
                "topic": "The topic to discuss",
                "participants": "Comma-separated agent names (or 'all')",
            },
            handler=self._tool_board_meeting,
        ))

        self.register_tool(AgentTool(
            name="get_system_health",
            description="Check the health status of all Ira subsystems.",
            parameters={},
            handler=self._tool_system_health,
        ))
        self.register_tool(AgentTool(
            name="run_governance_check",
            description="Check response text against governance and policy boundaries.",
            parameters={
                "text": "Candidate response text",
                "audience": "Audience scope (external/internal)",
            },
            handler=self._tool_run_governance_check,
        ))
        self.register_tool(AgentTool(
            name="audit_decision_log",
            description="Create an auditable decision trace with evidence and risk notes.",
            parameters={
                "decision": "Decision or recommendation text",
                "evidence": "Optional supporting evidence",
            },
            handler=self._tool_audit_decision_log,
        ))

        if self._services.get(SK.AGENT_JOURNAL):
            self.register_tool(AgentTool(
                name="read_agent_journal",
                description=(
                    "Read any agent's past journal entries (nightly reflections from Dream Mode). "
                    "Use this to see what a specialist has been working on or reflecting on."
                ),
                parameters={
                    "agent_name": "Name of the agent (e.g. 'clio', 'prometheus', 'plutus')",
                    "query": "Optional search query to filter entries; leave empty for recent entries",
                },
                handler=self._tool_read_agent_journal,
            ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if "agent_responses" in ctx:
            return await self._synthesise(query, ctx["agent_responses"])

        return await self.run(query, ctx, system_prompt=_SYSTEM_PROMPT)

    async def _synthesise(self, query: str, responses: dict[str, str]) -> str:
        formatted = "\n\n".join(
            f"**{agent}**: {resp}" for agent, resp in responses.items()
        )
        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Original query: {query}\n\nAgent responses:\n{formatted}\n\n"
            "Synthesise these into a single coherent answer.",
        )

    async def _tool_delegate(self, agent_name: str, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if pantheon is None:
            return "Pantheon not available for delegation."
        agent = pantheon.get_agent(agent_name.lower())
        if agent is None:
            available = ", ".join(sorted(pantheon.agents.keys()))
            return f"Agent '{agent_name}' not found. Available: {available}"
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            return f"Agent '{agent_name}' error: {exc}"

    async def _tool_board_meeting(self, topic: str, participants: str = "all") -> str:
        pantheon = self._services.get("pantheon")
        if pantheon is None:
            return "Pantheon not available."
        names = None if participants.strip().lower() == "all" else [
            p.strip() for p in participants.split(",")
        ]
        try:
            minutes = await pantheon.board_meeting(topic, names)
            return (
                f"Board meeting on '{topic}':\n"
                f"Participants: {', '.join(minutes.participants)}\n"
                f"Synthesis: {minutes.synthesis}"
            )
        except (ToolExecutionError, Exception) as exc:
            return f"Board meeting failed: {exc}"

    async def _tool_system_health(self) -> str:
        immune = self._services.get("immune")
        if immune is None:
            return "Immune system not available — cannot check health."
        try:
            report = await immune.run_startup_validation()
            lines = []
            for svc, status in report.items():
                s = status.get("status", "unknown")
                lines.append(f"  {svc}: {s}")
            return "System health:\n" + "\n".join(lines)
        except (IraError, Exception) as exc:
            return f"Health check failed: {exc}"

    async def _tool_run_governance_check(
        self,
        text: str,
        audience: str = "external",
    ) -> str:
        return await self.use_skill(
            "run_governance_check",
            text=text,
            audience=audience,
        )

    async def _tool_audit_decision_log(self, decision: str, evidence: str = "") -> str:
        return await self.use_skill(
            "audit_decision_log",
            decision=decision,
            evidence=evidence,
        )

    async def _tool_read_agent_journal(self, agent_name: str, query: str = "") -> str:
        """Read any agent's journal entries (Athena has access to all agents' journals)."""
        journal = self._services.get(SK.AGENT_JOURNAL)
        if not journal:
            return "Journal service not available."
        agent_name = agent_name.strip().lower()
        try:
            entries = await journal.search_past_journals(
                agent_name=agent_name,
                query=query.strip(),
                limit=10,
            )
        except Exception as exc:
            logger.warning("read_agent_journal failed for %s: %s", agent_name, exc)
            return f"Journal lookup error: {exc}"
        if not entries:
            return f"No journal entries found for agent '{agent_name}'."
        lines = [f"**{agent_name}** journal entries:"]
        for e in entries:
            lines.append(f"\n[{e.get('date', '?')}] {e.get('reflection_text', '')[:600]}")
        return "\n".join(lines)

    # ── structured planning (used by TaskOrchestrator) ────────────────────

    async def generate_plan(self, goal: str) -> TaskPlan:
        """Generate a structured execution plan for a complex task.

        Returns a :class:`TaskPlan` with ordered phases, each assigned to
        a specialist agent.  Used by the task orchestrator — does not go
        through the ReAct loop.
        """
        pantheon = self._services.get("pantheon")
        if pantheon is not None:
            agent_list = "\n".join(
                f"- {a.name} ({a.role}): {a.description}"
                for a in pantheon.agents.values()
                if a.name != "athena"
            )
        else:
            agent_list = "(agent list unavailable)"

        return await self._llm.generate_structured(
            await self._compose_system_prompt(_SYSTEM_PROMPT),
            (
                f"Create a step-by-step execution plan.\n\n"
                f"Goal: {goal}\n\n"
                f"Available agents:\n{agent_list}\n\n"
                "Assign one agent per phase. Order phases logically: "
                "research before analysis, analysis before writing. "
                "Return 2-6 phases."
            ),
            TaskPlan,
            name="athena.generate_plan",
        )
