"""Unified retrieval layer for the Ira system.

**No agent should query Qdrant or Neo4j directly.**  Every knowledge lookup
flows through :class:`UnifiedRetriever`, which fans out across the vector
store, the knowledge graph, and (optionally) Mem0 conversational memory,
then merges and reranks the results with Voyage AI Rerank (with FlashRank
as a local fallback) before returning them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from flashrank import Ranker, RerankRequest
from langfuse.decorators import observe

from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings
from ira.exceptions import DatabaseError, IngestionError, IraError
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import EntityNames, SubQueries
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_DECOMPOSE_SYSTEM_PROMPT = load_prompt("decompose_query")

_VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"


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
        self._flashrank = Ranker(model_name=reranker_model)

        self._llm = get_llm_client()
        settings = get_settings()
        self._voyage_key = settings.embedding.api_key.get_secret_value()
        self._voyage_rerank_model = settings.embedding.rerank_model

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
            except (DatabaseError, Exception):
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
            except (IraError, Exception):
                logger.warning("Knowledge discovery fallback failed", exc_info=True)

        if not merged:
            return await self._imports_fallback(query, limit)

        await self._log_retrieval(query, merged)
        return await self._rerank(query, merged, limit)

    # ── query decomposition ──────────────────────────────────────────────

    @observe()
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

        return await self._rerank(complex_query, merged, limit)

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
        return await self._rerank(query, results, limit)

    # ── backend-specific search helpers ──────────────────────────────────

    async def _search_qdrant(self, query: str, limit: int) -> list[dict[str, Any]]:
        return await self._qdrant.hybrid_search(query, limit=limit)

    async def _search_graph(self, query: str) -> list[dict[str, Any]]:
        """Extract entities from the query via LLM, then look each up in Neo4j.

        Scores are assigned based on match quality:
        - Direct name match on the queried entity: 0.85
        - 1-hop related nodes: 0.65
        - 2+-hop related nodes: 0.45
        """
        entity_names = await self._extract_entity_names(query)
        if not entity_names:
            entity_names = [query]

        query_lower = query.lower()
        all_results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for name in entity_names:
            subgraph = await self._graph.find_related_entities(name, max_hops=2)
            nodes = subgraph.get("nodes", [])
            relationships = subgraph.get("relationships", [])
            name_lower = name.lower()

            rel_strings: list[str] = []
            for rel in relationships:
                if isinstance(rel, dict):
                    rel_type = rel.get("type", "RELATED_TO")
                    from_name = rel.get("from", "?")
                    to_name = rel.get("to", "?")
                    rel_strings.append(f"{from_name} -[{rel_type}]-> {to_name}")

            for node in nodes:
                props = dict(node) if hasattr(node, "__iter__") else {"value": str(node)}
                content_parts = [f"{k}: {v}" for k, v in props.items() if v]
                content = ", ".join(content_parts)
                if content in seen:
                    continue
                seen.add(content)

                node_name = str(props.get("name", "")).lower()
                if node_name == name_lower or node_name in query_lower:
                    score = 0.85
                elif any(name_lower in str(v).lower() for v in props.values() if v):
                    score = 0.65
                else:
                    score = 0.45

                all_results.append(
                    {
                        "content": content,
                        "score": score,
                        "source": "neo4j",
                        "metadata": props,
                    }
                )

            if rel_strings:
                rel_content = "Graph relationships: " + "; ".join(rel_strings)
                if rel_content not in seen:
                    seen.add(rel_content)
                    all_results.append(
                        {
                            "content": rel_content,
                            "score": 0.75,
                            "source": "neo4j",
                            "metadata": {"type": "relationships", "entity": name},
                        }
                    )

        return all_results

    async def _extract_entity_names(self, query: str) -> list[str]:
        """Use the LLM to pull entity names (companies, people, machines) from a query."""
        system = (
            "Extract entity names from the user query. Return a JSON "
            "array of strings — company names, person names, email "
            "addresses, machine model numbers, and quote IDs. Return "
            "only the JSON array, nothing else. If no entities are "
            "found, return an empty array []."
        )
        try:
            result = await self._llm.generate_structured(
                system, query, EntityNames, name="retriever.extract_entities",
            )
            return result.entities
        except Exception:
            logger.warning("Entity name extraction failed for graph search; using raw query", exc_info=True)
        return []

    async def _search_mem0(self, query: str, limit: int) -> list[dict[str, Any]]:
        if self._mem0 is None:
            return []
        try:
            raw = self._mem0.search(
                query,
                user_id="global",
                top_k=limit,
            )
            memories = raw.get("results", raw) if isinstance(raw, dict) else raw
            return [
                {
                    "content": m.get("memory", m.get("text", "")),
                    "score": m.get("score", 0.5),
                    "source": "mem0",
                    "metadata": m.get("metadata", {}),
                }
                for m in (memories if isinstance(memories, list) else [])
            ]
        except (DatabaseError, Exception):
            logger.exception("Mem0 search failed")
            return []

    # ── retrieval logging (for graph consolidation) ────────────────────────

    async def _log_retrieval(self, query: str, results: list[dict[str, Any]]) -> None:
        try:
            from ira.brain.graph_consolidation import GraphConsolidation
            gc = GraphConsolidation(knowledge_graph=self._graph)
            chunks = [r.get("content", "")[:100] for r in results[:10]]
            sources = [r.get("source_type", "") for r in results[:10]]
            await gc.log_retrieval(query, chunks, sources)
        except (DatabaseError, Exception):
            logger.warning("Retrieval logging failed", exc_info=True)

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
        except (IngestionError, Exception):
            logger.warning("Imports fallback not available", exc_info=True)
            return []

    # ── reranking ────────────────────────────────────────────────────────

    async def _rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        if self._voyage_key:
            try:
                return await self._voyage_rerank(query, results, limit)
            except (IraError, Exception):
                logger.warning(
                    "Voyage rerank failed — falling back to FlashRank",
                    exc_info=True,
                )

        return await self._flashrank_rerank(query, results, limit)

    _MAX_DOC_CHARS = 4000
    _MAX_RERANK_DOCS = 100

    async def _voyage_rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Rerank via the Voyage AI Rerank API."""
        filtered: list[tuple[int, str]] = []
        for i, r in enumerate(results):
            doc = r.get("content", "").strip()
            if doc:
                filtered.append((i, doc[:self._MAX_DOC_CHARS]))

        if not filtered:
            return await self._flashrank_rerank(query, results, limit)

        filtered = filtered[:self._MAX_RERANK_DOCS]
        original_indices, documents = zip(*filtered)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _VOYAGE_RERANK_URL,
                json={
                    "query": query,
                    "documents": list(documents),
                    "model": self._voyage_rerank_model,
                    "top_k": min(limit, len(documents)),
                },
                headers={
                    "Authorization": f"Bearer {self._voyage_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Voyage rerank returned %d: %s",
                    resp.status_code, resp.text[:500],
                )
            resp.raise_for_status()

        data = resp.json()
        ranked_items = data.get("data", [])

        output: list[dict[str, Any]] = []
        for item in ranked_items:
            idx = item["index"]
            original = results[original_indices[idx]]
            output.append(
                {
                    "content": original.get("content", ""),
                    "score": item.get("relevance_score", 0.0),
                    "source": original.get("source", ""),
                    "source_type": original.get("source_type", ""),
                    "metadata": original.get("metadata", {}),
                }
            )

        return await self._apply_learned_corrections(output)

    async def _flashrank_rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Local FlashRank fallback reranker."""
        passages = [
            {"id": i, "text": r.get("content", ""), "meta": r}
            for i, r in enumerate(results)
        ]

        try:
            reranked = await asyncio.to_thread(
                self._flashrank.rerank,
                RerankRequest(query=query, passages=passages),
            )
        except (IraError, Exception):
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

        return await self._apply_learned_corrections(output)

    # ── learned corrections ────────────────────────────────────────────────

    async def _apply_learned_corrections(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Post-process results with learned entity corrections and competitor tags."""
        try:
            from ira.brain.correction_learner import CorrectionLearner
            learner = CorrectionLearner()
            await learner._load()

            for r in results:
                content = r.get("content", "")
                for entity in learner.get_all_learned().get("entity_corrections", {}):
                    corrected = learner.get_entity_correction(entity)
                    if corrected and entity.lower() in content.lower():
                        r.setdefault("metadata", {})["entity_correction"] = f"{entity} -> {corrected}"

                for entity in learner.get_all_learned().get("competitors", []):
                    if entity.lower() in content.lower():
                        r.setdefault("metadata", {})["competitor_mentioned"] = True
        except (IraError, Exception):
            logger.warning("Learned corrections overlay failed", exc_info=True)
        return results

    # ── LLM query decomposition ──────────────────────────────────────────

    async def _decompose_query(self, query: str) -> list[str]:
        try:
            result = await self._llm.generate_structured(
                _DECOMPOSE_SYSTEM_PROMPT, query, SubQueries,
                name="retriever.decompose",
            )
            if result.queries:
                logger.info("Decomposed query into %d sub-queries", len(result.queries))
            return result.queries
        except Exception:
            logger.exception("Query decomposition failed")
        return []
