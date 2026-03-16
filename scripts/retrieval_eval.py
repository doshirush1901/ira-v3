#!/usr/bin/env python3
"""Retrieval quality evaluation: run a set of queries and compute hit rate, MRR, P@k.

Expects data/brain/retrieval_eval_queries.json with entries:
  {"id": "...", "query": "...", "expected_in_content_or_source": ["snippet1", "snippet2"]}

A result is a hit if any of the expected strings appear (case-insensitive) in
the result's content or source. Writes a JSON report to data/brain/retrieval_eval_report.json.

Usage::
    poetry run python scripts/retrieval_eval.py
    poetry run python scripts/retrieval_eval.py --queries data/brain/retrieval_eval_queries.json --limit 10 --output data/brain/retrieval_eval_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.brain.retriever import UnifiedRetriever

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def _load_queries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


def _is_hit(result: dict, expected: list[str]) -> bool:
    content = (result.get("content") or "").lower()
    source = (result.get("source") or "").lower()
    text = content + " " + source
    return any(s.strip().lower() in text for s in expected if s)


def _first_rank_hit(results: list[dict], expected: list[str]) -> int | None:
    """Return 1-based rank of first result that is a hit, or None."""
    for rank, r in enumerate(results, 1):
        if _is_hit(r, expected):
            return rank
    return None


def _precision_at_k(results: list[dict], expected: list[str], k: int) -> float:
    top = results[:k]
    hits = sum(1 for r in top if _is_hit(r, expected))
    return hits / k if k else 0.0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval eval: hit rate, MRR, P@k")
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("data/brain/retrieval_eval_queries.json"),
        help="JSON file with query list",
    )
    parser.add_argument("--limit", type=int, default=10, help="Retrieval limit per query")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/brain/retrieval_eval_report.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Log per-query results")
    args = parser.parse_args()

    queries = _load_queries(args.queries)
    if not queries:
        print(f"No queries found at {args.queries}")
        sys.exit(1)

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph, mem0_client=None)

    try:
        await qdrant.ensure_collection()
    except Exception as e:
        logger.warning("Qdrant ensure_collection failed: %s", e)

    results_by_id: dict[str, list[dict]] = {}
    hit_at_1 = 0
    hit_at_5 = 0
    hit_at_10 = 0
    mrr_sum = 0.0
    p_at_5_sum = 0.0
    n = len(queries)

    for item in queries:
        qid = item.get("id", "unknown")
        query = item.get("query", "")
        expected = item.get("expected_in_content_or_source") or item.get("expected_keywords") or []
        if not query or not expected:
            continue

        try:
            results = await retriever.search(query, limit=args.limit)
        except Exception as e:
            logger.exception("Search failed for %s", qid)
            results = []

        results_by_id[qid] = [{"content": r.get("content", "")[:200], "source": r.get("source", "")} for r in results]

        first_rank = _first_rank_hit(results, expected)
        if first_rank is not None:
            if first_rank <= 1:
                hit_at_1 += 1
            if first_rank <= 5:
                hit_at_5 += 1
            hit_at_10 += 1
            mrr_sum += 1.0 / first_rank
        p_at_5_sum += _precision_at_k(results, expected, min(5, args.limit))

        if args.verbose:
            print(f"  {qid}: first_hit_rank={first_rank}, P@5={_precision_at_k(results, expected, 5):.2f}")

    await qdrant.close()
    await graph.close()

    report = {
        "n_queries": n,
        "hit_at_1": hit_at_1,
        "hit_at_5": hit_at_5,
        "hit_at_10": hit_at_10,
        "hit_at_1_rate": round(hit_at_1 / n, 4) if n else 0,
        "hit_at_5_rate": round(hit_at_5 / n, 4) if n else 0,
        "hit_at_10_rate": round(hit_at_10 / n, 4) if n else 0,
        "mrr": round(mrr_sum / n, 4) if n else 0,
        "precision_at_5_avg": round(p_at_5_sum / n, 4) if n else 0,
        "results_by_id": results_by_id,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("Retrieval Eval Report")
    print(f"  Queries:     {n}")
    print(f"  Hit@1:       {hit_at_1} ({report['hit_at_1_rate']:.2%})")
    print(f"  Hit@5:       {hit_at_5} ({report['hit_at_5_rate']:.2%})")
    print(f"  Hit@10:      {hit_at_10} ({report['hit_at_10_rate']:.2%})")
    print(f"  MRR:         {report['mrr']:.4f}")
    print(f"  P@5 (avg):   {report['precision_at_5_avg']:.4f}")
    print(f"  Report:      {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
