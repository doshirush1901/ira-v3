"""Nemesis — Trainer / Adversarial agent.

Generates adversarial training scenarios, stress-tests specialist agents,
and feeds the results back through the :class:`~ira.systems.learning_hub.LearningHub`
to close the improvement loop.

The primary tool is :meth:`create_training_scenario`, which:

1. Queries the LearningHub for areas with low performance scores.
2. Synthesises a challenging hypothetical query for that area.
3. Routes the query to the appropriate specialist agent.
4. Generates an ideal reference answer via a high-quality LLM call.
5. Scores the agent's response against the ideal and logs the result.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# ── Agent ↔ domain mapping ───────────────────────────────────────────────
# Used to select which agent should handle a scenario in a given domain.

_DOMAIN_AGENTS: dict[str, str] = {
    "sales": "prometheus",
    "pricing": "plutus",
    "finance": "plutus",
    "marketing": "hermes",
    "production": "hephaestus",
    "hr": "themis",
    "research": "clio",
    "writing": "calliope",
    "forecasting": "tyche",
}

# ── LLM prompts ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = load_prompt("nemesis_system")

_SCENARIO_GEN_PROMPT = load_prompt("nemesis_scenario_gen")

_SCENARIO_GEN_FALLBACK_PROMPT = load_prompt("nemesis_scenario_gen_fallback")

_IDEAL_RESPONSE_PROMPT = load_prompt("nemesis_ideal_response")

_SCORING_PROMPT = load_prompt("nemesis_scoring")


@dataclass
class TrainingResult:
    """Outcome of a single training scenario."""

    scenario_id: str = field(default_factory=lambda: str(uuid4()))
    domain: str = ""
    target_agent: str = ""
    test_query: str = ""
    agent_response: str = ""
    ideal_response: str = ""
    scores: dict[str, Any] = field(default_factory=dict)
    overall_score: int = 0


class Nemesis(BaseAgent):
    name = "nemesis"
    role = "Trainer / Adversarial"
    description = "Generates training scenarios and stress-tests agent responses"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._learning_hub: Any | None = None
        self._peer_agents: dict[str, BaseAgent] = {}

    def configure(
        self,
        learning_hub: Any,
        peer_agents: dict[str, BaseAgent],
    ) -> None:
        """Wire Nemesis to the LearningHub and the agent roster.

        Called after Pantheon construction so Nemesis can reach its peers.
        """
        self._learning_hub = learning_hub
        self._peer_agents = peer_agents

    # ── BaseAgent interface ──────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        num_scenarios = ctx.get("num_scenarios", 3)

        if self._learning_hub is None or not self._peer_agents:
            kb_results = await self.search_knowledge(query, limit=5)
            kb_context = self._format_context(kb_results)
            return await self.call_llm(
                _SYSTEM_PROMPT,
                f"Training request: {query}\n\nSystem Knowledge Sample:\n{kb_context}",
            )

        results = await self.run_training_cycle(num_scenarios=num_scenarios)
        return self._format_training_report(results)

    # ── training cycle ───────────────────────────────────────────────────

    async def run_training_cycle(
        self,
        num_scenarios: int = 3,
    ) -> list[TrainingResult]:
        """Run a full training cycle: generate scenarios, test agents, score."""
        scenarios = await self._generate_scenarios(num_scenarios)
        results: list[TrainingResult] = []

        for scenario in scenarios:
            result = await self.create_training_scenario(scenario)
            results.append(result)

        return results

    async def create_training_scenario(
        self,
        scenario: dict[str, Any],
    ) -> TrainingResult:
        """Execute a single training scenario end-to-end.

        1. Pick the target agent for the scenario's domain.
        2. Send the test query to that agent.
        3. Generate an ideal reference response.
        4. Score the agent's response against the ideal.
        5. Log the result through the LearningHub.
        """
        test_query = scenario.get("test_query", "")
        domain = scenario.get("domain", "research")
        agent_name = _DOMAIN_AGENTS.get(domain, "clio")

        result = TrainingResult(
            domain=domain,
            target_agent=agent_name,
            test_query=test_query,
        )

        agent = self._peer_agents.get(agent_name)
        if agent is None:
            result.agent_response = f"(Agent '{agent_name}' not available)"
            result.overall_score = 0
            return result

        try:
            result.agent_response = await agent.handle(test_query)
        except Exception:
            logger.exception("Agent '%s' failed on training query", agent_name)
            result.agent_response = f"(Agent '{agent_name}' raised an error)"
            result.overall_score = 0
            return result

        result.ideal_response = await self.call_llm(
            _IDEAL_RESPONSE_PROMPT,
            test_query,
            temperature=0.2,
        )

        scoring_input = (
            f"QUERY:\n{test_query}\n\n"
            f"AGENT RESPONSE:\n{result.agent_response[:4000]}\n\n"
            f"IDEAL RESPONSE:\n{result.ideal_response[:4000]}"
        )
        raw_scores = await self.call_llm(
            _SCORING_PROMPT,
            scoring_input,
            temperature=0.0,
        )
        result.scores = self._safe_parse(raw_scores)
        result.overall_score = result.scores.get("overall", 5)

        if self._learning_hub is not None:
            try:
                interaction = await self._learning_hub._crm.create_interaction(
                    contact_id=str(uuid4()),
                    channel="CLI",
                    direction="INBOUND",
                    subject=test_query[:500],
                    content=result.agent_response,
                )
                await self._learning_hub.process_feedback(
                    interaction_id=str(interaction.id),
                    feedback_score=result.overall_score,
                    correction=(
                        result.ideal_response if result.overall_score <= 5 else None
                    ),
                )
            except Exception:
                logger.exception("Failed to log training result to LearningHub")

        logger.info(
            "Training scenario: agent=%s domain=%s score=%d/10",
            agent_name,
            domain,
            result.overall_score,
        )
        return result

    # ── scenario generation ──────────────────────────────────────────────

    async def _generate_scenarios(
        self,
        count: int,
    ) -> list[dict[str, Any]]:
        """Build a list of training scenarios.

        Prefers targeting known weak areas from the LearningHub.  Falls
        back to LLM-generated scenarios when no feedback history exists.
        """
        scenarios: list[dict[str, Any]] = []

        if self._learning_hub is not None:
            weak_areas = self._learning_hub.get_weak_areas(limit=count)
            for area in weak_areas:
                gap = area.get("gap_analysis", {})
                description = gap.get("description", "general weakness")
                gap_type = gap.get("gap_type", "UNKNOWN")

                prompt = (
                    f"WEAK AREA:\n"
                    f"Type: {gap_type}\n"
                    f"Description: {description}\n"
                    f"Original score: {area.get('score', '?')}/10"
                )
                raw = await self.call_llm(
                    _SCENARIO_GEN_PROMPT, prompt, temperature=0.7,
                )
                parsed = self._safe_parse(raw)
                if isinstance(parsed, dict) and "test_query" in parsed:
                    scenarios.append(parsed)

        remaining = count - len(scenarios)
        if remaining > 0:
            raw = await self.call_llm(
                _SCENARIO_GEN_FALLBACK_PROMPT,
                f"Generate {remaining} diverse training scenarios.",
                temperature=0.8,
            )
            parsed = self._safe_parse(raw)
            if isinstance(parsed, list):
                for item in parsed[:remaining]:
                    if isinstance(item, dict) and "test_query" in item:
                        scenarios.append(item)

        if not scenarios:
            scenarios.append({
                "test_query": "What is the lead time for a PF1500 CNC machine order to Saudi Arabia?",
                "domain": "sales",
                "difficulty": "medium",
                "rationale": "Fallback scenario covering sales + production + logistics.",
            })

        return scenarios[:count]

    # ── formatting ───────────────────────────────────────────────────────

    def _format_training_report(self, results: list[TrainingResult]) -> str:
        if not results:
            return "No training scenarios were executed."

        lines = ["# Training Cycle Report\n"]
        total_score = 0

        for i, r in enumerate(results, 1):
            total_score += r.overall_score
            status = "PASS" if r.overall_score >= 7 else "WARN" if r.overall_score >= 4 else "FAIL"
            lines.append(f"## Scenario {i}: [{status}] {r.domain} → {r.target_agent}")
            lines.append(f"**Query:** {r.test_query}")
            lines.append(f"**Score:** {r.overall_score}/10\n")

            strengths = r.scores.get("strengths", [])
            if strengths:
                lines.append("**Strengths:**")
                for s in strengths:
                    lines.append(f"- {s}")

            weaknesses = r.scores.get("weaknesses", [])
            if weaknesses:
                lines.append("\n**Weaknesses:**")
                for w in weaknesses:
                    lines.append(f"- {w}")

            suggestion = r.scores.get("improvement_suggestion")
            if suggestion:
                lines.append(f"\n**Suggestion:** {suggestion}")

            lines.append("")

        avg = total_score / len(results) if results else 0
        lines.append(f"---\n**Average score:** {avg:.1f}/10 across {len(results)} scenarios")

        return "\n".join(lines)

    @staticmethod
    def _safe_parse(raw: str) -> Any:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return {"raw_response": raw}
