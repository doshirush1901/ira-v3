"""Qdrant vector-database manager for Ira's knowledge base.

Provides collection lifecycle management, batched upserts of
:class:`~ira.data.models.KnowledgeItem` objects, dense vector search,
and hybrid (dense + keyword filter) retrieval.  All operations are async
and go through :class:`~ira.brain.embeddings.EmbeddingService` for
embedding generation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Sequence
from uuid import UUID

import httpx
from qdrant_client import AsyncQdrantClient, models

from ira.brain.embeddings import EmbeddingService
from ira.services.resilience import RetryPolicy, run_with_retry
from ira.config import QdrantConfig, get_settings
from ira.data.models import KnowledgeItem
from ira.exceptions import DatabaseError, IraError, LLMError

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 100
# Smaller batches for Qdrant Cloud to avoid request/payload size limits (e.g. 32MB).
_CLOUD_UPSERT_BATCH_SIZE = 50
# Max concurrent search requests to Qdrant.  Qdrant Cloud resets connections
# when too many arrive simultaneously (ResponseHandlingException); a semaphore
# of 4 keeps throughput high while avoiding connection drops.
_MAX_CONCURRENT_SEARCHES = 4

# Payload fields returned by search/hybrid_search.  Fetching only these avoids
# transferring large raw payloads over the network — critical for Qdrant Cloud
# where full-payload responses can be 10-30x slower than selective ones.
_SEARCH_PAYLOAD_FIELDS: list[str] = [
    "content", "text", "raw_text",
    "source", "filename",
    "source_category", "doc_type",
    "metadata",
    "machines", "prices", "customer",
    "chunk", "total_chunks",
    "source_group", "ingested_at",
    "subject", "from_email", "to_email", "direction",
    "thread_key", "company_domain", "has_quote", "has_price",
]


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
        self._client = AsyncQdrantClient(
            url=cfg.url,
            api_key=api_key,
            check_compatibility=False,
            timeout=cfg.timeout,
        )
        self._embeddings = embedding_service
        app = get_settings().app
        self._use_sparse_hybrid = getattr(app, "use_sparse_hybrid", False)
        self._default_collection = (
            cfg.collection_hybrid if self._use_sparse_hybrid else cfg.collection
        )
        self._event_bus = event_bus
        self._search_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SEARCHES)
        # Optional second client for sync: when cloud_url is set, every upsert
        # and ensure_collection is mirrored so local and cloud stay in sync.
        self._client_cloud: AsyncQdrantClient | None = None
        if cfg.cloud_url and cfg.cloud_url.strip():
            cloud_key = cfg.cloud_api_key.get_secret_value() or None
            try:
                self._client_cloud = AsyncQdrantClient(
                    url=cfg.cloud_url.strip(),
                    api_key=cloud_key,
                    check_compatibility=False,
                    timeout=cfg.timeout,
                )
                logger.info("Qdrant sync enabled: writes will mirror to %s", cfg.cloud_url[:50])
            except Exception:
                logger.warning("Qdrant cloud client init failed — sync disabled", exc_info=True)

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    # ── collection lifecycle ─────────────────────────────────────────────

    _PAYLOAD_INDEXES: list[tuple[str, str]] = [
        ("source_category", "keyword"),
        ("doc_type", "keyword"),
        ("source", "keyword"),
        ("source_group", "keyword"),
        ("filename", "keyword"),
        ("from_email", "keyword"),
        ("to_email", "keyword"),
        ("direction", "keyword"),
        ("company_domain", "keyword"),
        ("thread_key", "keyword"),
    ]

    async def ensure_collection(
        self,
        name: str | None = None,
        vector_size: int = 1024,
    ) -> None:
        """Create the collection if it does not already exist.

        Defaults to cosine distance, which matches the normalised Voyage
        embeddings.  Also ensures payload indexes exist for commonly
        filtered fields (required by Qdrant Cloud).
        """
        collection = name or self._default_collection
        try:
            if await self._client.collection_exists(collection):
                logger.debug("Collection '%s' already exists", collection)
            else:
                if self._use_sparse_hybrid:
                    await self._client.create_collection(
                        collection_name=collection,
                        vectors_config={
                            "dense": models.VectorParams(
                                size=vector_size,
                                distance=models.Distance.COSINE,
                            ),
                        },
                        sparse_vectors_config={
                            "sparse": models.SparseVectorParams(),
                        },
                    )
                    logger.info(
                        "Created Qdrant collection '%s' (dense+sparse hybrid)",
                        collection,
                    )
                else:
                    await self._client.create_collection(
                        collection_name=collection,
                        vectors_config=models.VectorParams(
                            size=vector_size,
                            distance=models.Distance.COSINE,
                        ),
                    )
                    logger.info("Created Qdrant collection '%s' (dim=%d)", collection, vector_size)
            await self._ensure_payload_indexes(self._client, collection)
            # Mirror to cloud if sync is enabled
            if self._client_cloud is not None:
                if await self._client_cloud.collection_exists(collection):
                    logger.debug("Cloud collection '%s' already exists", collection)
                else:
                    if self._use_sparse_hybrid:
                        await self._client_cloud.create_collection(
                            collection_name=collection,
                            vectors_config={
                                "dense": models.VectorParams(
                                    size=vector_size,
                                    distance=models.Distance.COSINE,
                                ),
                            },
                            sparse_vectors_config={
                                "sparse": models.SparseVectorParams(),
                            },
                        )
                    else:
                        await self._client_cloud.create_collection(
                            collection_name=collection,
                            vectors_config=models.VectorParams(
                                size=vector_size,
                                distance=models.Distance.COSINE,
                            ),
                        )
                    logger.info("Created Qdrant cloud collection '%s'", collection)
                await self._ensure_payload_indexes(self._client_cloud, collection)
        except (DatabaseError, Exception):
            logger.exception("Failed to ensure collection '%s'", collection)
            raise

    async def _ensure_payload_indexes(
        self,
        client: AsyncQdrantClient,
        collection: str,
    ) -> None:
        """Create payload indexes if they don't already exist.

        Required for Qdrant Cloud where filtered queries fail without
        explicit indexes.  Errors are logged but not raised so that
        startup is not blocked by index creation on large collections.
        """
        try:
            info = await client.get_collection(collection)
            existing = set((info.payload_schema or {}).keys())
        except Exception:
            existing = set()

        for field, schema_type in self._PAYLOAD_INDEXES:
            if field in existing:
                continue
            try:
                schema = (
                    models.PayloadSchemaType.KEYWORD
                    if schema_type == "keyword"
                    else models.PayloadSchemaType.BOOL
                )
                await client.create_payload_index(
                    collection_name=collection,
                    field_name=field,
                    field_schema=schema,
                )
                logger.info("Created payload index '%s' (%s) on '%s'", field, schema_type, collection)
            except Exception:
                logger.debug(
                    "Payload index '%s' on '%s' not created (may already exist or cluster busy)",
                    field, collection, exc_info=True,
                )

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

        if self._use_sparse_hybrid:
            from ira.brain.sparse_vectors import text_to_sparse
            points = []
            for item, vector in zip(items, vectors):
                indices, values = text_to_sparse(item.content)
                points.append(
                    models.PointStruct(
                        id=_uuid_to_hex(item.id),
                        vector={
                            "dense": vector,
                            "sparse": models.SparseVector(
                                indices=indices,
                                values=values,
                            ),
                        },
                        payload={
                            "content": item.content,
                            "source": item.source,
                            "source_category": item.source_category,
                            "metadata": item.metadata,
                            "created_at": item.created_at.isoformat(),
                        },
                    )
                )
        else:
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
        # Mirror to cloud if sync is enabled (same points, same collection); use smaller batches for Cloud limits
        if self._client_cloud is not None:
            for start in range(0, len(points), _UPSERT_BATCH_SIZE):
                batch = points[start : start + _UPSERT_BATCH_SIZE]
                for cloud_start in range(0, len(batch), _CLOUD_UPSERT_BATCH_SIZE):
                    cloud_batch = batch[cloud_start : cloud_start + _CLOUD_UPSERT_BATCH_SIZE]
                    try:
                        await self._client_cloud.upsert(collection_name=col, points=cloud_batch)
                    except (DatabaseError, Exception):
                        try:
                            import asyncio
                            await asyncio.sleep(0.5)
                            await self._client_cloud.upsert(collection_name=col, points=cloud_batch)
                        except (DatabaseError, Exception):
                            logger.warning(
                                "Qdrant cloud sync upsert failed at offset %d (batch size %d) — primary succeeded",
                                start + cloud_start,
                                len(cloud_batch),
                                exc_info=True,
                            )

        logger.info("Upserted %d items into '%s'%s", upserted, col, " (synced to cloud)" if self._client_cloud else "")

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

    # ── retrieve by id (for graph–vector stitch) ─────────────────────────

    async def get_points(
        self,
        point_ids: Sequence[str],
        collection: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve points by ID; returns list of payload dicts (id, content, source, metadata)."""
        if not point_ids:
            return []
        col = collection or self._default_collection
        try:
            points = await self._client.retrieve(
                collection_name=col,
                ids=list(point_ids),
                with_payload=_SEARCH_PAYLOAD_FIELDS,
                with_vectors=False,
            )
        except (DatabaseError, Exception):
            logger.exception("get_points failed for %d ids", len(point_ids))
            raise
        return [_record_to_dict(p) for p in points if getattr(p, "payload", None)]

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

        async with self._search_semaphore:
            try:
                query_vector = await self._embeddings.embed_query(query)
                if self._use_sparse_hybrid:
                    result = await self._client.query_points(
                        collection_name=col,
                        query=query_vector,
                        using="dense",
                        limit=limit,
                        score_threshold=score_threshold,
                        with_payload=_SEARCH_PAYLOAD_FIELDS,
                    )
                else:
                    result = await self._client.query_points(
                        collection_name=col,
                        query=query_vector,
                        limit=limit,
                        score_threshold=score_threshold,
                        with_payload=_SEARCH_PAYLOAD_FIELDS,
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

        async with self._search_semaphore:
            try:
                query_vector = await self._embeddings.embed_query(query)
                if self._use_sparse_hybrid:
                    from ira.brain.sparse_vectors import text_to_sparse
                    si, sv = text_to_sparse(query)
                    result = await self._client.query_points(
                        collection_name=col,
                        prefetch=[
                            models.Prefetch(
                                query=models.SparseVector(indices=si, values=sv),
                                using="sparse",
                                limit=limit * 2,
                            ),
                            models.Prefetch(
                                query=query_vector,
                                using="dense",
                                limit=limit * 2,
                            ),
                        ],
                        query=models.FusionQuery(fusion=models.Fusion.RRF),
                        query_filter=keyword_filter,
                        limit=limit,
                        with_payload=_SEARCH_PAYLOAD_FIELDS,
                    )
                else:
                    result = await self._client.query_points(
                        collection_name=col,
                        query=query_vector,
                        query_filter=keyword_filter,
                        limit=limit,
                        with_payload=_SEARCH_PAYLOAD_FIELDS,
                    )
                hits = result.points
            except Exception as e:
                _err_str = str(e)
                if keyword_filter is not None and (
                    "Index required" in _err_str
                    or "400" in _err_str
                    or "Bad request" in _err_str.lower()
                ):
                    logger.warning(
                        "Hybrid search filter failed in '%s' (missing index?) — "
                        "retrying without filter: %s",
                        col, type(e).__name__,
                    )
                    try:
                        if self._use_sparse_hybrid:
                            result = await self._client.query_points(
                                collection_name=col,
                                prefetch=[
                                    models.Prefetch(
                                        query=models.SparseVector(indices=si, values=sv),
                                        using="sparse",
                                        limit=limit * 2,
                                    ),
                                    models.Prefetch(
                                        query=query_vector,
                                        using="dense",
                                        limit=limit * 2,
                                    ),
                                ],
                                query=models.FusionQuery(fusion=models.Fusion.RRF),
                                query_filter=None,
                                limit=limit,
                                with_payload=_SEARCH_PAYLOAD_FIELDS,
                            )
                        else:
                            result = await self._client.query_points(
                                collection_name=col,
                                query=query_vector,
                                query_filter=None,
                                limit=limit,
                                with_payload=_SEARCH_PAYLOAD_FIELDS,
                            )
                        hits = result.points
                    except Exception as e2:
                        logger.warning(
                            "Hybrid search fallback also failed in '%s': %s",
                            col, e2,
                        )
                        return []
                else:
                    logger.warning(
                        "Hybrid search failed in '%s' (%s: %s) — returning no results",
                        col, type(e).__name__, e,
                    )
                    return []

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
        except Exception as exc:
            if "Index required" in str(exc) or "400" in str(exc):
                logger.warning(
                    "count_by_source_category: payload index missing for '%s' — returning 0",
                    source_category,
                )
                return 0
            logger.exception("count_by_source_category failed for %s", source_category)
            raise
        return total

    async def scroll_by_source_category(
        self,
        source_category: str,
        collection: str | None = None,
        *,
        limit: int = 10_000,
        batch_size: int = 500,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Scroll all points whose source_category or doc_type matches; return (point_id, payload) list."""
        col = collection or self._default_collection
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
        out: list[tuple[str, dict[str, Any]]] = []
        offset: models.PointId | None = None
        try:
            while len(out) < limit:
                points, offset = await self._client.scroll(
                    collection_name=col,
                    scroll_filter=scroll_filter,
                    limit=min(batch_size, limit - len(out)),
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                )
                for pt in points:
                    out.append((str(pt.id), (pt.payload or {})))
                if offset is None or not points:
                    break
        except Exception:
            logger.exception("scroll_by_source_category failed for %s", source_category)
            raise
        return out

    async def sync_collection_to_cloud(
        self,
        collection: str | None = None,
        *,
        batch_size: int = 100,
        max_points: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Copy all points from local Qdrant to cloud (requires QDRANT_CLOUD_URL set).

        Scrolls the local collection with vectors and payload, upserts each batch
        to the cloud client. Use for one-time migration. Returns total points synced.
        """
        if self._client_cloud is None:
            raise IraError(
                "Qdrant cloud not configured. Set QDRANT_CLOUD_URL and QDRANT_CLOUD_API_KEY in .env"
            )
        col = collection or self._default_collection
        await self.ensure_collection(name=col)
        total = 0
        offset: models.PointId | None = None
        try:
            while True:
                points, offset = await self._client.scroll(
                    collection_name=col,
                    limit=batch_size,
                    with_payload=True,
                    with_vectors=True,
                    offset=offset,
                )
                if not points:
                    break
                # Rebuild PointStruct for cloud upsert (id, vector, payload)
                batch = []
                for pt in points:
                    vec = pt.vector
                    if isinstance(vec, dict):
                        vec = vec.get("") or (list(vec.values())[0] if vec else None)
                    if vec is None:
                        continue
                    batch.append(
                        models.PointStruct(
                            id=pt.id,
                            vector=vec,
                            payload=pt.payload or {},
                        )
                    )
                # Upsert to cloud in smaller chunks to stay under request size limits
                for sub_start in range(0, len(batch), _CLOUD_UPSERT_BATCH_SIZE):
                    sub = batch[sub_start : sub_start + _CLOUD_UPSERT_BATCH_SIZE]
                    await self._client_cloud.upsert(collection_name=col, points=sub)
                total += len(batch)
                logger.info("Synced %d points to cloud (total so far: %d)", len(batch), total)
                if progress_callback is not None:
                    progress_callback(len(batch), total)
                if max_points is not None and total >= max_points:
                    break
                if offset is None:
                    break
        except Exception:
            logger.exception("sync_collection_to_cloud failed")
            raise
        return total

    async def scroll_collection_payloads(
        self,
        collection: str | None = None,
        *,
        batch_size: int = 200,
        max_points: int | None = None,
        source_category: str | None = None,
        start_after_point_id: str | None = None,
    ):
        """Async generator: scroll collection and yield batches of payload dicts.

        Does not load vectors. Optional filter by source_category (or doc_type).
        Each item includes "point_id", "content", "source", "source_category", "payload".
        If start_after_point_id is set, scrolling starts after that point (for resume).
        """
        col = collection or self._default_collection
        scroll_filter: models.Filter | None = None
        if source_category:
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
        def _is_retryable_scroll_error(exc: Exception) -> bool:
            if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
                return True
            cause = getattr(exc, "__cause__", None)
            if cause is not None and isinstance(
                cause, (httpx.ConnectError, httpx.TimeoutException)
            ):
                return True
            if type(exc).__name__ == "ResponseHandlingException" and cause is not None:
                return isinstance(cause, (httpx.ConnectError, httpx.TimeoutException))
            return False

        scroll_retry = RetryPolicy(max_attempts=5, base_delay_seconds=2.0)
        total_yielded = 0
        offset: models.PointId | None = (
            start_after_point_id if start_after_point_id else None
        )
        try:
            while True:
                async def _do_scroll() -> tuple[Any, Any]:
                    return await self._client.scroll(
                        collection_name=col,
                        limit=batch_size,
                        with_payload=True,
                        with_vectors=False,
                        offset=offset,
                        scroll_filter=scroll_filter,
                    )

                points, offset = await run_with_retry(
                    _do_scroll,
                    policy=scroll_retry,
                    is_retryable=_is_retryable_scroll_error,
                )
                batch: list[dict[str, Any]] = []
                for pt in points:
                    payload = pt.payload or {}
                    content = payload.get("content") or payload.get("text") or ""
                    if not content or not isinstance(content, str):
                        continue
                    batch.append({
                        "point_id": str(pt.id),
                        "content": content,
                        "source": payload.get("source", ""),
                        "source_category": payload.get("source_category") or payload.get("doc_type", ""),
                        "payload": payload,
                    })
                if batch:
                    yield batch
                    total_yielded += len(batch)
                    if max_points is not None and total_yielded >= max_points:
                        break
                if offset is None or not points:
                    break
        except Exception:
            logger.exception("scroll_collection_payloads failed")
            raise

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

    async def delete_by_source_category(
        self,
        source_category: str,
        collection: str | None = None,
    ) -> None:
        """Delete all points whose source_category (or doc_type) payload matches *source_category*."""
        col = collection or self._default_collection
        try:
            await self._client.delete(
                collection_name=col,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
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
                ),
            )
            logger.info(
                "Deleted points with source_category/doc_type='%s' from '%s'",
                source_category, col,
            )
        except (DatabaseError, Exception):
            logger.exception(
                "Failed to delete points for source_category '%s'",
                source_category,
            )
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
        if self._client_cloud is not None:
            await self._client_cloud.close()

    async def __aenter__(self) -> QdrantManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


# ── helpers ──────────────────────────────────────────────────────────────────


def _uuid_to_hex(uid: UUID) -> str:
    """Qdrant accepts string or int point IDs; we use the UUID hex."""
    return uid.hex


def _record_to_dict(record: Any) -> dict[str, Any]:
    """Build canonical result dict from a retrieved point (id + payload, no score)."""
    payload = getattr(record, "payload", None) or {}
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
        "id": str(getattr(record, "id", "")),
        "content": content,
        "score": 1.0,
        "source": source,
        "metadata": metadata,
        "source_category": source_category,
    }


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
