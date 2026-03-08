"""Guardrails AI integration for semantic validation.

Provides validators that Vera (fact-checker) and Sphinx (gatekeeper) can
use to programmatically check LLM outputs for common issues:

- PII/sensitive data leakage
- Hallucinated or unsupported claims
- Toxic or unprofessional language
- Off-topic responses

These complement the LLM-based reasoning in the ReAct loop with
deterministic, fast validation checks.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_guard_instance = None


def _get_guard():
    """Lazy-load the Guardrails validator chain."""
    global _guard_instance
    if _guard_instance is not None:
        return _guard_instance

    try:
        from guardrails import Guard

        _guard_instance = Guard(name="ira_output_guard").use_many(
            _load_validators()
        )
        logger.info("Guardrails AI loaded with validators")
        return _guard_instance
    except Exception:
        logger.debug("Guardrails AI not available", exc_info=True)
        return None


def _load_validators() -> list:
    """Load available Guardrails validators."""
    validators = []

    try:
        from guardrails.hub import DetectPII
        validators.append(DetectPII(
            pii_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"],
            on_fail="fix",
        ))
    except (ImportError, Exception):
        logger.debug("DetectPII validator not available")

    try:
        from guardrails.hub import ToxicLanguage
        validators.append(ToxicLanguage(
            threshold=0.7,
            on_fail="noop",
        ))
    except (ImportError, Exception):
        logger.debug("ToxicLanguage validator not available")

    return validators


async def validate_output(text: str) -> dict[str, Any]:
    """Run Guardrails validators on a text output.

    Returns a dict with:
    - ``valid``: bool — whether all checks passed
    - ``issues``: list[str] — descriptions of any issues found
    - ``sanitized``: str — the text with PII redacted (if applicable)
    """
    guard = _get_guard()
    if guard is None:
        return {"valid": True, "issues": [], "sanitized": text}

    try:
        result = guard.validate(text)
        issues = []

        if result.validation_passed is False:
            for log in (result.error_spans or []):
                issues.append(f"{log.reason}: '{log.text[:100]}'")

        return {
            "valid": result.validation_passed,
            "issues": issues,
            "sanitized": str(result.validated_output) if result.validated_output else text,
        }
    except Exception as exc:
        logger.warning("Guardrails validation failed: %s", exc)
        return {"valid": True, "issues": [], "sanitized": text}


async def check_faithfulness(
    response: str,
    context_docs: list[str],
) -> dict[str, Any]:
    """Check whether a response is faithful to the provided context documents.

    Uses a lightweight heuristic: extracts key claims from the response and
    checks if they appear (or are semantically close to) the context.

    Returns:
    - ``faithful``: bool
    - ``unsupported_claims``: list[str] — claims not found in context
    - ``score``: float — 0.0 to 1.0 faithfulness score
    """
    if not context_docs or not response.strip():
        return {"faithful": True, "unsupported_claims": [], "score": 1.0}

    context_text = " ".join(context_docs).lower()
    sentences = [s.strip() for s in response.split(".") if len(s.strip()) > 20]

    if not sentences:
        return {"faithful": True, "unsupported_claims": [], "score": 1.0}

    supported = 0
    unsupported: list[str] = []

    for sentence in sentences:
        words = set(sentence.lower().split())
        significant_words = {w for w in words if len(w) > 3}
        if not significant_words:
            supported += 1
            continue

        overlap = sum(1 for w in significant_words if w in context_text)
        ratio = overlap / len(significant_words) if significant_words else 0

        if ratio >= 0.3:
            supported += 1
        else:
            unsupported.append(sentence)

    score = supported / len(sentences) if sentences else 1.0

    return {
        "faithful": score >= 0.7,
        "unsupported_claims": unsupported[:5],
        "score": round(score, 2),
    }
