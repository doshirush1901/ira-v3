"""BM25 keyword search with Reciprocal Rank Fusion.

Provides a pure-Python Okapi BM25 index that can be built from document
collections, persisted to disk as JSON, and fused with dense vector results
using RRF.  A query-dependent alpha function adjusts the BM25-vs-dense
weight based on whether the query looks like a keyword lookup (model
numbers, specs) or a conceptual question.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_K1 = 1.5
_B = 0.75


class BM25Index:
    """In-memory Okapi BM25 index over a document collection."""

    def __init__(self) -> None:
        self._doc_count: int = 0
        self._avg_dl: float = 0.0
        self._doc_lengths: dict[str, int] = {}
        self._tf: dict[str, dict[str, int]] = {}
        self._df: dict[str, int] = defaultdict(int)
        self._documents: dict[str, dict] = {}

    def build_from_documents(self, documents: list[dict]) -> None:
        """Build the inverted index with term frequencies.

        Each document dict must have at least ``id`` and ``content`` keys.
        Optional ``metadata`` is preserved for result output.
        """
        self._doc_count = len(documents)
        total_length = 0

        for doc in documents:
            doc_id = str(doc.get("id", ""))
            content = doc.get("content", "")
            tokens = _tokenize(content)

            self._doc_lengths[doc_id] = len(tokens)
            total_length += len(tokens)
            self._documents[doc_id] = doc

            term_freq: dict[str, int] = defaultdict(int)
            for token in tokens:
                term_freq[token] += 1
            self._tf[doc_id] = dict(term_freq)

            for term in term_freq:
                self._df[term] += 1

        self._avg_dl = total_length / self._doc_count if self._doc_count else 0.0
        logger.info("BM25 index built: %d documents, avg_dl=%.1f", self._doc_count, self._avg_dl)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Score all documents against *query* using Okapi BM25."""
        query_tokens = _tokenize(query)
        if not query_tokens or not self._doc_count:
            return []

        scores: dict[str, float] = {}
        for doc_id in self._tf:
            score = 0.0
            dl = self._doc_lengths.get(doc_id, 0)
            tf_map = self._tf[doc_id]

            for term in query_tokens:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                df = self._df.get(term, 0)
                idf = math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1.0)
                numerator = tf * (_K1 + 1)
                denominator = tf + _K1 * (1 - _B + _B * dl / self._avg_dl)
                score += idf * numerator / denominator

            if score > 0:
                scores[doc_id] = score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        results: list[dict] = []
        for doc_id, score in ranked:
            doc = self._documents.get(doc_id, {})
            results.append({
                "id": doc_id,
                "content": doc.get("content", ""),
                "score": score,
                "source": doc.get("source", ""),
                "metadata": doc.get("metadata", {}),
            })
        return results

    def save(self, path: Path) -> None:
        """Persist the index to disk as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "doc_count": self._doc_count,
            "avg_dl": self._avg_dl,
            "doc_lengths": self._doc_lengths,
            "tf": self._tf,
            "df": dict(self._df),
            "documents": self._documents,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        logger.info("BM25 index saved to %s (%d docs)", path, self._doc_count)

    def load(self, path: Path) -> None:
        """Load a previously saved index from disk."""
        if not path.exists():
            logger.warning("BM25 index file not found: %s", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._doc_count = data["doc_count"]
            self._avg_dl = data["avg_dl"]
            self._doc_lengths = data["doc_lengths"]
            self._tf = data["tf"]
            self._df = defaultdict(int, data["df"])
            self._documents = data["documents"]
            logger.info("BM25 index loaded from %s (%d docs)", path, self._doc_count)
        except (json.JSONDecodeError, KeyError, OSError):
            logger.exception("Failed to load BM25 index from %s", path)


# ── RRF fusion ───────────────────────────────────────────────────────────────


def hybrid_search_rrf(
    dense_results: list[dict],
    bm25_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Merge dense and BM25 results using Reciprocal Rank Fusion.

    Each result is identified by its ``content`` field (first 200 chars).
    The fused score is ``1 / (k + rank)`` summed across both lists.
    """
    scores: dict[str, float] = defaultdict(float)
    result_map: dict[str, dict] = {}

    for rank, item in enumerate(dense_results, start=1):
        key = _result_key(item)
        scores[key] += 1.0 / (k + rank)
        if key not in result_map:
            result_map[key] = item

    for rank, item in enumerate(bm25_results, start=1):
        key = _result_key(item)
        scores[key] += 1.0 / (k + rank)
        if key not in result_map:
            result_map[key] = item

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    merged: list[dict] = []
    for key, rrf_score in ranked:
        item = result_map[key].copy()
        item["rrf_score"] = rrf_score
        merged.append(item)

    return merged


# ── query-dependent alpha ────────────────────────────────────────────────────

_KEYWORD_HEAVY_PATTERN = re.compile(
    r"(PF1|AM-|IMG-|FCS-|UNO-|DUO-|\d{4,}|[A-Z]{2,}-\d+|spec|model\s*#|part\s*number)",
    re.IGNORECASE,
)

_CONCEPTUAL_PATTERN = re.compile(
    r"(how\s+(does|do|can|to)|what\s+(is|are|does)|why\s+(does|do|is)|explain|describe|difference\s+between)",
    re.IGNORECASE,
)


def query_dependent_alpha(query: str) -> float:
    """Return alpha weight for BM25 vs dense search.

    Higher alpha = more BM25 weight (keyword-oriented).
    Lower alpha = more dense/semantic weight.
    """
    has_keywords = bool(_KEYWORD_HEAVY_PATTERN.search(query))
    is_conceptual = bool(_CONCEPTUAL_PATTERN.search(query))

    if has_keywords and not is_conceptual:
        return 0.6
    if is_conceptual and not has_keywords:
        return 0.3
    return 0.5


# ── helpers ──────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization with basic punctuation stripping."""
    return re.findall(r"\b\w{2,}\b", text.lower())


def _result_key(item: dict) -> str:
    """Stable key for deduplication across result lists."""
    content = item.get("content", "")
    return content[:200]
