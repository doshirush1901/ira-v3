"""Qdrant vector-database manager for Ira's knowledge base.

Provides collection lifecycle management, batched upserts of
:class:`~ira.data.models.KnowledgeItem` objects, dense vector search,
and hybrid (dense + keyword filter) retrieval.  All operations are async
and go through :class:`~ira.brain.embeddings.EmbeddingService` for
embedding generation.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from ira.brain.embeddings import EmbeddingService
from ira.config import QdrantConfig, get_settings
from ira.data.models import KnowledgeItem

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 100


class QdrantManager:
    """Async wrapper around :class:`AsyncQdrantClient`."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        config: QdrantConfig | None = None,
    ) -> None:
        cfg = config or get_settings().qdrant
        self._client = AsyncQdrantClient(url=cfg.url)
        self._embeddings = embedding_service
        self._default_collection = cfg.collection

    # ── collection lifecycle ─────────────────────────────────────────────

    async def ensure_collection(
        self,
        name: str | None = None,
        vector_size: int = 1024,
    ) -> None:
        """Create the collection if it does not already exist.

        Defaults to cosine distance, which matches the normalised Voyage
        embeddings.
        """
        collection = name or self._default_collection
        try:
            if await self._client.collection_exists(collection):
                logger.debug("Collection '%s' already exists", collection)
                return

            await self._client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection '%s' (dim=%d)", collection, vector_size)
        except Exception:
            logger.exception("Failed to ensure collection '%s'", collection)
            raise

    # ── upsert ───────────────────────────────────────────────────────────

    async def upsert_items(
        self,
        items: Sequence[KnowledgeItem],
        collection: str | None = None,
    ) -> int:
        """Embed and upsert knowledge items, returning the count stored.

        Items are embedded in one call (the embedding service handles its
        own batching) and then upserted to Qdrant in batches of
        ``_UPSERT_BATCH_SIZE``.
        """
        if not items:
            return 0

        col = collection or self._default_collection
        texts = [item.content for item in items]

        try:
            vectors = await self._embeddings.embed_texts(texts)
        except Exception:
            logger.exception("Embedding failed for %d items", len(items))
            raise

        points = [
            models.PointStruct(
                id=_uuid_to_hex(item.id),
                vector=vector,
                payload={
                    "content": item.content,
                    "source": item.source,
                    "source_category": item.source_category,
                    "metadata": item.metadata,
                    "created_at": item.created_at.isoformat(),
                },
            )
            for item, vector in zip(items, vectors)
        ]

        upserted = 0
        for start in range(0, len(points), _UPSERT_BATCH_SIZE):
            batch = points[start : start + _UPSERT_BATCH_SIZE]
            try:
                await self._client.upsert(collection_name=col, points=batch)
                upserted += len(batch)
            except Exception:
                logger.exception(
                    "Qdrant upsert failed at offset %d (batch size %d)",
                    start,
                    len(batch),
                )
                raise

        logger.info("Upserted %d items into '%s'", upserted, col)
        return upserted

    # ── search ───────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Dense vector search — embed the query and find nearest neighbours."""
        col = collection or self._default_collection

        try:
            query_vector = await self._embeddings.embed_query(query)
            hits = await self._client.search(
                collection_name=col,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
            )
        except Exception:
            logger.exception("Search failed in '%s'", col)
            raise

        return [_hit_to_dict(hit) for hit in hits]

    async def hybrid_search(
        self,
        query: str,
        collection: str | None = None,
        limit: int = 10,
        keyword_filter: models.Filter | None = None,
        source_category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Dense vector search combined with Qdrant payload filtering.

        If *source_category* is provided a ``must`` match condition is
        built automatically.  For more complex predicates pass a full
        :class:`qdrant_client.models.Filter` via *keyword_filter*.
        """
        col = collection or self._default_collection

        if keyword_filter is None and source_category is not None:
            keyword_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_category",
                        match=models.MatchValue(value=source_category),
                    )
                ]
            )

        try:
            query_vector = await self._embeddings.embed_query(query)
            hits = await self._client.search(
                collection_name=col,
                query_vector=query_vector,
                query_filter=keyword_filter,
                limit=limit,
            )
        except Exception:
            logger.exception("Hybrid search failed in '%s'", col)
            raise

        return [_hit_to_dict(hit) for hit in hits]

    # ── cleanup ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> QdrantManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


# ── helpers ──────────────────────────────────────────────────────────────────


def _uuid_to_hex(uid: UUID) -> str:
    """Qdrant accepts string or int point IDs; we use the UUID hex."""
    return uid.hex


def _hit_to_dict(hit: models.ScoredPoint) -> dict[str, Any]:
    payload = hit.payload or {}
    return {
        "content": payload.get("content", ""),
        "score": hit.score,
        "source": payload.get("source", ""),
        "metadata": payload.get("metadata", {}),
        "source_category": payload.get("source_category", ""),
    }
