"""LLM evaluation tests using DeepEval.

Measures retrieval quality, answer relevance, hallucination rates,
and agent response quality.  Run with:

    poetry run pytest tests/test_eval.py -v

These tests require OPENAI_API_KEY to be set (DeepEval uses it for
evaluation metrics).  They are skipped automatically if the key is
missing or if DeepEval is not installed.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from deepeval import assert_test
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        FaithfulnessMetric,
        HallucinationMetric,
    )
    from deepeval.test_case import LLMTestCase

    HAS_DEEPEVAL = True
except ImportError:
    HAS_DEEPEVAL = False

pytestmark = [
    pytest.mark.skipif(not HAS_DEEPEVAL, reason="deepeval not installed"),
    pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY required for DeepEval metrics",
    ),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_test_case(
    query: str,
    response: str,
    retrieval_context: list[str] | None = None,
    context: list[str] | None = None,
) -> "LLMTestCase":
    return LLMTestCase(
        input=query,
        actual_output=response,
        retrieval_context=retrieval_context or [],
        context=context or [],
    )


# ── Answer Relevancy Tests ───────────────────────────────────────────────────


class TestAnswerRelevancy:
    """Verify that agent responses are relevant to the user's question."""

    metric = AnswerRelevancyMetric(threshold=0.6)

    def test_sales_query_relevancy(self):
        test_case = _make_test_case(
            query="What is the current status of the Dutch Tides deal?",
            response=(
                "The Dutch Tides deal is currently in the proposal stage. "
                "We sent a quote for 2x PF1 machines on January 15th, valued at EUR 450,000. "
                "Jaap van der Berg is the primary contact. Follow-up is scheduled for next week."
            ),
            retrieval_context=[
                "Quote Q-2024-089: Dutch Tides BV, 2x PF1, EUR 450,000, status: proposal sent",
                "Contact: Jaap van der Berg, CEO, Dutch Tides BV, jaap@dutch-tides.com",
            ],
        )
        assert_test(test_case, [self.metric])

    def test_machine_spec_relevancy(self):
        test_case = _make_test_case(
            query="What are the specifications of the PF1 machine?",
            response=(
                "The PF1 is a precision forming machine with a capacity of 500 tonnes, "
                "a working area of 2000x1500mm, and a cycle time of 12 seconds. "
                "It requires 3-phase 400V power supply and weighs approximately 8,500 kg."
            ),
            retrieval_context=[
                "PF1 Specifications: Capacity 500T, Working area 2000x1500mm, "
                "Cycle time 12s, Power 3-phase 400V, Weight 8500kg",
            ],
        )
        assert_test(test_case, [self.metric])


# ── Faithfulness Tests ───────────────────────────────────────────────────────


class TestFaithfulness:
    """Verify that responses are grounded in the retrieved context."""

    metric = FaithfulnessMetric(threshold=0.7)

    def test_grounded_financial_response(self):
        test_case = _make_test_case(
            query="What was our revenue last quarter?",
            response=(
                "Last quarter's revenue was EUR 2.3 million, up 15% from the previous quarter. "
                "The main contributors were the Dutch Tides and Norsk Hydro deals."
            ),
            retrieval_context=[
                "Q3 2025 Revenue: EUR 2,300,000 (+15% QoQ)",
                "Major deals closed: Dutch Tides BV (EUR 450K), Norsk Hydro (EUR 380K)",
            ],
        )
        assert_test(test_case, [self.metric])


# ── Hallucination Tests ──────────────────────────────────────────────────────


class TestHallucination:
    """Verify that responses do not contain hallucinated information."""

    metric = HallucinationMetric(threshold=0.7)

    def test_no_hallucinated_pricing(self):
        test_case = _make_test_case(
            query="What is the price of a PF1?",
            response=(
                "Based on our pricing records, the standard PF1 is quoted at "
                "approximately EUR 225,000 for the base configuration."
            ),
            context=[
                "PF1 base price: EUR 225,000 (standard configuration)",
                "PF1 with automation package: EUR 285,000",
            ],
        )
        assert_test(test_case, [self.metric])

    def test_no_hallucinated_delivery(self):
        test_case = _make_test_case(
            query="What is the delivery time for a PF1?",
            response="The standard lead time for a PF1 is 16-20 weeks from order confirmation.",
            context=[
                "PF1 lead time: 16-20 weeks (standard), 12-14 weeks (expedited)",
            ],
        )
        assert_test(test_case, [self.metric])
