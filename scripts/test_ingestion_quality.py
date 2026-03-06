#!/usr/bin/env python3
"""A/B test: old migrated data vs new DigestiveSystem ingestion.

Compares chunk quality, waste filtering, and retrieval relevance for
8 representative files across different types and sizes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_KEY = os.getenv("QDRANT_API_KEY", "")
MAIN_COLLECTION = os.getenv("QDRANT_COLLECTION", "ira_knowledge_v3")
TEST_COLLECTION = "ira_knowledge_v3_test"

QDRANT_HEADERS = {"api-key": QDRANT_KEY, "Content-Type": "application/json"}

TEST_FILES = [
    {
        "path": "data/imports/01_Quotes_and_Proposals/MT2023090 PF1 810 V03 Machinecraft.pdf",
        "old_source": "MT2023090 PF1 810 V03 Machinecraft.pdf",
        "label": "Large quote PDF (16 MB)",
    },
    {
        "path": "data/imports/04_Machine_Manuals_and_Specs/PF1-X-3220 - Machinecraft.pdf",
        "old_source": "PF1-X-3220 - Machinecraft.pdf",
        "label": "Machine spec PDF (881 KB)",
    },
    {
        "path": "data/imports/08_Sales_and_CRM/European_Machine_Sales.xlsx",
        "old_source": "European_Machine_Sales_20250902.xlsx",
        "label": "Sales CRM spreadsheet",
    },
    {
        "path": "data/imports/02_Orders_and_POs/Machinecraft Machine Order Analysis.xlsx",
        "old_source": "Machinecraft Machine Order Analysis.xlsx",
        "label": "Order tracking spreadsheet",
    },
    {
        "path": "data/imports/01_Quotes_and_Proposals/EFX Edge Folding Offer for KTX.pdf",
        "old_source": "EFX Edge Folding Offer for KTX.pdf",
        "label": "Mid-size quote PDF (937 KB)",
    },
    {
        "path": "data/imports/06_Market_Research_and_Analysis/Value of ITF.pdf",
        "old_source": "Value of ITF (1).pdf",
        "label": "Market research PDF (913 KB)",
    },
    {
        "path": "data/imports/02_Orders_and_POs/PO 3584 10054AVF amended.docx",
        "old_source": "PO 3584 10054AVF  amended.docx",
        "label": "Purchase order DOCX",
    },
    {
        "path": "data/imports/docs_from_telegram/20260303_141951_photo_3124.extracted.txt",
        "old_source": "photo_3124.jpg",
        "label": "Telegram extracted text",
    },
]

RETRIEVAL_QUERIES = [
    "What is the price of PF1-X-3220?",
    "Which European customers have ordered machines?",
    "What are the specs of the edge folding machine?",
    "What is the value of the thermoforming industry?",
    "What purchase orders are pending?",
]


# ── Qdrant helpers ────────────────────────────────────────────────────────


def qdrant_get(path: str) -> dict:
    r = httpx.get(f"{QDRANT_URL}{path}", headers=QDRANT_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def qdrant_post(path: str, body: dict) -> dict:
    r = httpx.post(
        f"{QDRANT_URL}{path}",
        headers=QDRANT_HEADERS,
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def qdrant_put(path: str, body: dict) -> dict:
    r = httpx.put(
        f"{QDRANT_URL}{path}",
        headers=QDRANT_HEADERS,
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def qdrant_delete(path: str) -> dict:
    r = httpx.delete(f"{QDRANT_URL}{path}", headers=QDRANT_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ── Step 1: snapshot old data ─────────────────────────────────────────────


def fetch_old_chunks(source_name: str) -> list[dict]:
    """Scroll all points whose source matches *source_name*."""
    chunks: list[dict] = []
    offset = None
    for _ in range(50):
        body: dict = {"limit": 100, "with_payload": True, "with_vector": False}
        if offset:
            body["offset"] = offset
        data = qdrant_post(
            f"/collections/{MAIN_COLLECTION}/points/scroll", body
        )["result"]
        for pt in data["points"]:
            src = pt["payload"].get("source", "")
            if source_name.lower() in src.lower():
                chunks.append(pt["payload"])
        offset = data.get("next_page_offset")
        if not offset:
            break
    return chunks


# ── Step 2: run DigestiveSystem on a file ─────────────────────────────────


async def digest_file(file_path: str) -> dict:
    """Read a file and run it through the DigestiveSystem, returning the full result."""
    from ira.brain.document_ingestor import _READERS, _category_from_path
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.document_ingestor import DocumentIngestor
    from ira.systems.digestive import DigestiveSystem
    from ira.config import QdrantConfig

    p = Path(file_path)
    ext = p.suffix.lower()
    reader = _READERS.get(ext)
    if not reader:
        return {"error": f"No reader for {ext}"}

    raw_text = reader(p)
    if not raw_text.strip():
        return {"error": "Empty content"}

    category = _category_from_path(p, Path("data/imports"))

    test_config = QdrantConfig(
        url=QDRANT_URL,
        collection=TEST_COLLECTION,
    )

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding, config=test_config)
    await qdrant.ensure_collection(TEST_COLLECTION, vector_size=1024)
    graph = KnowledgeGraph()
    ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)
    digestive = DigestiveSystem(
        ingestor=ingestor,
        knowledge_graph=graph,
        embedding_service=embedding,
        qdrant=qdrant,
    )

    result = await digestive.ingest(
        raw_data=raw_text,
        source=file_path,
        source_category=category,
    )
    result["raw_text_len"] = len(raw_text)
    result["category"] = category
    await qdrant.close()
    return result


# ── Step 3: compare ──────────────────────────────────────────────────────


def print_separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def print_comparison(label: str, old_chunks: list[dict], new_result: dict) -> None:
    print_separator(label)

    old_count = len(old_chunks)
    new_count = new_result.get("chunks_created", 0)
    nutrients = new_result.get("nutrients_extracted", {})
    entities = new_result.get("entities_found", {})
    raw_len = new_result.get("raw_text_len", 0)
    elapsed = new_result.get("processing_time", 0)

    print(f"  Raw text length:   {raw_len:,} chars")
    print(f"  Category:          {new_result.get('category', '?')}")
    print(f"  Processing time:   {elapsed:.1f}s")
    print()
    print(f"  {'Metric':<25} {'Old (A)':<12} {'New (B)':<12}")
    print(f"  {'-' * 49}")
    print(f"  {'Chunks stored':<25} {old_count:<12} {new_count:<12}")
    print(f"  {'Protein items':<25} {'n/a':<12} {nutrients.get('protein', 0):<12}")
    print(f"  {'Carbs items':<25} {'n/a':<12} {nutrients.get('carbs', 0):<12}")
    print(f"  {'Waste discarded':<25} {'n/a':<12} {nutrients.get('waste', 0):<12}")
    print(f"  {'Companies found':<25} {'n/a':<12} {entities.get('companies', 0):<12}")
    print(f"  {'People found':<25} {'n/a':<12} {entities.get('people', 0):<12}")
    print(f"  {'Machines found':<25} {'n/a':<12} {entities.get('machines', 0):<12}")

    if old_chunks:
        print(f"\n  --- Sample OLD chunk (first 200 chars) ---")
        sample = old_chunks[0].get("content", "")[:200]
        print(textwrap.indent(textwrap.fill(sample, 68), "  "))

    if new_result.get("error"):
        print(f"\n  [ERROR] {new_result['error']}")


# ── Step 4: retrieval test ───────────────────────────────────────────────


async def search_collection(collection: str, query: str, limit: int = 3) -> list[dict]:
    from ira.brain.embeddings import EmbeddingService

    embedding = EmbeddingService()
    vec = await embedding.embed_query(query)

    body = {"query": vec, "limit": limit, "with_payload": True}
    try:
        r = httpx.post(
            f"{QDRANT_URL}/collections/{collection}/points/query",
            headers=QDRANT_HEADERS,
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        return [
            {
                "score": pt["score"],
                "content": pt["payload"].get("content", "")[:150],
                "source": pt["payload"].get("source", ""),
            }
            for pt in r.json()["result"]["points"]
        ]
    except Exception as e:
        return [{"error": str(e)}]


def print_retrieval_comparison(
    query: str, old_results: list[dict], new_results: list[dict]
) -> None:
    print(f"\n  Query: \"{query}\"")
    print(f"  {'─' * 60}")

    print(f"  OLD (A) top result:")
    if old_results and "error" not in old_results[0]:
        r = old_results[0]
        print(f"    score={r['score']:.3f}  source={r['source']}")
        print(f"    {r['content'][:120]}...")
    else:
        print(f"    (no results)")

    print(f"  NEW (B) top result:")
    if new_results and "error" not in new_results[0]:
        r = new_results[0]
        print(f"    score={r['score']:.3f}  source={r['source']}")
        print(f"    {r['content'][:120]}...")
    else:
        print(f"    (no results)")


# ── Main ─────────────────────────────────────────────────────────────────


async def main() -> None:
    print_separator("INGESTION QUALITY A/B TEST")
    print(f"  Main collection:  {MAIN_COLLECTION}")
    print(f"  Test collection:  {TEST_COLLECTION}")
    print(f"  Test files:       {len(TEST_FILES)}")
    print(f"  Retrieval queries: {len(RETRIEVAL_QUERIES)}")

    # ── Step 1 + 2 + 3: per-file comparison ──
    for tf in TEST_FILES:
        label = tf["label"]
        file_path = str(PROJECT_ROOT / tf["path"])

        print(f"\n  Fetching old chunks for: {tf['old_source']}...")
        old_chunks = fetch_old_chunks(tf["old_source"])

        print(f"  Digesting through new pipeline: {Path(file_path).name}...")
        new_result = await digest_file(file_path)

        print_comparison(label, old_chunks, new_result)

    # ── Fetch new chunks from test collection ──
    test_info = qdrant_get(f"/collections/{TEST_COLLECTION}")
    test_points = test_info["result"]["points_count"]
    print_separator(f"TEST COLLECTION: {test_points} points ingested")

    # ── Step 4: retrieval comparison ──
    print_separator("RETRIEVAL QUALITY COMPARISON")
    for query in RETRIEVAL_QUERIES:
        old_results = await search_collection(MAIN_COLLECTION, query)
        new_results = await search_collection(TEST_COLLECTION, query)
        print_retrieval_comparison(query, old_results, new_results)

    # ── Cleanup ──
    print_separator("CLEANUP")
    print(f"  Deleting test collection: {TEST_COLLECTION}")
    try:
        qdrant_delete(f"/collections/{TEST_COLLECTION}")
        print(f"  Done.")
    except Exception as e:
        print(f"  Warning: {e}")

    print_separator("A/B TEST COMPLETE")


if __name__ == "__main__":
    asyncio.run(main())
