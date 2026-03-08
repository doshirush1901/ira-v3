"""Pantheon — top-level orchestrator for the Ira agent system.

Initialises all agents, the message bus, and brain services, then
routes incoming queries through the deterministic router (fast path)
or Athena (LLM path).  Also supports "board meeting" mode where
multiple agents collaborate on a topic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

from ira.agents.alexandros import Alexandros
from ira.agents.arachne import Arachne
from ira.agents.asclepius import Asclepius
from ira.agents.athena import Athena
from ira.agents.atlas import Atlas
from ira.agents.cadmus import Cadmus
from ira.agents.calliope import Calliope
from ira.agents.chiron import Chiron
from ira.agents.clio import Clio
from ira.agents.delphi import Delphi
from ira.agents.hephaestus import Hephaestus
from ira.agents.hera import Hera
from ira.agents.hermes import Hermes
from ira.agents.iris import Iris
from ira.agents.mnemosyne import Mnemosyne
from ira.agents.nemesis import Nemesis
from ira.agents.plutus import Plutus
from ira.agents.prometheus import Prometheus
from ira.agents.quotebuilder import Quotebuilder
from ira.agents.sophia import Sophia
from ira.agents.sphinx import Sphinx
from ira.agents.themis import Themis
from ira.agents.tyche import Tyche
from ira.agents.vera import Vera
from ira.agents.base_agent import BaseAgent
from ira.brain.deterministic_router import DeterministicRouter
from ira.exceptions import ToolExecutionError
from ira.brain.retriever import UnifiedRetriever
from ira.data.models import BoardMeetingMinutes
from ira.message_bus import MessageBus
from ira.skills import SKILL_MATRIX
from ira.skills.handlers import use_skill

logger = logging.getLogger(__name__)

_AGENT_CLASSES: list[type[BaseAgent]] = [
    Athena, Clio, Prometheus, Plutus, Hermes, Hephaestus, Themis,
    Calliope, Tyche, Delphi, Sphinx, Vera, Sophia, Iris, Mnemosyne,
    Nemesis, Arachne, Alexandros, Hera, Atlas, Asclepius, Chiron,
    Cadmus, Quotebuilder,
]


class Pantheon:
    """Top-level orchestrator that ties agents, brain, and bus together."""

    def __init__(
        self,
        retriever: UnifiedRetriever,
        bus: MessageBus | None = None,
    ) -> None:
        self._bus = bus or MessageBus()
        self._retriever = retriever
        self._router = DeterministicRouter()

        self._agents: dict[str, BaseAgent] = {}
        for cls in _AGENT_CLASSES:
            agent = cls(retriever=retriever, bus=self._bus)
            self._agents[agent.name] = agent

        self._athena: Athena = self._agents["athena"]  # type: ignore[assignment]

    def inject_services(self, services: dict[str, Any]) -> None:
        """Propagate shared services (CRM, PricingEngine, etc.) to all agents."""
        for agent in self._agents.values():
            agent.inject_services(services)
        logger.info(
            "Injected services into %d agents: %s",
            len(self._agents),
            sorted(services),
        )

    @property
    def router(self) -> DeterministicRouter:
        """Public access to the deterministic router."""
        return self._router

    @property
    def retriever(self) -> UnifiedRetriever:
        """Public access to the unified retriever."""
        return self._retriever

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._bus.start()
        logger.info("Pantheon started with %d agents", len(self._agents))

    async def stop(self) -> None:
        await self._bus.stop()
        logger.info("Pantheon stopped")

    async def __aenter__(self) -> Pantheon:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ── main entry point ─────────────────────────────────────────────────

    async def process(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> str:
        """Process a user query and return the final response.

        1. Try the deterministic router for a fast-path match.
        2. If no match, ask Athena to route via LLM.
        3. Dispatch to the selected agents and synthesise.
        """
        ctx = context or {}

        routing = self._router.route(query)
        if routing:
            return await self._dispatch_routed(query, routing, ctx, on_progress)

        return await self._dispatch_athena(query, ctx, on_progress)

    # ── routing strategies ───────────────────────────────────────────────

    async def _dispatch_routed(
        self,
        query: str,
        routing: dict[str, Any],
        context: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> str:
        """Dispatch to agents selected by the deterministic router."""
        agent_names = routing["required_agents"]
        logger.info(
            "Deterministic route: %s -> %s",
            routing["intent"],
            agent_names,
        )

        if len(agent_names) == 1:
            agent = self._agents.get(agent_names[0])
            if agent:
                if on_progress:
                    await on_progress({"type": "agent_started", "agent": agent_names[0], "role": getattr(agent, "role", "")})
                result = await agent.handle(query, context)
                if on_progress:
                    await on_progress({"type": "agent_done", "agent": agent_names[0], "preview": result[:200]})
                return result

        responses = await self._gather_responses(agent_names, query, context, on_progress)

        if len(responses) == 1:
            return next(iter(responses.values()))

        if on_progress:
            await on_progress({"type": "synthesizing", "agent": "athena"})
        return await self._athena.handle(
            query, {"agent_responses": responses},
        )

    async def _dispatch_athena(
        self,
        query: str,
        context: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> str:
        """Let Athena decide which agents to consult via LLM."""
        logger.info("LLM routing via Athena")
        if on_progress:
            await on_progress({"type": "routing", "agent": "athena"})
        routing_response = await self._athena.handle(query, context)

        agent_names = self._parse_agent_list(routing_response)
        if not agent_names:
            return routing_response

        responses = await self._gather_responses(agent_names, query, context, on_progress)
        if len(responses) == 1:
            return next(iter(responses.values()))

        if on_progress:
            await on_progress({"type": "synthesizing", "agent": "athena"})
        return await self._athena.handle(
            query, {"agent_responses": responses},
        )

    # ── board meeting mode ───────────────────────────────────────────────

    async def board_meeting(
        self,
        topic: str,
        participants: list[str] | None = None,
    ) -> BoardMeetingMinutes:
        """Run a board meeting where multiple agents discuss a topic.

        Each participant contributes their perspective, then Athena
        synthesises a final decision.
        """
        agent_names = participants or list(self._agents.keys())
        agent_names = [n for n in agent_names if n in self._agents and n != "athena"]

        contributions = await self._gather_responses(agent_names, topic, {})

        synthesis = await self._athena.handle(
            topic, {"agent_responses": contributions},
        )

        return BoardMeetingMinutes(
            topic=topic,
            participants=["athena"] + list(contributions.keys()),
            contributions=contributions,
            synthesis=synthesis,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    _AGENT_TIMEOUT = 60

    async def _gather_responses(
        self,
        agent_names: list[str],
        query: str,
        context: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, str]:
        """Run agents sequentially and collect their responses.

        Each agent gets a per-agent timeout to prevent runaway execution.
        An optional *on_progress* callback receives ``agent_started`` and
        ``agent_done`` events for live streaming.
        """
        responses: dict[str, str] = {}
        for name in agent_names:
            agent = self._agents.get(name)
            if not agent:
                responses[name] = f"(Agent '{name}' not found)"
                continue
            if on_progress:
                await on_progress({"type": "agent_started", "agent": name, "role": getattr(agent, "role", "")})
            try:
                response = await asyncio.wait_for(
                    agent.handle(query, context),
                    timeout=self._AGENT_TIMEOUT,
                )
                responses[name] = response
            except asyncio.TimeoutError:
                logger.warning("Agent '%s' timed out after %ds", name, self._AGENT_TIMEOUT)
                responses[name] = f"(Agent '{name}' timed out after {self._AGENT_TIMEOUT}s)"
            except (ToolExecutionError, Exception):
                logger.exception("Agent '%s' failed", name)
                responses[name] = f"(Agent '{name}' encountered an error)"
            if on_progress:
                await on_progress({"type": "agent_done", "agent": name, "preview": responses[name][:200]})
        return responses

    def _parse_agent_list(self, routing_response: str) -> list[str]:
        """Try to extract agent names from Athena's routing JSON."""
        try:
            data = json.loads(routing_response)
            if isinstance(data, dict) and "agents" in data:
                names = data["agents"]
                return [
                    n.lower() for n in names
                    if isinstance(n, str) and n.lower() in self._agents
                ]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    # ── skill execution ──────────────────────────────────────────────────

    async def use_skill(self, skill_name: str, **kwargs: Any) -> str:
        """Execute a skill by name at the orchestrator level.

        This is a convenience wrapper so callers that hold a reference to
        the Pantheon (e.g. the CLI or an API layer) can invoke skills
        without going through a specific agent.
        """
        logger.info("Pantheon invoking skill '%s'", skill_name)
        return await use_skill(skill_name, **kwargs)

    @staticmethod
    def available_skills() -> dict[str, str]:
        """Return the full skill matrix for introspection."""
        return dict(SKILL_MATRIX)

    # ── introspection ────────────────────────────────────────────────────

    @property
    def agents(self) -> dict[str, BaseAgent]:
        return dict(self._agents)

    def get_agent(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)
