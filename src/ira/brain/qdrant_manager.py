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
from ira.exceptions import DatabaseError, IraError, LLMError

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 100


class QdrantManager:
    """Async wrapper around :class:`AsyncQdrantClient`."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        config: QdrantConfig | None = None,
        event_bus: Any | None = None,
    ) -> None:
        cfg = config or get_settings().qdrant
        api_key = cfg.api_key.get_secret_value() or None
        self._client = AsyncQdrantClient(url=cfg.url, api_key=api_key)
        self._embeddings = embedding_service
        self._default_collection = cfg.collection
        self._event_bus = event_bus

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

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
        except (DatabaseError, Exception):
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
        except (LLMError, Exception):
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
            except (DatabaseError, Exception):
                logger.exception(
                    "Qdrant upsert failed at offset %d (batch size %d)",
                    start,
                    len(batch),
                )
                raise

        logger.info("Upserted %d items into '%s'", upserted, col)

        if self._event_bus is not None and upserted > 0:
            from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
            try:
                await self._event_bus.emit(DataEvent(
                    event_type=EventType.CHUNK_UPSERTED,
                    entity_type="knowledge_chunk",
                    entity_id=col,
                    payload={
                        "collection": col,
                        "count": upserted,
                        "sources": list({it.source for it in items[:10]}),
                    },
                    source_store=SourceStore.QDRANT,
                ))
            except (IraError, Exception):
                logger.debug("Qdrant event emission failed", exc_info=True)

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
            result = await self._client.query_points(
                collection_name=col,
                query=query_vector,
                limit=limit,
                score_threshold=score_threshold,
            )
            hits = result.points
        except (DatabaseError, Exception):
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
                should=[
                    models.FieldCondition(
                        key="source_category",
                        match=models.MatchValue(value=source_category),
                    ),
                    models.FieldCondition(
                        key="doc_type",
                        match=models.MatchValue(value=source_category),
                    ),
                ]
            )

        try:
            query_vector = await self._embeddings.embed_query(query)
            result = await self._client.query_points(
                collection_name=col,
                query=query_vector,
                query_filter=keyword_filter,
                limit=limit,
            )
            hits = result.points
        except (DatabaseError, Exception):
            logger.exception("Hybrid search failed in '%s'", col)
            raise

        return [_hit_to_dict(hit) for hit in hits]

    # ── count by category ────────────────────────────────────────────────

    async def count_by_source_category(
        self,
        source_category: str,
        collection: str | None = None,
    ) -> int:
        """Count points whose source_category (or doc_type) payload matches."""
        col = collection or self._default_collection
        total = 0
        offset: models.PointId | None = None
        scroll_filter = models.Filter(
            should=[
                models.FieldCondition(
                    key="source_category",
                    match=models.MatchValue(value=source_category),
                ),
                models.FieldCondition(
                    key="doc_type",
                    match=models.MatchValue(value=source_category),
                ),
            ]
        )
        try:
            while True:
                points, offset = await self._client.scroll(
                    collection_name=col,
                    scroll_filter=scroll_filter,
                    limit=500,
                    with_payload=False,
                    with_vectors=False,
                    offset=offset,
                )
                total += len(points)
                if offset is None or not points:
                    break
        except Exception:
            logger.exception("count_by_source_category failed for %s", source_category)
            raise
        return total

    # ── deletion ─────────────────────────────────────────────────────────

    async def delete_by_source(
        self,
        source: str,
        collection: str | None = None,
    ) -> None:
        """Delete all points whose ``source`` payload matches *source*."""
        col = collection or self._default_collection
        try:
            await self._client.delete(
                collection_name=col,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source",
                                match=models.MatchValue(value=source),
                            )
                        ]
                    )
                ),
            )
            logger.info("Deleted points with source='%s' from '%s'", source, col)
        except (DatabaseError, Exception):
            logger.exception("Failed to delete points for source '%s'", source)
            raise

    # ── payload updates ─────────────────────────────────────────────────

    async def set_payload(
        self,
        point_id: str,
        payload: dict[str, Any],
        collection: str | None = None,
    ) -> None:
        """Update payload fields on an existing point without re-embedding."""
        col = collection or self._default_collection
        try:
            await self._client.set_payload(
                collection_name=col,
                payload=payload,
                points=[point_id],
            )
        except (DatabaseError, Exception):
            logger.warning("set_payload failed for point %s", point_id, exc_info=True)
            raise

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
    """Normalise a Qdrant hit into ira-v3's canonical result schema.

    Handles both the old ira payload layout (``text``, ``doc_type``,
    ``filename``, ``machines``, ``prices``, …) and the new ira-v3 layout
    (``content``, ``source_category``, ``metadata``).
    """
    payload = hit.payload or {}

    content = payload.get("content") or payload.get("text") or payload.get("raw_text", "")
    source = payload.get("source") or payload.get("filename", "")
    source_category = payload.get("source_category") or payload.get("doc_type", "")

    metadata = payload.get("metadata", {})
    if not metadata:
        extra_keys = {
            "machines", "prices", "customer", "chunk", "total_chunks",
            "source_group", "doc_type", "filename", "ingested_at",
            "subject", "from_email", "to_email", "direction",
            "thread_key", "company_domain", "has_quote", "has_price",
        }
        metadata = {k: v for k, v in payload.items() if k in extra_keys and v}

    return {
        "id": str(hit.id),
        "content": content,
        "score": hit.score,
        "source": source,
        "metadata": metadata,
        "source_category": source_category,
    }
