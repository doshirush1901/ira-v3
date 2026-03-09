"""Shared resilience primitives: retry, backoff, and circuit breaker."""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 20.0
    jitter_ratio: float = 0.2


class CircuitBreaker:
    """Simple half-open circuit breaker for unstable upstream calls."""

    def __init__(self, *, threshold: int = 8, window_seconds: int = 180) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def record_failure(self) -> None:
        now = time.time()
        self._failures.append(now)
        cutoff = now - self._window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._opened_at = now

    def can_attempt(self) -> bool:
        if self._opened_at is None:
            return True
        return (time.time() - self._opened_at) >= self._window_seconds


def _backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    base = min(policy.base_delay_seconds * (2 ** max(0, attempt - 1)), policy.max_delay_seconds)
    jitter = base * policy.jitter_ratio * random.random()
    return base + jitter


async def run_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    is_retryable: Callable[[Exception], bool],
    circuit_breaker: CircuitBreaker | None = None,
) -> T:
    """Run async operation with retry and optional circuit breaker checks."""
    if circuit_breaker is not None and not circuit_breaker.can_attempt():
        raise RuntimeError("Circuit breaker open for operation")

    last_exc: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await operation()
            if circuit_breaker is not None:
                circuit_breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            if circuit_breaker is not None:
                circuit_breaker.record_failure()
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            await asyncio.sleep(_backoff_delay(attempt, policy))
    raise last_exc if last_exc else RuntimeError("retry failed without error")
