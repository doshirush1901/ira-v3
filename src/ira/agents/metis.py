"""Metis — Stability Monitor agent.

Tracks response quality across Cursor sessions and determines when
the system has reached a stable mode.  Can auto-adjust max_rounds
(react_max_iterations) when quality is below threshold.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("metis_system")
_STABILITY_PATH = Path("data/brain/stability_scores.json")
_STABILITY_THRESHOLD = 75
_CONSECUTIVE_REQUIRED = 10
_WINDOW_SIZE = 20
_REPORT_PROBABILITY = 0.1


class Metis(BaseAgent):
    name = "metis"
    role = "Stability Monitor"
    description = "Tracks response quality and determines when Ira is stable in Cursor"
    knowledge_categories = []
    timeout = 15

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="score_response",
            description="Score a response on quality (0-100).",
            parameters={
                "agents_succeeded": "Number of agents that succeeded (no timeout/error)",
                "agents_total": "Total number of agents invoked",
                "has_sources": "Whether sources were cited (true/false)",
                "response_length": "Length of the response in characters",
                "had_warnings": "Whether provenance/DLP warnings were added (true/false)",
            },
            handler=self._tool_score_response,
        ))

        self.register_tool(AgentTool(
            name="get_stability_status",
            description="Check current stability score, max_rounds, and stable mode status.",
            parameters={},
            handler=self._tool_get_status,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    def _load_state(self) -> dict[str, Any]:
        if _STABILITY_PATH.exists():
            try:
                return json.loads(_STABILITY_PATH.read_text())
            except Exception:
                pass
        return {
            "scores": [],
            "consecutive_above": 0,
            "stable": False,
            "max_rounds": 8,
            "last_updated": 0,
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        _STABILITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STABILITY_PATH.write_text(json.dumps(state, indent=2))

    def _compute_score(
        self,
        agents_succeeded: int,
        agents_total: int,
        has_sources: bool,
        response_length: int,
        had_warnings: bool,
    ) -> int:
        score = 0
        if agents_total > 0 and agents_succeeded == agents_total:
            score += 30
        elif agents_total > 0:
            score += int(30 * (agents_succeeded / agents_total))
        if has_sources:
            score += 20
        if response_length > 200:
            score += 30
        elif response_length > 50:
            score += 15
        if not had_warnings:
            score += 10
        score += 10  # no user correction (assumed at scoring time)
        return min(100, score)

    async def score_and_track(
        self,
        agents_used: list[str],
        raw_response: str,
    ) -> dict[str, Any]:
        """Score a response and update stability tracking. Returns status dict."""
        agents_total = len(agents_used)
        agents_succeeded = sum(
            1 for a in agents_used
            if a not in ("timeout",) and f"timed out" not in raw_response
        )
        has_sources = any(
            marker in raw_response
            for marker in ("source:", "Source:", "Sources:", "Confidence:", "thread_id")
        )
        had_warnings = any(
            marker in raw_response
            for marker in ("Provenance note:", "Content note:", "could not be traced")
        )

        score = self._compute_score(
            agents_succeeded, agents_total, has_sources, len(raw_response), had_warnings,
        )

        state = self._load_state()
        state["scores"].append({"score": score, "timestamp": time.time()})
        state["scores"] = state["scores"][-_WINDOW_SIZE:]
        state["last_updated"] = time.time()

        avg = sum(s["score"] for s in state["scores"]) / len(state["scores"])

        if avg >= _STABILITY_THRESHOLD:
            state["consecutive_above"] += 1
        else:
            state["consecutive_above"] = 0

        should_announce_stable = (
            not state["stable"]
            and state["consecutive_above"] >= _CONSECUTIVE_REQUIRED
        )

        should_report = random.random() < _REPORT_PROBABILITY

        from ira.config import get_settings
        current_max = get_settings().app.react_max_iterations
        state["max_rounds"] = current_max

        self._save_state(state)

        return {
            "score": score,
            "rolling_avg": round(avg, 1),
            "consecutive_above": state["consecutive_above"],
            "stable": state["stable"],
            "should_announce_stable": should_announce_stable,
            "should_report": should_report,
            "max_rounds": current_max,
        }

    async def confirm_stable(self) -> None:
        """User confirmed stability. Mark as stable."""
        state = self._load_state()
        state["stable"] = True
        self._save_state(state)
        logger.info("METIS | Stability confirmed by user at max_rounds=%d", state["max_rounds"])

    async def reject_stable(self) -> None:
        """User rejected stability. Increase max_rounds by 20%."""
        state = self._load_state()
        state["consecutive_above"] = 0

        from ira.config import get_settings
        current = get_settings().app.react_max_iterations
        new_max = max(current + 1, int(current * 1.2))
        state["max_rounds"] = new_max
        self._save_state(state)
        logger.info("METIS | Stability rejected. max_rounds %d → %d", current, new_max)

    async def _tool_score_response(
        self,
        agents_succeeded: str = "0",
        agents_total: str = "0",
        has_sources: str = "false",
        response_length: str = "0",
        had_warnings: str = "false",
    ) -> str:
        score = self._compute_score(
            int(agents_succeeded),
            int(agents_total),
            has_sources.lower() == "true",
            int(response_length),
            had_warnings.lower() == "true",
        )
        return f"Response quality score: {score}/100"

    async def _tool_get_status(self) -> str:
        state = self._load_state()
        scores = state.get("scores", [])
        avg = sum(s["score"] for s in scores) / len(scores) if scores else 0
        return (
            f"Stability status:\n"
            f"- Rolling average: {avg:.1f}/100 (last {len(scores)} requests)\n"
            f"- Consecutive above {_STABILITY_THRESHOLD}: {state.get('consecutive_above', 0)}\n"
            f"- Stable: {state.get('stable', False)}\n"
            f"- Max rounds: {state.get('max_rounds', 8)}"
        )
