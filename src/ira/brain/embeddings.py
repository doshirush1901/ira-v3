"""Primary embedding service for all vector operations in Ira.

Every component that needs to convert text into dense vectors — the Qdrant
manager, the retriever, the document ingestor, sales intelligence — goes
through :class:`EmbeddingService`.  It wraps the Voyage AI embeddings API,
handles batching, retries, and a two-tier cache (in-memory L1 + SQLite L2)
so that repeated texts are never re-embedded across restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Sequence

import httpx

from ira.config import EmbeddingConfig, get_settings

logger = logging.getLogger(__name__)

_VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
_MAX_BATCH_SIZE = 128
_DEFAULT_CACHE_SIZE = 4096
_DEFAULT_CACHE_PATH = "data/brain/embedding_cache.db"

_MAX_RETRIES = 5
_INITIAL_BACKOFF_S = 0.5
_BACKOFF_MULTIPLIER = 2


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _init_sqlite_cache(path: str) -> None:
    """Create cache directory and table if they do not exist."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                text_hash TEXT PRIMARY KEY,
                embedding BLOB,
                created_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _sqlite_get_sync(path: str, text_hash: str) -> list[float] | None:
    """Synchronous SQLite cache lookup."""
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT embedding FROM embedding_cache WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            if row is None:
                return None
            blob = row[0]
            return json.loads(blob.decode("utf-8") if isinstance(blob, bytes) else blob)
        finally:
            conn.close()
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.warning("SQLite cache read failed for %s: %s", text_hash[:16], e)
        return None


def _sqlite_put_sync(path: str, text_hash: str, embedding: list[float]) -> None:
    """Synchronous SQLite cache write."""
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO embedding_cache (text_hash, embedding, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    text_hash,
                    json.dumps(embedding).encode("utf-8"),
                    datetime.now(tz=None).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("SQLite cache write failed for %s: %s", text_hash[:16], e)


class EmbeddingService:
    """Async wrapper around the Voyage AI embeddings endpoint."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        *,
        cache_size: int = _DEFAULT_CACHE_SIZE,
        cache_path: str = _DEFAULT_CACHE_PATH,
    ) -> None:
        cfg = config or get_settings().embedding
        self._api_key = cfg.api_key.get_secret_value()
        self._model = cfg.model
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self._cache_path = cache_path
        _init_sqlite_cache(cache_path)

    # ── public API ───────────────────────────────────────────────────────

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        """Embed a list of texts, returning one vector per input.

        L1 (in-memory) is checked first, then L2 (SQLite). Uncached texts
        are sent to Voyage AI in batches of up to ``_MAX_BATCH_SIZE``.
        New embeddings are stored in both caches.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        l1_miss_indices: list[int] = []

        for i, text in enumerate(texts):
            cached = self._cache_get(text)
            if cached is not None:
                results[i] = cached
            else:
                l1_miss_indices.append(i)

        if not l1_miss_indices:
            return results  # type: ignore[return-value]

        # L2 (SQLite) lookup for L1 misses (parallel)
        l2_results = await asyncio.gather(
            *[
                asyncio.to_thread(
                    _sqlite_get_sync, self._cache_path, _text_hash(texts[idx])
                )
                for idx in l1_miss_indices
            ]
        )
        l2_miss_indices: list[int] = []
        for idx, vec in zip(l1_miss_indices, l2_results):
            if vec is not None:
                results[idx] = vec
                self._cache_put(texts[idx], vec)
            else:
                l2_miss_indices.append(idx)

        if l2_miss_indices:
            uncached_texts = [texts[i] for i in l2_miss_indices]
            vectors = await self._embed_batched(uncached_texts, input_type=input_type)
            for idx, vec in zip(l2_miss_indices, vectors):
                results[idx] = vec
                text = texts[idx]
                self._cache_put(text, vec)
            await asyncio.gather(
                *[
                    asyncio.to_thread(
                        _sqlite_put_sync,
                        self._cache_path,
                        _text_hash(texts[idx]),
                        vec,
                    )
                    for idx, vec in zip(l2_miss_indices, vectors)
                ]
            )

        return results  # type: ignore[return-value]

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string for retrieval."""
        cached = self._cache_get(query)
        if cached is not None:
            return cached

        vec = await asyncio.to_thread(
            _sqlite_get_sync, self._cache_path, _text_hash(query)
        )
        if vec is not None:
            self._cache_put(query, vec)
            return vec

        vectors = await self._call_api([query], input_type="query")
        self._cache_put(query, vectors[0])
        await asyncio.to_thread(
            _sqlite_put_sync, self._cache_path, _text_hash(query), vectors[0]
        )
        return vectors[0]

    # ── batching ─────────────────────────────────────────────────────────

    async def _embed_batched(
        self,
        texts: Sequence[str],
        *,
        input_type: str,
    ) -> list[list[float]]:
        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[start : start + _MAX_BATCH_SIZE]
            vectors = await self._call_api(batch, input_type=input_type)
            all_vectors.extend(vectors)
        return all_vectors

    # ── HTTP with retry ──────────────────────────────────────────────────

    async def _call_api(
        self,
        texts: Sequence[str],
        *,
        input_type: str,
    ) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": list(texts),
            "model": self._model,
            "input_type": input_type,
        }

        backoff = _INITIAL_BACKOFF_S
        last_exc: Exception | None = None

        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    resp = await client.post(_VOYAGE_API_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    return [item["embedding"] for item in data["data"]]
                except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                    last_exc = exc
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                        raise
                    logger.warning(
                        "Voyage API attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt,
                        _MAX_RETRIES,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= _BACKOFF_MULTIPLIER

        raise RuntimeError(
            f"Voyage API failed after {_MAX_RETRIES} retries"
        ) from last_exc

    # ── LRU cache (dict-based) ───────────────────────────────────────────

    def _cache_get(self, text: str) -> list[float] | None:
        key = _text_hash(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, text: str, vector: list[float]) -> None:
        key = _text_hash(text)
        self._cache[key] = vector
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
