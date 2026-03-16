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
import hashlib
import json
import logging
from typing import Any, TypeVar

import instructor
from anthropic import AsyncAnthropic
from langfuse.decorators import observe
from langfuse.openai import AsyncOpenAI
from pydantic import BaseModel

from ira.config import Settings, get_settings
from ira.services.resilience import CircuitBreaker, RetryPolicy, run_with_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0
_MAX_DELAY_SECONDS = 10.0


def _status_code(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _is_retryable_llm_error(exc: Exception) -> bool:
    """Return True for rate limits (429), server errors (5xx), connection errors; False for 401/400."""
    status = _status_code(exc)
    if status is not None and status in (401, 400):
        return False
    return status in (402, 429) or status is None or (status is not None and status >= 500)


class LLMClient:
    """Unified async client for OpenAI and Anthropic with Langfuse tracing."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        openai_key = cfg.llm.openai_api_key.get_secret_value()
        anthropic_key = cfg.llm.anthropic_api_key.get_secret_value()
        helicone_key = cfg.helicone.api_key.get_secret_value()

        openai_kwargs: dict[str, Any] = {"api_key": openai_key}
        anthropic_kwargs: dict[str, Any] = {"api_key": anthropic_key}

        if helicone_key:
            openai_kwargs["base_url"] = "https://oai.helicone.ai/v1"
            openai_kwargs["default_headers"] = {"Helicone-Auth": f"Bearer {helicone_key}"}
            anthropic_kwargs["base_url"] = "https://anthropic.helicone.ai/v1"
            anthropic_kwargs["default_headers"] = {"Helicone-Auth": f"Bearer {helicone_key}"}
            logger.info("Helicone proxy enabled for OpenAI and Anthropic")

        self._openai: AsyncOpenAI | None = (
            AsyncOpenAI(**openai_kwargs) if openai_key else None
        )
        self._anthropic: AsyncAnthropic | None = (
            AsyncAnthropic(**anthropic_kwargs) if anthropic_key else None
        )

        self._openai_instructor = (
            instructor.from_openai(self._openai) if self._openai else None
        )
        self._anthropic_instructor = (
            instructor.from_anthropic(self._anthropic) if self._anthropic else None
        )

        self._openai_model = cfg.llm.openai_model
        self._anthropic_model = cfg.llm.anthropic_model

        self._semaphore = asyncio.Semaphore(10)
        self._retry_policy = RetryPolicy(
            max_attempts=_MAX_RETRIES,
            base_delay_seconds=_RETRY_BACKOFF,
            max_delay_seconds=_MAX_DELAY_SECONDS,
        )
        self._openai_breaker = CircuitBreaker(threshold=10, window_seconds=180)
        self._anthropic_breaker = CircuitBreaker(threshold=10, window_seconds=180)
        self._redis_cache: Any = None

    def set_redis_cache(self, cache: Any) -> None:
        """Inject Redis cache for semantic response caching (optional)."""
        self._redis_cache = cache

    @staticmethod
    def _llm_cache_key(
        system: str,
        user: str,
        model: str,
        temperature: float,
        extra: str = "",
    ) -> str:
        raw = f"{system[:2000]}|{user[:4000]}|{model}|{temperature:.2f}|{extra}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    _LLM_CACHE_TTL = 86400  # 24 hours

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
        async with self._semaphore:
            return await self._generate_structured_inner(
                system, user, response_model,
                provider=provider, model=model, temperature=temperature,
                max_tokens=max_tokens, name=name, session_id=session_id,
                user_id=user_id,
            )

    async def _generate_structured_inner(
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
        resolved_model = model or (self._openai_model if provider == "openai" else self._anthropic_model)
        if self._redis_cache and temperature <= 0.2:
            try:
                cache_key = self._llm_cache_key(
                    system, user, resolved_model, temperature,
                    extra=f"structured:{response_model.__name__}",
                )
                cached = await self._redis_cache.get_llm_cache(cache_key)
                if cached is not None:
                    data = json.loads(cached)
                    return response_model.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass
        if provider == "openai":
            result = await self._openai_structured(
                system, user, response_model,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        else:
            result = await self._anthropic_structured(
                system, user, response_model,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        if self._redis_cache and temperature <= 0.2:
            try:
                cache_key = self._llm_cache_key(
                    system, user, resolved_model, temperature,
                    extra=f"structured:{response_model.__name__}",
                )
                await self._redis_cache.set_llm_cache(
                    cache_key,
                    json.dumps(result.model_dump(), default=str),
                    ttl_seconds=self._LLM_CACHE_TTL,
                )
            except Exception:
                pass
        return result

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

        async def _operation() -> T:
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
                logger.warning("OpenAI structured attempt failed: %s", exc)
                raise

        try:
            return await run_with_retry(
                _operation,
                policy=self._retry_policy,
                is_retryable=_is_retryable_llm_error,
                circuit_breaker=self._openai_breaker,
            )
        except Exception as exc:
            logger.warning(
                "OpenAI structured call failed after retries: %s",
                exc,
                exc_info=True,
            )
            raise

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

        async def _operation() -> T:
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
                logger.warning("Anthropic structured attempt failed: %s", exc)
                raise

        try:
            return await run_with_retry(
                _operation,
                policy=self._retry_policy,
                is_retryable=_is_retryable_llm_error,
                circuit_breaker=self._anthropic_breaker,
            )
        except Exception as exc:
            logger.warning(
                "Anthropic structured call failed after retries: %s",
                exc,
                exc_info=True,
            )
            raise

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
        async with self._semaphore:
            return await self._generate_text_inner(
                system, user,
                provider=provider, model=model, temperature=temperature,
                max_tokens=max_tokens, name=name, session_id=session_id,
                user_id=user_id,
            )

    async def _generate_text_inner(
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
        resolved_model = model or (self._openai_model if provider == "openai" else self._anthropic_model)
        if self._redis_cache and temperature <= 0.2:
            try:
                cache_key = self._llm_cache_key(system, user, resolved_model, temperature, extra="text")
                cached = await self._redis_cache.get_llm_cache(cache_key)
                if cached is not None:
                    return cached
            except Exception:
                pass
        if provider == "openai":
            result = await self._openai_text(
                system, user,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        else:
            result = await self._anthropic_text(
                system, user,
                model=model, temperature=temperature, max_tokens=max_tokens,
                name=name, session_id=session_id, user_id=user_id,
            )
        if self._redis_cache and temperature <= 0.2 and not result.startswith("("):
            try:
                cache_key = self._llm_cache_key(system, user, resolved_model, temperature, extra="text")
                await self._redis_cache.set_llm_cache(
                    cache_key, result, ttl_seconds=self._LLM_CACHE_TTL,
                )
            except Exception:
                pass
        return result

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

        async def _operation() -> str:
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

        try:
            return await run_with_retry(
                _operation,
                policy=self._retry_policy,
                is_retryable=_is_retryable_llm_error,
                circuit_breaker=self._openai_breaker,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status in (429, 402):
                logger.warning("OpenAI %d — quota/rate limit", status)
                return "(OpenAI quota/rate limit exceeded)"
            if status and status < 500:
                logger.warning("OpenAI %d error: %s", status, exc)
                return "(LLM call failed)"
            logger.warning("OpenAI text retry exhausted: %s", exc)
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

        async def _operation() -> str:
            resp = await self._anthropic.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=120.0,
                system=system,
                messages=[{"role": "user", "content": user[:12_000]}],
            )
            return resp.content[0].text

        try:
            return await run_with_retry(
                _operation,
                policy=self._retry_policy,
                is_retryable=_is_retryable_llm_error,
                circuit_breaker=self._anthropic_breaker,
            )
        except Exception as exc:
            status = _status_code(exc)
            if status in (429, 402):
                logger.warning("Anthropic %d — quota/rate limit", status)
                return "(Anthropic quota/rate limit exceeded)"
            if status and status < 500:
                logger.warning("Anthropic %d error: %s", status, exc)
                return "(LLM call failed)"
            logger.warning("Anthropic text retry exhausted: %s", exc)
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


def reset_llm_circuit_breakers() -> None:
    """Clear OpenAI and Anthropic circuit breakers so the next request is attempted.
    Use after reloading the OpenAI wallet or when starting Ira so prior 429s don't block."""
    client = get_llm_client()
    client._openai_breaker.reset()
    client._anthropic_breaker.reset()
