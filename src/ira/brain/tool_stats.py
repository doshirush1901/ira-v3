"""In-memory tool call success/failure tracking for observability.

Used by the dashboard to show per-agent (and per-tool) success rates.
No persistence; resets on process restart.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class ToolStatsTracker:
    """Tracks tool call outcomes per agent and per tool for success-rate reporting."""

    def __init__(self) -> None:
        # (agent_name, tool_name) -> {"successes": int, "failures": int}
        self._counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"successes": 0, "failures": 0}
        )
        self._lock = asyncio.Lock()

    async def record_tool_call(self, agent_name: str, tool_name: str, success: bool) -> None:
        """Record one tool invocation outcome."""
        async with self._lock:
            key = (agent_name, tool_name)
            if success:
                self._counts[key]["successes"] += 1
            else:
                self._counts[key]["failures"] += 1

    async def get_tool_success_rates(
        self,
        *,
        by_tool: bool = True,
    ) -> list[dict[str, Any]]:
        """Return success rate stats.

        If by_tool is True, each row is (agent, tool) with total, successes, failures, rate.
        If by_tool is False, each row is agent-only (aggregated across tools).
        """
        async with self._lock:
            if by_tool:
                rows: list[dict[str, Any]] = []
                for (agent_name, tool_name), counts in self._counts.items():
                    total = counts["successes"] + counts["failures"]
                    if total == 0:
                        continue
                    rows.append({
                        "agent": agent_name,
                        "tool": tool_name,
                        "total": total,
                        "successes": counts["successes"],
                        "failures": counts["failures"],
                        "rate": round(counts["successes"] / total, 2),
                    })
                return sorted(rows, key=lambda r: (r["agent"], r["tool"]))
            # Aggregate by agent
            agent_totals: dict[str, dict[str, int | float]] = defaultdict(
                lambda: {"total": 0, "successes": 0, "failures": 0}
            )
            for (agent_name, _), counts in self._counts.items():
                agent_totals[agent_name]["total"] += counts["successes"] + counts["failures"]
                agent_totals[agent_name]["successes"] += counts["successes"]
                agent_totals[agent_name]["failures"] += counts["failures"]
            rows = []
            for agent_name, data in agent_totals.items():
                total = data["total"]
                if total == 0:
                    continue
                rows.append({
                    "agent": agent_name,
                    "tool": "(all)",
                    "total": total,
                    "successes": data["successes"],
                    "failures": data["failures"],
                    "rate": round(data["successes"] / total, 2),
                })
            return sorted(rows, key=lambda r: r["agent"])
