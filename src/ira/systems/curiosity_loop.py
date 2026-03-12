"""Intrinsic curiosity — boredom-driven inter-agent exploration.

When the system is idle, boredom (EndocrineSystem) rises. When it exceeds
a threshold, the loop wakes a random agent and prompts them to explore
gaps and ask other agents questions. MessageBus carries the resulting
dialogue; ProceduralMemory and LongTermMemory can absorb new facts from
tool use (store_memory, etc.). Boredom resets after the cycle.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from ira.data.models import AgentMessage

logger = logging.getLogger(__name__)

_BOREDOM_THRESHOLD = 0.8
_TICK_IDLE_AMOUNT = 0.05
_IDLE_CHECK_INTERVAL_SEC = 3600

_BOREDOM_PROMPT = (
    "You are bored. Look at your recent work and domain. "
    "What don't you know? Ask another agent a question (use ask_agent) to learn something useful. "
    "Then briefly summarise what you learned."
)


class CuriosityLoop:
    """Listens for IdleEvent (boredom > threshold) and runs a curiosity cycle."""

    def __init__(
        self,
        endocrine: Any,
        bus: Any,
        pantheon: Any,
        *,
        idle_interval_sec: float = _IDLE_CHECK_INTERVAL_SEC,
        boredom_threshold: float = _BOREDOM_THRESHOLD,
    ) -> None:
        self._endocrine = endocrine
        self._bus = bus
        self._pantheon = pantheon
        self._idle_interval_sec = idle_interval_sec
        self._boredom_threshold = boredom_threshold
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Subscribe to curiosity_loop and start the idle-tick background task."""
        if self._running:
            return
        self._bus.subscribe("curiosity_loop", self._handle_idle)
        self._running = True
        self._task = asyncio.create_task(self._idle_tick_loop())
        logger.info("CuriosityLoop started (idle check every %.0fs)", self._idle_interval_sec)

    async def stop(self) -> None:
        """Stop the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("CuriosityLoop stopped")

    async def _idle_tick_loop(self) -> None:
        """Every interval, increase boredom and emit IdleEvent if over threshold."""
        while self._running:
            try:
                await asyncio.sleep(self._idle_interval_sec)
                if not self._running:
                    break
                self._endocrine.tick_idle(_TICK_IDLE_AMOUNT)
                status = self._endocrine.get_status()
                boredom = status.get("boredom", 0.0)
                if boredom >= self._boredom_threshold:
                    await self._bus.send(
                        "sensory",
                        "curiosity_loop",
                        "idle",
                        {"event": "IdleEvent", "boredom": boredom},
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("CuriosityLoop idle tick failed", exc_info=True)

    async def run_one_cycle(self) -> None:
        """Run one curiosity cycle (e.g. from dream mode). Resets boredom after."""
        try:
            await self._run_curiosity_cycle()
        finally:
            try:
                self._endocrine.reset_boredom()
            except Exception:
                logger.debug("reset_boredom failed", exc_info=True)

    async def _handle_idle(self, message: AgentMessage) -> None:
        """Run one curiosity cycle: wake a random agent, prompt, then reset boredom."""
        if message.query != "idle":
            return
        await self.run_one_cycle()

    async def _run_curiosity_cycle(self) -> None:
        """Pick a random agent (excluding athena) and run the boredom prompt."""
        agents = [
            name for name in self._pantheon.agents
            if name != "athena"
        ]
        if not agents:
            return
        name = random.choice(agents)
        agent = self._pantheon.get_agent(name)
        if agent is None:
            return
        ctx: dict[str, Any] = {
            "services": {
                "pantheon": self._pantheon,
            },
            "_curiosity": True,
        }
        try:
            response = await agent.handle(_BOREDOM_PROMPT, ctx)
            logger.info(
                "Curiosity cycle: %s responded (%d chars)",
                name, len(response or ""),
            )
        except Exception:
            logger.warning("Curiosity cycle: %s failed", name, exc_info=True)
