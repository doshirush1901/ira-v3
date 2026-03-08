"""Tests for provenance tracking — chunk IDs and citation formatting.

Verifies that Qdrant results carry chunk IDs through the retrieval
pipeline and that agent tools format citations correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.brain.retriever import UnifiedRetriever


# ── Qdrant _hit_to_dict ──────────────────────────────────────────────────────


class TestHitToDict:
    """Verify that _hit_to_dict includes the point ID."""

    def test_includes_id_field(self):
        from ira.brain.qdrant_manager import _hit_to_dict

        hit = MagicMock()
        hit.id = "abc123"
        hit.score = 0.85
        hit.payload = {
            "content": "PF1 specs",
            "source": "specs.pdf",
            "source_category": "specs",
            "metadata": {},
        }

        result = _hit_to_dict(hit)
        assert "id" in result
        assert result["id"] == "abc123"

    def test_id_is_stringified(self):
        from ira.brain.qdrant_manager import _hit_to_dict

        hit = MagicMock()
        hit.id = 42
        hit.score = 0.5
        hit.payload = {"content": "test", "source": "doc.txt"}

        result = _hit_to_dict(hit)
        assert result["id"] == "42"


# ── Retriever reranking preserves ID ──────────────────────────────────────────


class TestRetrieverPreservesId:
    """Verify that reranking methods propagate the id field."""

    @pytest.fixture
    def retriever(self):
        qdrant = MagicMock()
        graph = MagicMock()
        with patch("ira.brain.retriever.get_settings") as mock_settings, \
             patch("ira.brain.retriever.Ranker"):
            mock_settings.return_value.embedding.api_key.get_secret_value.return_value = ""
            mock_settings.return_value.embedding.rerank_model = "test"
            r = UnifiedRetriever(qdrant=qdrant, graph=graph)
        return r

    @pytest.mark.asyncio
    async def test_flashrank_rerank_preserves_id(self, retriever):
        results = [
            {"id": "chunk-1", "content": "PF1 specs", "score": 0.8, "source": "a.pdf", "source_type": "qdrant", "metadata": {}},
            {"id": "chunk-2", "content": "PF2 specs", "score": 0.6, "source": "b.pdf", "source_type": "qdrant", "metadata": {}},
        ]

        with patch.object(retriever, "_flashrank") as mock_ranker:
            mock_ranker.rerank.return_value = [
                {"id": 0, "text": "PF1 specs", "score": 0.9, "meta": results[0]},
                {"id": 1, "text": "PF2 specs", "score": 0.7, "meta": results[1]},
            ]
            with patch.object(retriever, "_apply_learned_corrections", new_callable=AsyncMock, side_effect=lambda x: x):
                output = await retriever._flashrank_rerank("PF1", results, limit=2)

        assert len(output) == 2
        assert output[0]["id"] == "chunk-1"
        assert output[1]["id"] == "chunk-2"


# ── Agent tool citation format ────────────────────────────────────────────────


class TestAgentCitationFormat:
    """Verify that _tool_search_knowledge includes Source and Chunk tags."""

    @pytest.mark.asyncio
    async def test_citation_format(self):
        from ira.agents.base_agent import BaseAgent

        retriever = MagicMock()
        retriever.search = AsyncMock(return_value=[
            {"id": "abc123", "content": "PF1 capacity is 500T", "source": "specs.pdf", "source_type": "qdrant", "metadata": {}},
        ])
        bus = MagicMock()

        class TestAgent(BaseAgent):
            name = "test"
            role = "tester"
            description = "test agent"

            async def handle(self, query, context=None):
                return ""

        with patch("ira.agents.base_agent.get_settings") as mock_settings, \
             patch("ira.agents.base_agent.get_llm_client"):
            mock_settings.return_value.app.react_max_iterations = 5
            agent = TestAgent(retriever=retriever, bus=bus)

        result = await agent._tool_search_knowledge("PF1 capacity")
        assert "[Source: specs.pdf, Chunk: abc123]" in result

    @pytest.mark.asyncio
    async def test_format_context_includes_citation(self):
        from ira.agents.base_agent import BaseAgent

        retriever = MagicMock()
        bus = MagicMock()

        class TestAgent(BaseAgent):
            name = "test"
            role = "tester"
            description = "test agent"

            async def handle(self, query, context=None):
                return ""

        with patch("ira.agents.base_agent.get_settings") as mock_settings, \
             patch("ira.agents.base_agent.get_llm_client"):
            mock_settings.return_value.app.react_max_iterations = 5
            agent = TestAgent(retriever=retriever, bus=bus)

        kb_results = [
            {"id": "xyz789", "content": "PF2 weight 12000kg", "source": "pf2_spec.pdf"},
        ]
        formatted = agent._format_context(kb_results)
        assert "[Source: pf2_spec.pdf, Chunk: xyz789]" in formatted
