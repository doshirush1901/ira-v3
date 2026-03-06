"""Unified retrieval layer for the Ira system.

**No agent should query Qdrant or Neo4j directly.**  Every knowledge lookup
flows through :class:`UnifiedRetriever`, which fans out across the vector
store, the knowledge graph, and (optionally) Mem0 conversational memory,
then merges and reranks the results with FlashRank before returning them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from flashrank import Ranker, RerankRequest

from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings

logger = logging.getLogger(__name__)

_DECOMPOSE_SYSTEM_PROMPT = """\
You are a query decomposition engine.  Given a complex user question,
break it into 2-4 simpler, self-contained sub-queries that together
cover the original intent.

Return ONLY a JSON array of strings — no markdown fences, no explanation.
Example: ["sub-query 1", "sub-query 2"]"""


class UnifiedRetriever:
    """Single entry-point for all knowledge retrieval in Ira."""

    def __init__(
        self,
        qdrant: QdrantManager,
        graph: KnowledgeGraph,
        mem0_client: Any | None = None,
        *,
        reranker_model: str = "ms-marco-MiniLM-L-12-v2",
    ) -> None:
        self._qdrant = qdrant
        self._graph = graph
        self._mem0 = mem0_client
        self._ranker = Ranker(model_name=reranker_model)

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

    # ── primary search ───────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        sources: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fan-out search across Qdrant, Neo4j, and Mem0, then rerank.

        *sources* can restrict which backends are queried.  Valid values:
        ``"qdrant"``, ``"neo4j"``, ``"mem0"``.  ``None`` means all.
        """
        use = set(sources) if sources else {"qdrant", "neo4j", "mem0"}

        tasks: dict[str, asyncio.Task[Any]] = {}
        if "qdrant" in use:
            tasks["qdrant"] = asyncio.create_task(self._search_qdrant(query, limit=limit * 2))
        if "neo4j" in use:
            tasks["neo4j"] = asyncio.create_task(self._search_graph(query))
        if "mem0" in use and self._mem0 is not None:
            tasks["mem0"] = asyncio.create_task(self._search_mem0(query, limit=limit))

        merged: list[dict[str, Any]] = []
        for source_type, task in tasks.items():
            try:
                results = await task
                for r in results:
                    r["source_type"] = source_type
                merged.extend(results)
            except Exception:
                logger.exception("Retrieval from %s failed", source_type)

        if not merged:
            return []

        return self._rerank(query, merged, limit)

    # ── query decomposition ──────────────────────────────────────────────

    async def decompose_and_search(
        self,
        complex_query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Break a complex query into sub-queries, search each, and merge."""
        sub_queries = await self._decompose_query(complex_query)
        if not sub_queries:
            return await self.search(complex_query, limit=limit)

        tasks = [self.search(sq, limit=limit) for sq in sub_queries]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[dict[str, Any]] = []
        seen_contents: set[str] = set()
        for result_set in all_results:
            if isinstance(result_set, BaseException):
                logger.exception("Sub-query search failed", exc_info=result_set)
                continue
            for r in result_set:
                content_key = r.get("content", "")[:200]
                if content_key not in seen_contents:
                    seen_contents.add(content_key)
                    merged.append(r)

        if not merged:
            return []

        return self._rerank(complex_query, merged, limit)

    # ── category-filtered search ─────────────────────────────────────────

    async def search_by_category(
        self,
        query: str,
        category: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search Qdrant restricted to a single source_category."""
        results = await self._qdrant.hybrid_search(
            query, source_category=category, limit=limit * 2,
        )
        for r in results:
            r["source_type"] = "qdrant"
        return self._rerank(query, results, limit)

    # ── backend-specific search helpers ──────────────────────────────────

    async def _search_qdrant(self, query: str, limit: int) -> list[dict[str, Any]]:
        return await self._qdrant.hybrid_search(query, limit=limit)

    async def _search_graph(self, query: str) -> list[dict[str, Any]]:
        """Extract key terms from the query and look them up in Neo4j."""
        subgraph = await self._graph.find_related_entities(query, max_hops=1)
        nodes = subgraph.get("nodes", [])
        if not nodes:
            return []

        results: list[dict[str, Any]] = []
        for node in nodes:
            props = dict(node) if hasattr(node, "__iter__") else {"value": str(node)}
            content_parts = [f"{k}: {v}" for k, v in props.items() if v]
            results.append(
                {
                    "content": ", ".join(content_parts),
                    "score": 0.5,
                    "source": "neo4j",
                    "metadata": props,
                }
            )
        return results

    async def _search_mem0(self, query: str, limit: int) -> list[dict[str, Any]]:
        if self._mem0 is None:
            return []
        try:
            memories = self._mem0.search(query, limit=limit)
            return [
                {
                    "content": m.get("memory", m.get("text", "")),
                    "score": m.get("score", 0.5),
                    "source": "mem0",
                    "metadata": m.get("metadata", {}),
                }
                for m in (memories if isinstance(memories, list) else [])
            ]
        except Exception:
            logger.exception("Mem0 search failed")
            return []

    # ── reranking ────────────────────────────────────────────────────────

    def _rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        passages = [
            {"id": i, "text": r.get("content", ""), "meta": r}
            for i, r in enumerate(results)
        ]

        try:
            reranked = self._ranker.rerank(
                RerankRequest(query=query, passages=passages)
            )
        except Exception:
            logger.exception("FlashRank reranking failed; returning by original score")
            results.sort(key=lambda r: r.get("score", 0), reverse=True)
            return results[:limit]

        output: list[dict[str, Any]] = []
        for item in reranked[:limit]:
            meta: dict[str, Any] = item.get("meta") or item.get("metadata") or {}
            output.append(
                {
                    "content": item.get("text", ""),
                    "score": item.get("score", 0.0),
                    "source": meta.get("source", ""),
                    "source_type": meta.get("source_type", ""),
                    "metadata": meta.get("metadata", {}),
                }
            )
        return output

    # ── LLM query decomposition ──────────────────────────────────────────

    async def _decompose_query(self, query: str) -> list[str]:
        if not self._openai_key:
            logger.warning("No OpenAI key; skipping query decomposition")
            return []

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _DECOMPOSE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                sub_queries = json.loads(content)
                if isinstance(sub_queries, list) and all(isinstance(q, str) for q in sub_queries):
                    logger.info("Decomposed query into %d sub-queries", len(sub_queries))
                    return sub_queries
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            logger.exception("Query decomposition failed")

        return []
