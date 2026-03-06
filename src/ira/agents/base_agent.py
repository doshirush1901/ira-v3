"""Abstract base class for all Pantheon agents.

Every specialist agent inherits from :class:`BaseAgent`, which provides
LLM access (OpenAI and Anthropic), knowledge-base search via the
:class:`~ira.brain.retriever.UnifiedRetriever`, and a reference to the
:class:`~ira.message_bus.MessageBus` for inter-agent communication.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.message_bus import MessageBus
from ira.skills import SKILL_MATRIX
from ira.skills.handlers import use_skill as _use_skill

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for every agent in the Pantheon."""

    name: str = "base"
    role: str = ""
    description: str = ""
    model_provider: str = "openai"  # "openai" or "anthropic"

    def __init__(
        self,
        retriever: UnifiedRetriever,
        bus: MessageBus,
        *,
        services: dict[str, Any] | None = None,
    ) -> None:
        self._retriever = retriever
        self._bus = bus
        self._services: dict[str, Any] = services or {}

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model
        self._anthropic_key = settings.llm.anthropic_api_key.get_secret_value()
        self._anthropic_model = settings.llm.anthropic_model

    def inject_services(self, services: dict[str, Any]) -> None:
        """Late-bind shared services after construction."""
        self._services.update(services)

    # ── abstract interface ───────────────────────────────────────────────

    @abstractmethod
    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Process a query and return a response string."""

    # ── LLM access ───────────────────────────────────────────────────────

    async def call_llm(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
    ) -> str:
        """Call the configured LLM provider and return the response text."""
        if self.model_provider == "anthropic" and self._anthropic_key:
            return await self._call_anthropic(system_prompt, user_message, temperature)
        return await self._call_openai(system_prompt, user_message, temperature)

    async def _call_openai(self, system: str, user: str, temperature: float) -> str:
        if not self._openai_key:
            return "(No OpenAI key configured)"

        payload = {
            "model": self._openai_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._openai_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError):
            logger.exception("OpenAI call failed in %s", self.name)
            return "(LLM call failed)"

    async def _call_anthropic(self, system: str, user: str, temperature: float) -> str:
        if not self._anthropic_key:
            return "(No Anthropic key configured)"

        payload = {
            "model": self._anthropic_model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user[:12_000]}],
            "temperature": temperature,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers={
                        "x-api-key": self._anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError):
            logger.exception("Anthropic call failed in %s", self.name)
            return "(LLM call failed)"

    # ── knowledge retrieval ──────────────────────────────────────────────

    async def search_knowledge(
        self,
        query: str,
        limit: int = 10,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the unified knowledge base."""
        return await self._retriever.search(query, sources=sources, limit=limit)

    async def search_category(
        self,
        query: str,
        category: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search within a specific knowledge category."""
        return await self._retriever.search_by_category(query, category, limit=limit)

    # ── inter-agent communication ────────────────────────────────────────

    async def send_to(self, to_agent: str, query: str, context: dict[str, Any] | None = None) -> None:
        """Send a message to another agent via the message bus."""
        await self._bus.send(self.name, to_agent, query, context)

    # ── utility ──────────────────────────────────────────────────────────

    def _format_context(self, kb_results: list[dict[str, Any]]) -> str:
        """Format knowledge-base results into a context string for LLM prompts."""
        if not kb_results:
            return "(No relevant context found)"
        lines = []
        for r in kb_results:
            lines.append(f"- [{r.get('source', 'unknown')}] {r.get('content', '')[:500]}")
        return "\n".join(lines)

    def _parse_json_response(self, raw: str) -> dict[str, Any] | list[Any]:
        """Attempt to parse an LLM response as JSON, stripping markdown fences."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        return json.loads(cleaned)

    # ── skill execution ──────────────────────────────────────────────────

    async def use_skill(self, skill_name: str, **kwargs: Any) -> str:
        """Execute a skill from the SKILL_MATRIX by name.

        Every agent inherits this method, giving the entire Pantheon
        uniform access to the shared skill library.

        Raises :class:`ValueError` for unrecognised skill names.
        """
        logger.info("Agent '%s' invoking skill '%s'", self.name, skill_name)
        return await _use_skill(skill_name, **kwargs)

    @staticmethod
    def available_skills() -> dict[str, str]:
        """Return the full skill matrix for introspection."""
        return dict(SKILL_MATRIX)
