"""Guardrails AI integration for semantic validation.

Provides validators that Vera (fact-checker) and Sphinx (gatekeeper) can
use to programmatically check LLM outputs for common issues:

- PII/sensitive data leakage
- Hallucinated or unsupported claims
- Toxic or unprofessional language
- Competitor praise in external communications
- Confidential data leakage (pricing, margins, HR)

These complement the LLM-based reasoning in the ReAct loop with
deterministic, fast validation checks.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import ConfidentialityResult, FaithfulnessResult

logger = logging.getLogger(__name__)

_guard_instance = None

_FAITHFULNESS_SYSTEM_PROMPT = load_prompt("faithfulness_check")

KNOWN_COMPETITORS: list[str] = [
    "ILLIG", "Kiefel", "GN Thermoforming", "WM Thermoforming",
    "Gabler", "Multivac", "AMUT", "Cannon",
]

_CONFIDENTIAL_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:margin|markup)\s*(?:is|of|at|:)?\s*\d+", "internal_margin"),
    (r"\b(?:cost\s*price|COGS|cost\s*of\s*goods)\s*(?:is|of|at|:)?\s*(?:EUR|USD|\$|€)\s*[\d,]+", "cost_price"),
    (r"\b(?:salary|compensation|CTC|take[\s-]?home)\s*(?:is|of|at|:)?\s*(?:EUR|USD|INR|\$|€|₹)\s*[\d,]+", "hr_salary"),
    (r"\b(?:employee\s*ID|emp[\s-]?ID)\s*(?:is|of|:)?\s*\w+", "hr_employee_id"),
    (r"\b(?:vendor\s*price|supplier\s*cost|purchase\s*price)\s*(?:is|of|at|:)?\s*(?:EUR|USD|\$|€)\s*[\d,]+", "vendor_pricing"),
]


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
        result = await asyncio.to_thread(guard.validate, text)
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

    Uses an LLM-based entailment check via Instructor for semantic
    verification.  Falls back to the keyword-overlap heuristic if the
    LLM call fails.

    Returns:
    - ``faithful``: bool
    - ``unsupported_claims``: list[dict] — claims not found in context
    - ``score``: float — 0.0 to 1.0 faithfulness score
    """
    if not context_docs or not response.strip():
        return {"faithful": True, "unsupported_claims": [], "score": 1.0}

    try:
        from ira.services.llm_client import get_llm_client

        llm = get_llm_client()
        context_text = "\n---\n".join(context_docs)
        user_msg = f"Response:\n{response}\n\nSource Context:\n{context_text}"

        result = await llm.generate_structured(
            _FAITHFULNESS_SYSTEM_PROMPT,
            user_msg,
            FaithfulnessResult,
            name="guardrails.faithfulness",
        )
        return {
            "faithful": result.faithful,
            "unsupported_claims": [c.model_dump() for c in result.unsupported_claims],
            "score": round(result.score, 2),
        }
    except Exception:
        logger.debug("LLM faithfulness check failed, using heuristic", exc_info=True)

    return _heuristic_faithfulness(response, context_docs)


def _heuristic_faithfulness(
    response: str,
    context_docs: list[str],
) -> dict[str, Any]:
    """Keyword-overlap fallback for faithfulness checking."""
    context_text = " ".join(context_docs).lower()
    sentences = [s.strip() for s in response.split(".") if len(s.strip()) > 20]

    if not sentences:
        return {"faithful": True, "unsupported_claims": [], "score": 1.0}

    supported = 0
    unsupported: list[dict[str, str]] = []

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
            unsupported.append({"claim": sentence, "reason": "Low keyword overlap with context"})

    score = supported / len(sentences) if sentences else 1.0

    return {
        "faithful": score >= 0.7,
        "unsupported_claims": unsupported[:5],
        "score": round(score, 2),
    }


async def check_competitor_mentions(
    text: str,
    competitors: list[str] | None = None,
) -> dict[str, Any]:
    """Flag responses that mention or praise competitors.

    Returns:
    - ``clean``: bool — True if no competitor issues found
    - ``mentions``: list[dict] — competitor mentions with context
    """
    competitor_list = competitors or KNOWN_COMPETITORS
    text_lower = text.lower()
    mentions: list[dict[str, str]] = []

    for competitor in competitor_list:
        comp_lower = competitor.lower()
        if comp_lower in text_lower:
            idx = text_lower.index(comp_lower)
            start = max(0, idx - 50)
            end = min(len(text), idx + len(competitor) + 50)
            snippet = text[start:end].strip()
            mentions.append({
                "competitor": competitor,
                "context": snippet,
            })

    return {
        "clean": len(mentions) == 0,
        "mentions": mentions,
    }


async def check_confidentiality(
    text: str,
    direction: str = "external",
) -> dict[str, Any]:
    """Detect internal pricing, margin, or HR data in external-facing responses.

    Uses regex patterns for fast detection and optionally an LLM for
    nuanced classification.

    Args:
        text: The response text to check.
        direction: ``"external"`` (strict) or ``"internal"`` (lenient).

    Returns:
    - ``safe``: bool — True if no confidential data detected
    - ``leaked_categories``: list[str] — types of data found
    - ``flagged_snippets``: list[str] — the offending text fragments
    """
    if direction == "internal":
        return {"safe": True, "leaked_categories": [], "flagged_snippets": []}

    leaked_categories: list[str] = []
    flagged_snippets: list[str] = []

    for pattern, category in _CONFIDENTIAL_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            if category not in leaked_categories:
                leaked_categories.append(category)
            for match in matches[:3]:
                flagged_snippets.append(match)

    if not leaked_categories:
        return {"safe": True, "leaked_categories": [], "flagged_snippets": []}

    try:
        from ira.services.llm_client import get_llm_client

        llm = get_llm_client()
        result = await llm.generate_structured(
            "You are a data loss prevention checker for Machinecraft. "
            "Determine if the flagged snippets contain genuinely confidential "
            "internal data (margins, cost prices, salaries, vendor pricing) "
            "or if they are publicly available information (list prices, "
            "published specs). Return safe=true if all snippets are public.",
            f"Text: {text[:4000]}\n\nFlagged snippets: {flagged_snippets}",
            ConfidentialityResult,
            name="guardrails.confidentiality",
        )
        return {
            "safe": result.safe,
            "leaked_categories": result.leaked_categories or leaked_categories,
            "flagged_snippets": result.flagged_snippets or flagged_snippets,
        }
    except Exception:
        logger.debug("LLM confidentiality check failed, using regex results", exc_info=True)

    return {
        "safe": False,
        "leaked_categories": leaked_categories,
        "flagged_snippets": flagged_snippets[:5],
    }
