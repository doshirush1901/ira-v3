"""Async pub/sub message bus for inter-agent communication.

Every agent publishes and receives :class:`~ira.data.models.AgentMessage`
objects through the bus.  Messages can be directed (to a specific agent)
or broadcast (to all subscribers).  A full message log is kept for
debugging and auditing.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from ira.data.models import AgentMessage
from ira.exceptions import ToolExecutionError

logger = logging.getLogger(__name__)

MessageHandler = Callable[[AgentMessage], Awaitable[None]]

_BROADCAST = "__broadcast__"


class MessageBus:
    """Async message bus using :class:`asyncio.Queue`."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=maxsize)
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._log: deque[AgentMessage] = deque(maxlen=1000)
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ── subscription ─────────────────────────────────────────────────────

    def subscribe(self, agent_name: str, handler: MessageHandler) -> None:
        """Register *handler* to receive messages addressed to *agent_name*."""
        self._handlers[agent_name].append(handler)
        logger.debug("Subscribed handler for '%s'", agent_name)

    def subscribe_broadcast(self, handler: MessageHandler) -> None:
        """Register *handler* to receive all broadcast messages."""
        self._handlers[_BROADCAST].append(handler)

    # ── publishing ───────────────────────────────────────────────────────

    async def publish(self, message: AgentMessage) -> None:
        """Enqueue a message for delivery."""
        await self._queue.put(message)
        logger.debug(
            "Published message from '%s' to '%s'",
            message.from_agent,
            message.to_agent,
        )

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Convenience: build and publish an :class:`AgentMessage`."""
        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            query=query,
            context=context or {},
        )
        await self.publish(msg)

    async def broadcast(
        self,
        from_agent: str,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Publish a message to all broadcast subscribers."""
        await self.send(from_agent, _BROADCAST, query, context)

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dispatch loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._dispatch_loop())
        logger.info("MessageBus started")

    async def stop(self) -> None:
        """Drain remaining messages and stop the dispatch loop."""
        self._running = False
        if self._task is not None:
            await self._queue.put(None)  # type: ignore[arg-type]
            await self._task
            self._task = None
        logger.info("MessageBus stopped")

    # ── dispatch ─────────────────────────────────────────────────────────

    async def _dispatch_loop(self) -> None:
        while self._running:
            message = await self._queue.get()
            if message is None:
                break
            self._log.append(message)
            await self._dispatch(message)
            self._queue.task_done()

    async def _dispatch(self, message: AgentMessage) -> None:
        target = message.to_agent
        handlers = list(self._handlers.get(target, []))
        if target != _BROADCAST:
            handlers.extend(self._handlers.get(_BROADCAST, []))

        for handler in handlers:
            try:
                await handler(message)
            except (ToolExecutionError, Exception):
                logger.exception(
                    "Handler failed for message from '%s' to '%s'",
                    message.from_agent,
                    target,
                )

    # ── introspection ────────────────────────────────────────────────────

    @property
    def message_log(self) -> list[AgentMessage]:
        return list(self._log)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
