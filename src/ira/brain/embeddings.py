"""Primary embedding service for all vector operations in Ira.

Every component that needs to convert text into dense vectors — the Qdrant
manager, the retriever, the document ingestor, sales intelligence — goes
through :class:`EmbeddingService`.  It wraps the Voyage AI embeddings API,
handles batching, retries, and an in-memory cache so that repeated texts
(e.g. the same query issued by multiple agents in one request) are never
re-embedded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import Sequence

import httpx

from ira.config import EmbeddingConfig, get_settings

logger = logging.getLogger(__name__)

_VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
_MAX_BATCH_SIZE = 128
_DEFAULT_CACHE_SIZE = 4096

_MAX_RETRIES = 5
_INITIAL_BACKOFF_S = 0.5
_BACKOFF_MULTIPLIER = 2


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class EmbeddingService:
    """Async wrapper around the Voyage AI embeddings endpoint."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        *,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        cfg = config or get_settings().embedding
        self._api_key = cfg.api_key.get_secret_value()
        self._model = cfg.model
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    # ── public API ───────────────────────────────────────────────────────

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        """Embed a list of texts, returning one vector per input.

        Texts already in the cache are served from memory.  The remainder
        are sent to Voyage AI in batches of up to ``_MAX_BATCH_SIZE``.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []

        for i, text in enumerate(texts):
            cached = self._cache_get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)

        if uncached_indices:
            uncached_texts = [texts[i] for i in uncached_indices]
            vectors = await self._embed_batched(uncached_texts, input_type=input_type)
            for idx, vec in zip(uncached_indices, vectors):
                results[idx] = vec
                self._cache_put(texts[idx], vec)

        return results  # type: ignore[return-value]

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string for retrieval."""
        cached = self._cache_get(query)
        if cached is not None:
            return cached

        vectors = await self._call_api([query], input_type="query")
        self._cache_put(query, vectors[0])
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
