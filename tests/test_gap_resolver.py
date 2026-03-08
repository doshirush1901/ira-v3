"""Tests for the GapResolver and related gap-resolution infrastructure.

Covers gap prioritization, resolution via mocked web search and LLM,
and Metacognition gap tracking methods.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _mock_llm_client():
    client = MagicMock()
    client.generate_text = AsyncMock(return_value="The PF1 has a 500T capacity.")
    client.generate_structured = AsyncMock()
    return client


# ── GapResolver.prioritize_gaps ──────────────────────────────────────────────


class TestGapPrioritization:
    """Verify gap scoring and sorting logic."""

    def test_unknown_state_scores_higher_than_partial(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        resolver = GapResolver(long_term_memory=ltm)

        now = datetime.now(timezone.utc)
        gaps = [
            {"query": "PF1 specs", "state": "PARTIAL", "created_at": now.isoformat(), "gaps": []},
            {"query": "PF1 specs", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
        ]

        prioritized = resolver.prioritize_gaps(gaps)
        assert prioritized[0]["state"] == "UNKNOWN"

    def test_frequent_gaps_rank_higher(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        resolver = GapResolver(long_term_memory=ltm)

        now = datetime.now(timezone.utc)
        gaps = [
            {"query": "rare question", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
            {"query": "common question", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
            {"query": "common question", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
            {"query": "common question", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
        ]

        prioritized = resolver.prioritize_gaps(gaps)
        assert prioritized[0]["query"] == "common question"

    def test_recent_gaps_rank_higher_than_old(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        resolver = GapResolver(long_term_memory=ltm)

        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=30)).isoformat()
        gaps = [
            {"query": "old question", "state": "UNKNOWN", "created_at": old, "gaps": []},
            {"query": "new question", "state": "UNKNOWN", "created_at": now.isoformat(), "gaps": []},
        ]

        prioritized = resolver.prioritize_gaps(gaps)
        assert prioritized[0]["query"] == "new question"


# ── GapResolver.resolve_gap ──────────────────────────────────────────────────


class TestGapResolution:
    """Verify the resolve_gap method with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_resolve_gap_stores_fact(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        ltm.store_fact = AsyncMock(return_value=[])
        meta = MagicMock()
        meta.mark_gap_resolved = AsyncMock()

        with patch("ira.brain.gap_resolver.get_llm_client", return_value=_mock_llm_client()), \
             patch("ira.brain.gap_resolver.load_prompt", return_value="test prompt"):
            resolver = GapResolver(long_term_memory=ltm, metacognition=meta)

        gap = {"id": 1, "query": "PF1 capacity", "gaps": ["capacity unknown"], "state": "UNKNOWN"}
        result = await resolver.resolve_gap(gap)

        assert result is not None
        assert "500T" in result
        ltm.store_fact.assert_called_once()
        meta.mark_gap_resolved.assert_called_once_with(1, result)

    @pytest.mark.asyncio
    async def test_resolve_gap_returns_none_on_no_answer(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        ltm.store_fact = AsyncMock()

        mock_llm = _mock_llm_client()
        mock_llm.generate_text = AsyncMock(return_value="NONE")

        with patch("ira.brain.gap_resolver.get_llm_client", return_value=mock_llm), \
             patch("ira.brain.gap_resolver.load_prompt", return_value="test prompt"):
            resolver = GapResolver(long_term_memory=ltm)

        gap = {"id": 2, "query": "unknown thing", "gaps": [], "state": "UNKNOWN"}
        result = await resolver.resolve_gap(gap)

        assert result is None
        ltm.store_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_gap_with_web_search(self):
        from ira.brain.gap_resolver import GapResolver

        ltm = MagicMock()
        ltm.store_fact = AsyncMock(return_value=[])

        with patch("ira.brain.gap_resolver.get_llm_client", return_value=_mock_llm_client()), \
             patch("ira.brain.gap_resolver.load_prompt", return_value="test prompt"):
            resolver = GapResolver(long_term_memory=ltm)

        web_search = AsyncMock(return_value=[
            {"title": "PF1 Info", "url": "https://example.com", "snippet": "PF1 has 500T capacity"},
        ])

        gap = {"id": 3, "query": "PF1 capacity", "gaps": [], "state": "UNKNOWN"}
        result = await resolver.resolve_gap(gap, web_search_fn=web_search)

        assert result is not None
        web_search.assert_called_once()


# ── Metacognition gap tracking ────────────────────────────────────────────────


class TestMetacognitionGapTracking:
    """Verify gap resolution columns and methods."""

    @pytest.mark.asyncio
    async def test_get_unresolved_gaps(self, tmp_path):
        from ira.memory.metacognition import Metacognition

        db_path = str(tmp_path / "test_meta.db")

        with patch("ira.memory.metacognition.get_llm_client", return_value=_mock_llm_client()), \
             patch("ira.memory.metacognition.load_prompt", return_value="test"):
            meta = Metacognition(db_path=db_path)
            await meta.initialize()

        from ira.data.models import KnowledgeState
        await meta.log_knowledge_gap("test query", KnowledgeState.UNKNOWN, ["gap1"])

        gaps = await meta.get_unresolved_gaps()
        assert len(gaps) == 1
        assert gaps[0]["query"] == "test query"

        await meta.close()

    @pytest.mark.asyncio
    async def test_mark_gap_resolved(self, tmp_path):
        from ira.memory.metacognition import Metacognition

        db_path = str(tmp_path / "test_meta2.db")

        with patch("ira.memory.metacognition.get_llm_client", return_value=_mock_llm_client()), \
             patch("ira.memory.metacognition.load_prompt", return_value="test"):
            meta = Metacognition(db_path=db_path)
            await meta.initialize()

        from ira.data.models import KnowledgeState
        await meta.log_knowledge_gap("test query", KnowledgeState.UNKNOWN, ["gap1"])

        gaps = await meta.get_unresolved_gaps()
        gap_id = gaps[0]["id"]

        await meta.mark_gap_resolved(gap_id, "Resolved: PF1 has 500T capacity")

        unresolved = await meta.get_unresolved_gaps()
        assert len(unresolved) == 0

        await meta.close()
