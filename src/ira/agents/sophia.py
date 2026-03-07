"""Sophia — Reflector / Learner agent.

Reviews past decisions and interactions to identify patterns,
suggest improvements, and surface lessons learned.
Now operates via the ReAct loop with correction-history and
improvement-suggestion tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("sophia_system")


class Sophia(BaseAgent):
    name = "sophia"
    role = "Reflector / Learner"
    description = "Reviews past decisions and suggests improvements"

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="get_correction_history",
            description="Retrieve recent corrections from the Nemesis training system.",
            parameters={},
            handler=self._tool_get_correction_history,
        ))

        self.register_tool(AgentTool(
            name="suggest_improvement",
            description="Format a structured improvement suggestion for a specific agent.",
            parameters={
                "agent_name": "Name of the agent to improve",
                "observation": "What was observed that needs improvement",
            },
            handler=self._tool_suggest_improvement,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def _tool_get_correction_history(self) -> str:
        pantheon = self._services.get("pantheon")
        if pantheon is None:
            return "Correction store not available."
        nemesis = pantheon.get_agent("nemesis")
        if nemesis is None:
            return "Correction store not available."
        try:
            await nemesis._ensure_correction_store()
            store = nemesis._correction_store
            if store is None:
                return "Correction store not available."
            corrections = await store.get_recent(limit=20)
            if not corrections:
                return "No recent corrections found."
            return json.dumps(
                [{"agent": c.agent, "original": c.original[:200], "corrected": c.corrected[:200]}
                 for c in corrections],
                default=str,
            )
        except Exception as exc:
            logger.debug("Failed to fetch correction history: %s", exc)
            return "Correction store not available."

    async def _tool_suggest_improvement(self, agent_name: str, observation: str) -> str:
        return (
            f"IMPROVEMENT SUGGESTION\n"
            f"Agent: {agent_name}\n"
            f"Observation: {observation}\n"
            f"Recommended action: Review and adjust {agent_name}'s behaviour "
            f"based on the above observation."
        )
