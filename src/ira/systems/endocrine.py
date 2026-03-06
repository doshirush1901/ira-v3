"""Endocrine system — adaptive behavior through hormone-like state variables.

Manages four hormone levels (confidence, energy, growth_signal, stress) that
influence how Ira's agents behave.  Other systems call ``boost()`` /
``reduce()`` when events occur, and agents call ``get_behavioral_modifiers()``
to get prompt-injection instructions before generating responses.

All methods are synchronous — hormone adjustments are lightweight in-memory
operations.  Thread-safe via ``threading.Lock``.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_HORMONE_NAMES = frozenset({"confidence", "energy", "growth_signal", "stress"})

_BASELINE: dict[str, float] = {
    "confidence": 0.5,
    "energy": 0.7,
    "growth_signal": 0.3,
    "stress": 0.2,
}

_HIGH_CONFIDENCE_THRESHOLD = 0.7
_LOW_CONFIDENCE_THRESHOLD = 0.3
_HIGH_STRESS_THRESHOLD = 0.7
_LOW_STRESS_THRESHOLD = 0.3
_HIGH_GROWTH_THRESHOLD = 0.6
_LOW_ENERGY_THRESHOLD = 0.3


class EndocrineSystem:
    """Manages Ira's adaptive behavior through hormone levels."""

    def __init__(self) -> None:
        self._levels: dict[str, float] = dict(_BASELINE)
        self._lock = threading.Lock()
        self._last_decay: float = time.monotonic()

    # ── level adjustments ─────────────────────────────────────────────────

    def boost(self, hormone: str, amount: float) -> None:
        """Increase a hormone level, capped at 1.0."""
        if hormone not in _HORMONE_NAMES:
            raise ValueError(f"Unknown hormone '{hormone}'. Valid: {sorted(_HORMONE_NAMES)}")
        with self._lock:
            old = self._levels[hormone]
            self._levels[hormone] = min(1.0, old + abs(amount))
            logger.debug("ENDOCRINE boost %s +%.2f -> %.2f", hormone, abs(amount), self._levels[hormone])

    def reduce(self, hormone: str, amount: float) -> None:
        """Decrease a hormone level, floored at 0.0."""
        if hormone not in _HORMONE_NAMES:
            raise ValueError(f"Unknown hormone '{hormone}'. Valid: {sorted(_HORMONE_NAMES)}")
        with self._lock:
            old = self._levels[hormone]
            self._levels[hormone] = max(0.0, old - abs(amount))
            logger.debug("ENDOCRINE reduce %s -%.2f -> %.2f", hormone, abs(amount), self._levels[hormone])

    def decay_all(self, factor: float = 0.95) -> None:
        """Move all hormone levels toward their baselines by *factor*.

        With ``factor=0.95``, each call moves levels 5 % closer to baseline.
        """
        with self._lock:
            for name in _HORMONE_NAMES:
                current = self._levels[name]
                baseline = _BASELINE[name]
                self._levels[name] = current + (baseline - current) * (1.0 - factor)
            self._last_decay = time.monotonic()

    # ── queries ───────────────────────────────────────────────────────────

    def get_levels(self) -> dict[str, float]:
        """Return a snapshot of current hormone levels."""
        with self._lock:
            return dict(self._levels)

    def get_behavioral_modifiers(self) -> dict[str, str]:
        """Translate hormone levels into behavioral instructions for agents."""
        with self._lock:
            levels = dict(self._levels)

        confidence = levels["confidence"]
        stress = levels["stress"]
        growth = levels["growth_signal"]
        energy = levels["energy"]

        # Base response style
        if confidence >= _HIGH_CONFIDENCE_THRESHOLD and stress <= _LOW_STRESS_THRESHOLD:
            response_style = "assertive"
            verbosity = "concise"
            addendum = "Be direct and concise. State facts confidently."
        elif confidence <= _LOW_CONFIDENCE_THRESHOLD or stress >= _HIGH_STRESS_THRESHOLD:
            response_style = "cautious"
            verbosity = "detailed"
            addendum = (
                "Express uncertainty where appropriate. "
                "Suggest human review for critical decisions. Include caveats."
            )
        else:
            response_style = "balanced"
            verbosity = "normal"
            addendum = "Provide clear, balanced responses."

        # Growth signal overlay
        if growth >= _HIGH_GROWTH_THRESHOLD:
            follow_up = "high"
            addendum += " Ask clarifying follow-up questions to deepen understanding."
        else:
            follow_up = "normal"

        # Energy overlay
        if energy <= _LOW_ENERGY_THRESHOLD:
            complexity = "reduced"
            verbosity = "concise"
            addendum += " Keep responses brief. Defer complex analysis to a later time."
        else:
            complexity = "full" if energy > 0.6 else "normal"

        return {
            "response_style": response_style,
            "verbosity": verbosity,
            "follow_up_tendency": follow_up,
            "complexity_tolerance": complexity,
            "prompt_addendum": addendum,
        }
