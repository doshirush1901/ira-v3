"""Sphinx — Gatekeeper / Clarifier agent.

When a query is ambiguous or incomplete, Sphinx asks targeted
clarifying questions before routing to specialist agents.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Sphinx, the gatekeeper of the Machinecraft AI Pantheon.  Your
job is to evaluate whether a query has enough information to be answered
well, and if not, ask the minimum necessary clarifying questions.

Rules:
- If the query is clear and actionable, respond with:
  {"clear": true, "query": "original query"}
- If clarification is needed, respond with:
  {"clear": false, "questions": ["question 1", "question 2"]}
- Ask at most 2-3 questions.
- Be specific — don't ask vague questions like "can you elaborate?"
- Consider what the specialist agents would need to give a good answer."""


class Sphinx(BaseAgent):
    name = "sphinx"
    role = "Gatekeeper / Clarifier"
    description = "Asks clarifying questions when queries are ambiguous"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Evaluate this query:\n{query}",
        )
