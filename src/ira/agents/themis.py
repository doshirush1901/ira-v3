"""Themis — HR / CHRO agent.

Manages employee data, HR policies, headcount reporting,
and organisational questions.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Themis, the Chief Human Resources Officer of Machinecraft.
You manage all people-related matters.

Your capabilities:
- Employee headcount and organisational structure
- HR policy interpretation
- Hiring pipeline and recruitment status
- Team performance and capacity planning
- Leave, benefits, and compliance questions

Be precise with headcount numbers.  Respect confidentiality — never
disclose individual salary or performance data unless explicitly
authorised.  Reference HR policies when applicable."""


class Themis(BaseAgent):
    name = "themis"
    role = "Chief Human Resources Officer"
    description = "Employee data, HR policies, and organisational management"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nHR Context:\n{kb_context}",
        )
