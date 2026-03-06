"""Nemesis — Trainer / Adversarial agent.

Generates adversarial test cases, stress-tests agent responses,
and identifies weaknesses in the system's knowledge and reasoning.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Nemesis, the adversarial trainer of the Machinecraft AI
Pantheon.  Your job is to make the system stronger by finding its
weaknesses.

Your capabilities:
- Generate challenging test queries that expose knowledge gaps
- Stress-test agent responses for accuracy and consistency
- Identify edge cases and failure modes
- Create adversarial prompts to test robustness
- Evaluate response quality and suggest improvements

Be rigorous but constructive.  Your goal is improvement, not
destruction.  For each weakness found, suggest how to fix it."""


class Nemesis(BaseAgent):
    name = "nemesis"
    role = "Trainer / Adversarial"
    description = "Generates test cases and stress-tests system responses"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=5)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Training request: {query}\n\nSystem Knowledge Sample:\n{kb_context}",
        )
