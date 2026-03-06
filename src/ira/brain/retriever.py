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
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DECOMPOSE_SYSTEM_PROMPT = load_prompt("decompose_query")


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

        When the primary backends return no results, the imports fallback
        retriever (Alexandros's metadata index) is consulted automatically.
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
            try:
                from ira.brain.knowledge_discovery import KnowledgeDiscovery
                discovery = KnowledgeDiscovery(
                    retriever=self, qdrant_manager=self._qdrant,
                    embedding_service=self._qdrant._embeddings,
                )
                discovered = await discovery.discover_and_store(query, [])
                if discovered:
                    for d in discovered:
                        d["source_type"] = "discovery"
                    merged.extend(discovered)
            except Exception:
                logger.debug("Knowledge discovery not available", exc_info=True)

        if not merged:
            return await self._imports_fallback(query, limit)

        self._log_retrieval(query, merged)
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
        """Extract entities from the query via LLM, then look each up in Neo4j."""
        entity_names = await self._extract_entity_names(query)
        if not entity_names:
            entity_names = [query]

        all_results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for name in entity_names:
            subgraph = await self._graph.find_related_entities(name, max_hops=1)
            nodes = subgraph.get("nodes", [])
            for node in nodes:
                props = dict(node) if hasattr(node, "__iter__") else {"value": str(node)}
                content_parts = [f"{k}: {v}" for k, v in props.items() if v]
                content = ", ".join(content_parts)
                if content in seen:
                    continue
                seen.add(content)
                all_results.append(
                    {
                        "content": content,
                        "score": 0.5,
                        "source": "neo4j",
                        "metadata": props,
                    }
                )
        return all_results

    async def _extract_entity_names(self, query: str) -> list[str]:
        """Use the LLM to pull entity names (companies, people, machines) from a query."""
        if not self._openai_key:
            return []

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract entity names from the user query. Return a JSON "
                        "array of strings — company names, person names, email "
                        "addresses, machine model numbers, and quote IDs. Return "
                        "only the JSON array, nothing else. If no entities are "
                        "found, return an empty array []."
                    ),
                },
                {"role": "user", "content": query},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                names = json.loads(content)
                if isinstance(names, list) and all(isinstance(n, str) for n in names):
                    return names
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            logger.debug("Entity name extraction failed for graph search; using raw query")

        return []

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

    # ── retrieval logging (for graph consolidation) ────────────────────────

    def _log_retrieval(self, query: str, results: list[dict[str, Any]]) -> None:
        try:
            from ira.brain.graph_consolidation import GraphConsolidation
            gc = GraphConsolidation(knowledge_graph=self._graph)
            chunks = [r.get("content", "")[:100] for r in results[:10]]
            sources = [r.get("source_type", "") for r in results[:10]]
            gc.log_retrieval(query, chunks, sources)
        except Exception:
            pass

    # ── imports fallback ───────────────────────────────────────────────────

    async def _imports_fallback(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Last-resort: search the raw imports archive via Alexandros's metadata index."""
        try:
            from ira.brain.imports_fallback_retriever import fallback_retrieve

            results = await fallback_retrieve(query)
            return [
                {
                    "content": r.get("content", ""),
                    "score": r.get("relevance", 0.5),
                    "source": r.get("source", ""),
                    "source_type": "imports_fallback",
                    "metadata": {"filename": r.get("filename", ""), "doc_type": r.get("doc_type", "")},
                }
                for r in results[:limit]
            ]
        except Exception:
            logger.debug("Imports fallback not available", exc_info=True)
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

        return self._apply_learned_corrections(output)

    # ── learned corrections ────────────────────────────────────────────────

    def _apply_learned_corrections(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Post-process results with learned entity corrections and competitor tags."""
        try:
            from ira.brain.correction_learner import CorrectionLearner
            learner = CorrectionLearner()

            for r in results:
                content = r.get("content", "")
                for entity in learner.get_all_learned().get("entity_corrections", {}):
                    corrected = learner.get_entity_correction(entity)
                    if corrected and entity.lower() in content.lower():
                        r.setdefault("metadata", {})["entity_correction"] = f"{entity} -> {corrected}"

                for entity in learner.get_all_learned().get("competitors", []):
                    if entity.lower() in content.lower():
                        r.setdefault("metadata", {})["competitor_mentioned"] = True
        except Exception:
            pass
        return results

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
