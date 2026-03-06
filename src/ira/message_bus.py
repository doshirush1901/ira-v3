"""Async message bus for agent-to-agent communication.

The :class:`MessageBus` is the backbone of the Pantheon's internal
communication.  It routes :class:`~ira.data.models.AgentMessage` objects
between agents, maintains a conversation trace for debugging, and supports
parallel fan-out via :meth:`broadcast`.

A module-level singleton ``bus`` is provided — every part of the
application should import and use this single instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ira.data.models import AgentMessage

logger = logging.getLogger(__name__)


class MessageBus:
    """Simple async message bus backed by :class:`asyncio.Queue`."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._trace: list[AgentMessage] = []
        self._queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

    # ── registration ──────────────────────────────────────────────────────

    def register_agent(self, agent_name: str, handler: Callable[..., Any]) -> None:
        """Register *handler* as the receiver for messages sent to *agent_name*.

        Raises :class:`ValueError` if the agent is already registered.
        """
        if agent_name in self._handlers:
            raise ValueError(f"Agent '{agent_name}' is already registered on the bus")
        self._handlers[agent_name] = handler
        logger.info("Registered agent '%s' on the message bus", agent_name)

    # ── send ──────────────────────────────────────────────────────────────

    async def send(self, message: AgentMessage) -> AgentMessage:
        """Route *message* to the target agent and return the filled message.

        The handler registered for ``message.to_agent`` is awaited with
        *message*.  On return the handler's result is written into
        ``message.response``.

        Raises :class:`KeyError` if no handler is registered for the
        target agent.
        """
        self._trace.append(message)

        logger.debug(
            "MessageBus: %s -> %s | %.120s",
            message.from_agent,
            message.to_agent,
            message.query,
        )

        handler = self._handlers.get(message.to_agent)
        if handler is None:
            raise KeyError(
                f"No handler registered for agent '{message.to_agent}'. "
                f"Registered agents: {list(self._handlers)}"
            )

        response = await handler(message)
        message.response = response
        return message

    # ── broadcast ─────────────────────────────────────────────────────────

    async def broadcast(
        self,
        from_agent: str,
        query: str,
        target_agents: list[str],
    ) -> dict[str, str]:
        """Send the same *query* to every agent in *target_agents* in parallel.

        Returns a mapping of ``agent_name -> response_text``.
        """
        messages = [
            AgentMessage(from_agent=from_agent, to_agent=target, query=query)
            for target in target_agents
        ]

        results = await asyncio.gather(
            *(self.send(m) for m in messages),
            return_exceptions=True,
        )

        responses: dict[str, str] = {}
        for target, result in zip(target_agents, results):
            if isinstance(result, BaseException):
                logger.error("Broadcast to '%s' failed: %s", target, result)
                responses[target] = f"Error: {result}"
            else:
                responses[target] = result.response or ""

        return responses

    # ── trace ─────────────────────────────────────────────────────────────

    def get_trace(self) -> list[AgentMessage]:
        """Return a copy of the full conversation trace."""
        return list(self._trace)

    def clear_trace(self) -> None:
        """Reset the conversation trace."""
        self._trace.clear()


# ── module-level singleton ────────────────────────────────────────────────

bus = MessageBus()
