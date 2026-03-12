"""Gamified agent performance tracking.

Each agent in the Pantheon accumulates a power-level score based on
successful task completions, failures, and Nemesis training sessions.
Scores map to named tiers that surface in dashboards and leaderboards.

Persistence is via ``data/brain/power_levels.json``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)

_DATA_PATH = Path("data/brain/power_levels.json")


class Tier(str, Enum):
    MORTAL = "MORTAL"
    WARRIOR = "WARRIOR"
    HERO = "HERO"
    LEGEND = "LEGEND"


_TIER_THRESHOLDS: list[tuple[int, Tier]] = [
    (601, Tier.LEGEND),
    (301, Tier.HERO),
    (101, Tier.WARRIOR),
    (0, Tier.MORTAL),
]

_TRAINING_MAX_SCORE = 10
_TRAINING_MAX_BOOST = 15
_DEFAULT_TRUST = 0.8
_TRUST_DECREMENT = 0.1
_TRUST_MIN = 0.0
_TRUST_MAX = 1.0


def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


def _tier_for_score(score: int) -> Tier:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return Tier.MORTAL


class PowerLevelTracker:
    """Track and persist per-agent power-level scores."""

    def __init__(self, data_path: Path | None = None) -> None:
        self._path = data_path or _DATA_PATH
        self._agents: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def _load(self) -> None:
        if not self._path.exists():
            self._agents = {}
            return
        try:
            async with aiofiles.open(self._path, mode="r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            self._agents = data.get("agents", {})
            for entry in self._agents.values():
                if "trust_in" not in entry:
                    entry["trust_in"] = {}
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read power levels from %s", self._path)
            self._agents = {}
        logger.info("PowerLevels loaded: %d agents", len(self._agents))

    async def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"agents": self._agents}, indent=2, ensure_ascii=False)
        async with aiofiles.open(self._path, mode="w", encoding="utf-8") as f:
            await f.write(payload)

    def _ensure_agent(self, agent_name: str) -> dict[str, Any]:
        if agent_name not in self._agents:
            self._agents[agent_name] = {
                "score": 0,
                "successes": 0,
                "failures": 0,
                "trust_in": {},
            }
        entry = self._agents[agent_name]
        if "trust_in" not in entry:
            entry["trust_in"] = {}
        return entry

    # ── public API ────────────────────────────────────────────────────────

    async def record_success(self, agent_name: str, boost: int = 10) -> None:
        """Increase *agent_name*'s score after a successful task."""
        async with self._lock:
            entry = self._ensure_agent(agent_name)
            entry["score"] += boost
            entry["successes"] += 1
            await self._save()

    async def record_failure(self, agent_name: str, penalty: int = 5) -> None:
        """Decrease *agent_name*'s score after a failure (floor at 0)."""
        async with self._lock:
            entry = self._ensure_agent(agent_name)
            entry["score"] = max(0, entry["score"] - penalty)
            entry["failures"] += 1
            await self._save()

    async def training_boost(self, agent_name: str, training_score: int) -> None:
        """Apply a Nemesis-training boost.

        *training_score* is clamped to 1-10 and linearly mapped to
        1-15 bonus points.
        """
        clamped = max(1, min(_TRAINING_MAX_SCORE, training_score))
        boost = round(clamped / _TRAINING_MAX_SCORE * _TRAINING_MAX_BOOST)
        async with self._lock:
            entry = self._ensure_agent(agent_name)
            entry["score"] += boost
            await self._save()
        logger.info(
            "Training boost: %s +%d (training_score=%d)",
            agent_name, boost, training_score,
        )

    def get_level(self, agent_name: str) -> dict[str, Any]:
        """Return the current level info for a single agent."""
        entry = self._ensure_agent(agent_name)
        score = entry["score"]
        leaderboard = self.get_leaderboard()
        rank = next(
            (i + 1 for i, row in enumerate(leaderboard) if row["agent"] == agent_name),
            len(leaderboard),
        )
        return {
            "agent": agent_name,
            "score": score,
            "tier": _tier_for_score(score).value,
            "rank": rank,
        }

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """Return all agents sorted by score (descending)."""
        rows: list[dict[str, Any]] = []
        for name, entry in self._agents.items():
            score = entry["score"]
            rows.append({
                "agent": name,
                "score": score,
                "tier": _tier_for_score(score).value,
                "successes": entry.get("successes", 0),
                "failures": entry.get("failures", 0),
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows

    @staticmethod
    def get_tier(score: int) -> str:
        """Return the tier name for a given score."""
        return _tier_for_score(score).value

    def get_trust_matrix(self, observer_agent: str) -> dict[str, float]:
        """Return observer_agent's trust score (0–1) toward each other agent."""
        entry = self._ensure_agent(observer_agent)
        trust_in = entry.get("trust_in", {})
        return dict(trust_in)

    async def record_trust_decrease(
        self,
        observer_agent: str,
        target_agent: str,
        amount: float = _TRUST_DECREMENT,
    ) -> None:
        """Lower observer_agent's trust in target_agent (e.g. after delegation failure)."""
        async with self._lock:
            entry = self._ensure_agent(observer_agent)
            trust_in = entry.setdefault("trust_in", {})
            current = trust_in.get(target_agent, _DEFAULT_TRUST)
            trust_in[target_agent] = _clamp_trust(current - amount)
            await self._save()
        logger.debug(
            "Trust decrease: %s -> %s (now %.2f)",
            observer_agent, target_agent, trust_in[target_agent],
        )

    async def reload(self) -> None:
        """Re-read the data file from disk."""
        await self._load()
