from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ira.brain.retriever import UnifiedRetriever
from ira.services.resilience import RetryPolicy


def _make_retriever() -> UnifiedRetriever:
    r = UnifiedRetriever.__new__(UnifiedRetriever)
    r._qdrant = MagicMock()
    r._graph = MagicMock()
    r._mem0 = None
    r._flashrank = MagicMock()
    r._llm = MagicMock()
    r._voyage_key = "voyage-key"
    r._voyage_rerank_model = "rerank-2.5"
    r._backend_timeouts_seconds = {"qdrant": 1.0, "neo4j": 1.0, "mem0": 0.02}
    r._mem0_timeout_seconds = 0.02
    r._flashrank_timeout_seconds = 1.0
    r._external_retry = RetryPolicy(max_attempts=2, base_delay_seconds=0.01, max_delay_seconds=0.02)
    r._mem0_breaker = None
    r._voyage_breaker = None
    r._stitch_graph_to_vectors = AsyncMock(side_effect=lambda merged: merged)
    r._log_retrieval = AsyncMock()
    r._imports_fallback = AsyncMock(return_value=[])
    r._apply_learned_corrections = AsyncMock(side_effect=lambda items: items)
    return r


@pytest.mark.asyncio
async def test_mem0_timeout_does_not_block_other_sources():
    retriever = _make_retriever()
    retriever._mem0 = MagicMock()

    retriever._search_qdrant = AsyncMock(return_value=[
        {"content": "qdrant ok", "score": 0.8, "source": "doc1", "metadata": {}},
    ])
    retriever._search_graph = AsyncMock(return_value=[])

    async def _slow_mem0(*args, **kwargs):
        await asyncio.sleep(0.2)
        return []

    retriever._search_mem0 = AsyncMock(side_effect=_slow_mem0)
    retriever._rerank = AsyncMock(side_effect=lambda _q, rows, _l: rows)

    out = await retriever.search("test", limit=5)
    assert out
    assert out[0]["content"] == "qdrant ok"
    assert out[0]["source_type"] == "qdrant"


@pytest.mark.asyncio
async def test_voyage_rerank_retries_then_succeeds():
    retriever = _make_retriever()
    results = [{"content": "a", "source": "s", "source_type": "qdrant", "metadata": {}}]
    call_count = {"n": 0}

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"data": [{"index": 0, "relevance_score": 0.9}]}

    async def _post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("temporary connect failure")
        return _Resp()

    mock_client = AsyncMock()
    mock_client.post.side_effect = _post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("ira.brain.retriever.httpx.AsyncClient", return_value=mock_client):
        reranked = await retriever._voyage_rerank("query", results, limit=1)

    assert call_count["n"] == 2
    assert len(reranked) == 1
    assert reranked[0]["score"] == 0.9


@pytest.mark.asyncio
async def test_rerank_falls_back_to_flashrank_when_voyage_persistently_fails():
    retriever = _make_retriever()
    results = [{"content": "a", "score": 0.7, "source": "s", "source_type": "qdrant", "metadata": {}}]
    retriever._voyage_rerank = AsyncMock(side_effect=httpx.HTTPError("down"))
    retriever._flashrank_rerank = AsyncMock(return_value=[{"content": "a", "score": 0.7}])

    out = await retriever._rerank("query", results, limit=1)
    assert out == [{"content": "a", "score": 0.7}]
    retriever._flashrank_rerank.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_timeout_only_skips_timed_out_source():
    retriever = _make_retriever()
    retriever._mem0 = MagicMock()

    async def _slow_graph(*args, **kwargs):
        await asyncio.sleep(0.2)
        return [{"content": "graph late"}]

    retriever._search_qdrant = AsyncMock(return_value=[
        {"content": "vector data", "score": 0.9, "source": "vec", "metadata": {}},
    ])
    retriever._search_graph = AsyncMock(side_effect=_slow_graph)
    retriever._search_mem0 = AsyncMock(return_value=[])
    retriever._backend_timeouts_seconds = {"qdrant": 1.0, "neo4j": 0.02, "mem0": 1.0}
    retriever._rerank = AsyncMock(side_effect=lambda _q, rows, _l: rows)

    out = await retriever.search("query", limit=5)
    assert out
    assert any(r.get("source_type") == "qdrant" for r in out)
    assert not any(r.get("source_type") == "neo4j" for r in out)
