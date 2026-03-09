"""Lightweight smoke checks for representative routing paths."""

from __future__ import annotations

from ira.brain.deterministic_router import DeterministicRouter


def test_representative_queries_route_to_expected_intents() -> None:
    router = DeterministicRouter()

    samples = [
        ("show me pipeline and conversion rate this quarter", "SALES_PIPELINE"),
        ("how much is the quote pricing for the machine", "QUOTE_REQUEST"),
        ("vendor procurement supplier component inventory status", "VENDOR_PROCUREMENT"),
        ("show quality punch list for installation", "QUALITY_MANAGEMENT"),
        ("what did we discuss in previous conversation", "MEMORY_RECALL"),
    ]

    for query, expected_intent in samples:
        routing = router.route(query)
        assert routing is not None, f"Expected deterministic route for: {query}"
        assert routing["intent"] == expected_intent
