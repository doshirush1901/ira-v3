"""Centralised LLM client wrapping the OpenAI and Anthropic SDKs.

All LLM calls in the codebase route through this module.  OpenAI calls
go via the ``langfuse.openai`` wrapper so every request is automatically
traced in Langfuse.  Anthropic calls use the standard SDK with manual
``@observe()`` tracing.

Structured output uses `instructor <https://python.useinstructor.com/>`_
which sends Pydantic validation errors back to the LLM for automatic
correction, dramatically reducing parse failures.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar

import instructor
from anthropic import AsyncAnthropic
from langfuse.decorators import observe
from langfuse.openai import AsyncOpenAI
from pydantic import BaseModel

from ira.config import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0


class LLMClient:
    """Unified async client for OpenAI and Anthropic with Langfuse tracing."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        openai_key = cfg.llm.openai_api_key.get_secret_value()
        anthropic_key = cfg.llm.anthropic_api_key.get_secret_value()

        self._openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=openai_key) if openai_key else None
        )
        self._anthropic: AsyncAnthropic | None = (
            AsyncAnthropic(api_key=anthropic_key) if anthropic_key else None
        )

        self._openai_instructor = (
            instructor.from_openai(self._openai) if self._openai else None
        )
        self._anthropic_instructor = (
            instructor.from_anthropic(self._anthropic) if self._anthropic else None
        )

        self._openai_model = cfg.llm.openai_model
        self._anthropic_model = cfg.llm.anthropic_model

    # ── structured output (JSON → Pydantic) ──────────────────────────────

    async def generate_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        provider: str = "openai",
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> T:
        """Call an LLM and parse the response into a Pydantic model.

        Uses Instructor to handle structured output with automatic
        validation-retry feedback for both OpenAI and Anthropic.
        """
        if provider == "openai":
            return await self._openai_structured(
                system, user, response_model,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        return await self._anthropic_structured(
            system, user, response_model,
            model=model, temperature=temperature, max_tokens=max_tokens,
            name=name, session_id=session_id, user_id=user_id,
        )

    async def _openai_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> T:
        if self._openai_instructor is None:
            return response_model()

        resolved_model = model or self._openai_model
        metadata: dict[str, Any] = {}
        if session_id:
            metadata["langfuse_session_id"] = session_id
        if user_id:
            metadata["langfuse_user_id"] = user_id

        backoff = _RETRY_BACKOFF
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await self._openai_instructor.chat.completions.create(
                    model=resolved_model,
                    response_model=response_model,
                    max_retries=2,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=120.0,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user[:12_000]},
                    ],
                    **({"name": name} if name else {}),
                    **({"metadata": metadata} if metadata else {}),
                )
            except Exception as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (429, 402):
                    logger.warning("OpenAI %d — quota/rate limit", status)
                    break
                if status and status < 500:
                    logger.warning("OpenAI %d error: %s", status, exc)
                    break
                logger.warning(
                    "OpenAI structured attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        if last_exc:
            logger.error("OpenAI structured call failed: %s", last_exc)
        return response_model()

    @observe(name="anthropic_structured")
    async def _anthropic_structured(
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        model: str | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> T:
        if self._anthropic_instructor is None:
            return response_model()

        resolved_model = model or self._anthropic_model

        backoff = _RETRY_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await self._anthropic_instructor.messages.create(
                    model=resolved_model,
                    response_model=response_model,
                    max_retries=2,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=120.0,
                    system=system,
                    messages=[{"role": "user", "content": user[:12_000]}],
                )
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (429, 402):
                    logger.warning("Anthropic %d — quota/rate limit", status)
                    break
                if status and status < 500:
                    logger.warning("Anthropic %d error: %s", status, exc)
                    break
                logger.warning(
                    "Anthropic structured attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        return response_model()

    # ── plain text output ─────────────────────────────────────────────────

    async def generate_text(
        self,
        system: str,
        user: str,
        *,
        provider: str = "openai",
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Call an LLM and return the raw text response."""
        if provider == "openai":
            return await self._openai_text(
                system, user,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        return await self._anthropic_text(
            system, user,
            model=model, temperature=temperature, max_tokens=max_tokens,
            name=name, session_id=session_id, user_id=user_id,
        )

    async def _openai_text(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        if self._openai is None:
            return "(No OpenAI key configured)"

        resolved_model = model or self._openai_model
        metadata: dict[str, Any] = {}
        if session_id:
            metadata["langfuse_session_id"] = session_id
        if user_id:
            metadata["langfuse_user_id"] = user_id

        backoff = _RETRY_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self._openai.chat.completions.create(
                    model=resolved_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=120.0,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user[:12_000]},
                    ],
                    **({"name": name} if name else {}),
                    **({"metadata": metadata} if metadata else {}),
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (429, 402):
                    logger.warning("OpenAI %d — quota/rate limit", status)
                    return "(OpenAI quota/rate limit exceeded)"
                if status and status < 500:
                    logger.warning("OpenAI %d error: %s", status, exc)
                    return "(LLM call failed)"
                logger.warning(
                    "OpenAI text attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        return "(LLM call failed after 3 retries)"

    @observe(name="anthropic_text")
    async def _anthropic_text(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        if self._anthropic is None:
            return "(No Anthropic key configured)"

        resolved_model = model or self._anthropic_model

        backoff = _RETRY_BACKOFF
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self._anthropic.messages.create(
                    model=resolved_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=120.0,
                    system=system,
                    messages=[{"role": "user", "content": user[:12_000]}],
                )
                return resp.content[0].text
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (429, 402):
                    logger.warning("Anthropic %d — quota/rate limit", status)
                    return "(Anthropic quota/rate limit exceeded)"
                if status and status < 500:
                    logger.warning("Anthropic %d error: %s", status, exc)
                    return "(LLM call failed)"
                logger.warning(
                    "Anthropic text attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        return "(LLM call failed after 3 retries)"

    # ── fallback wrappers ─────────────────────────────────────────────────

    async def generate_text_with_fallback(
        self,
        system: str,
        user: str,
        *,
        primary: str = "openai",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: str | None = None,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Try the primary provider; fall back to the other on failure."""
        result = await self.generate_text(
            system, user,
            provider=primary, model=model, temperature=temperature,
            max_tokens=max_tokens, name=name,
            session_id=session_id, user_id=user_id,
        )
        if not result.startswith("("):
            return result

        fallback = "anthropic" if primary == "openai" else "openai"
        logger.info("Falling back to %s after %s failure", fallback, primary)
        return await self.generate_text(
            system, user,
            provider=fallback, temperature=temperature,
            max_tokens=max_tokens, name=name,
            session_id=session_id, user_id=user_id,
        )

    async def generate_structured_with_fallback(
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        primary: str = "openai",
        temperature: float = 0,
        max_tokens: int = 4096,
        model: str | None = None,
        name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> T:
        """Try structured output from the primary provider; fall back on failure."""
        result = await self.generate_structured(
            system, user, response_model,
            provider=primary, model=model, temperature=temperature,
            max_tokens=max_tokens, name=name,
            session_id=session_id, user_id=user_id,
        )
        if result != response_model():
            return result

        fallback = "anthropic" if primary == "openai" else "openai"
        logger.info("Falling back to %s for structured output", fallback)
        return await self.generate_structured(
            system, user, response_model,
            provider=fallback, temperature=temperature,
            max_tokens=max_tokens, name=name,
            session_id=session_id, user_id=user_id,
        )


# ── singleton ─────────────────────────────────────────────────────────────

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the global LLMClient singleton (created on first call)."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_llm_client() -> None:
    """Reset the singleton — useful for tests."""
    global _client
    _client = None
