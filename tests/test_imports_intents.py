"""Tests for imports intent taxonomy and intent-aware index search."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ira.brain.imports_intents import (
    infer_intents_from_text,
    infer_query_intents,
    normalize_intent_tags,
)


def test_normalize_intent_tags_handles_aliases_and_csv() -> None:
    tags = normalize_intent_tags(["customer quote", "unknown_intent", "spec_sheet"])
    assert "quote_customer" in tags
    assert "spec_sheet" in tags
    assert "unknown_intent" not in tags

    csv_tags = normalize_intent_tags("vendor quote, part detail")
    assert csv_tags == ["quote_vendor", "part_detail"]


def test_infer_query_intents_detects_counterparty_and_role() -> None:
    intents, counterparty, role = infer_query_intents(
        "Find latest vendor quote and part detail for PF1 tooling",
    )
    assert "quote_vendor" in intents
    assert counterparty == "vendor"
    assert role in {"quote_vendor", "part_detail"}


def test_infer_intents_uses_doc_type_fallback() -> None:
    intents, _counterparty, role, confidence = infer_intents_from_text(
        "short content without direct lexical triggers",
        doc_type="technical_spec",
    )
    assert "spec_sheet" in intents
    assert role == "spec_sheet"
    assert isinstance(confidence, dict)


@pytest.mark.asyncio
async def test_search_index_honors_intent_filters() -> None:
    from ira.brain.imports_metadata_index import search_index

    index = {
        "files": {
            "a.pdf": {
                "path": "/tmp/a.pdf",
                "name": "a.pdf",
                "summary": "Vendor quote for thermoforming line",
                "doc_type": "quote",
                "machines": [],
                "topics": ["pricing"],
                "entities": ["Acme"],
                "keywords": ["quote", "vendor", "pricing"],
                "intent_tags": ["quote_vendor"],
                "counterparty_type": "vendor",
                "document_role": "quote_vendor",
            },
            "b.pdf": {
                "path": "/tmp/b.pdf",
                "name": "b.pdf",
                "summary": "Customer quote with project update",
                "doc_type": "quote",
                "machines": [],
                "topics": ["pricing"],
                "entities": ["Beta"],
                "keywords": ["quote", "customer"],
                "intent_tags": ["quote_customer"],
                "counterparty_type": "customer",
                "document_role": "quote_customer",
            },
        },
    }

    with patch("ira.brain.imports_metadata_index.load_index", new_callable=AsyncMock, return_value=index):
        results = await search_index(
            "quote",
            intent_filters=["quote_vendor"],
            counterparty_filter="vendor",
        )

    assert len(results) == 1
    assert results[0]["name"] == "a.pdf"
