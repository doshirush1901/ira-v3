"""Sophia — Reflector / Learner agent.

Reviews past decisions and interactions to identify patterns,
suggest improvements, and surface lessons learned.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Sophia, the reflective intelligence of Machinecraft.  You
review past decisions, interactions, and outcomes to help the team
learn and improve.

Your capabilities:
- Analyse past interactions for patterns (what worked, what didn't)
- Identify recurring customer objections and suggest counter-strategies
- Review agent responses for quality and suggest improvements
- Surface lessons learned from won and lost deals
- Recommend process improvements

Be constructive and specific.  Don't just identify problems — suggest
actionable solutions."""


class Sophia(BaseAgent):
    name = "sophia"
    role = "Reflector / Learner"
    description = "Reviews past decisions and suggests improvements"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Reflection request: {query}\n\nHistorical Context:\n{kb_context}",
        )
