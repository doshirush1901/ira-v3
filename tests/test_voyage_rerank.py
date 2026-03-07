"""Tests for the Voyage AI Rerank upgrade in UnifiedRetriever."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ira.brain.retriever import UnifiedRetriever


def _make_retriever() -> UnifiedRetriever:
    """Build a retriever with mocked backends."""
    r = UnifiedRetriever.__new__(UnifiedRetriever)
    r._qdrant = MagicMock()
    r._graph = MagicMock()
    r._mem0 = None
    r._flashrank = MagicMock()
    r._openai_key = "test-key"
    r._openai_model = "gpt-4.1"
    r._voyage_key = "test-voyage-key"
    r._voyage_rerank_model = "rerank-2.5"
    return r


def _sample_results() -> list[dict]:
    return [
        {"content": "Machine spec A", "score": 0.8, "source": "qdrant", "source_type": "qdrant", "metadata": {}},
        {"content": "Machine spec B", "score": 0.6, "source": "qdrant", "source_type": "qdrant", "metadata": {}},
        {"content": "Machine spec C", "score": 0.4, "source": "neo4j", "source_type": "neo4j", "metadata": {}},
    ]


class TestVoyageRerank:
    """Voyage AI Rerank as primary reranker."""

    @patch("ira.brain.retriever.httpx.AsyncClient")
    async def test_voyage_rerank_success(self, mock_client_cls):
        retriever = _make_retriever()
        results = _sample_results()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.80},
            ]
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        reranked = await retriever._voyage_rerank("machine specs", results, limit=2)

        assert len(reranked) == 2
        assert reranked[0]["content"] == "Machine spec C"
        assert reranked[0]["score"] == 0.95
        assert reranked[1]["content"] == "Machine spec A"

    @patch("ira.brain.retriever.httpx.AsyncClient")
    async def test_voyage_rerank_sends_correct_payload(self, mock_client_cls):
        retriever = _make_retriever()
        results = _sample_results()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"index": 0, "relevance_score": 0.9}]}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await retriever._voyage_rerank("test query", results, limit=1)

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["query"] == "test query"
        assert payload["model"] == "rerank-2.5"
        assert len(payload["documents"]) == 3
        assert payload["top_k"] == 1


class TestFlashRankFallback:
    """FlashRank is used when Voyage is unavailable or fails."""

    async def test_fallback_when_no_voyage_key(self):
        retriever = _make_retriever()
        retriever._voyage_key = ""
        results = _sample_results()

        mock_reranked = [
            MagicMock(
                __getitem__=lambda self, k: {"text": "Machine spec A", "score": 0.9, "meta": results[0]}[k],
                get=lambda k, d=None: {"text": "Machine spec A", "score": 0.9, "meta": results[0]}.get(k, d),
            )
        ]
        retriever._flashrank.rerank.return_value = mock_reranked

        reranked = await retriever._rerank("test", results, limit=1)
        retriever._flashrank.rerank.assert_called_once()
        assert len(reranked) == 1

    @patch("ira.brain.retriever.httpx.AsyncClient")
    async def test_fallback_when_voyage_fails(self, mock_client_cls):
        retriever = _make_retriever()
        results = _sample_results()

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("API down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        mock_reranked = [
            MagicMock(
                __getitem__=lambda self, k: {"text": "Machine spec A", "score": 0.9, "meta": results[0]}[k],
                get=lambda k, d=None: {"text": "Machine spec A", "score": 0.9, "meta": results[0]}.get(k, d),
            )
        ]
        retriever._flashrank.rerank.return_value = mock_reranked

        reranked = await retriever._rerank("test", results, limit=1)
        retriever._flashrank.rerank.assert_called_once()

    async def test_empty_results(self):
        retriever = _make_retriever()
        reranked = await retriever._rerank("test", [], limit=5)
        assert reranked == []
