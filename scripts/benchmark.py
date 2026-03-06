#!/usr/bin/env python3
"""Automated accuracy benchmark across Machinecraft knowledge domains.

Runs hardcoded test cases through Pantheon.process() and scores responses
on keyword hit rate, forbidden-keyword avoidance, and agent routing accuracy.

Usage::

    python scripts/benchmark.py
    python scripts/benchmark.py --quick
    python scripts/benchmark.py --category pricing --json
    python scripts/benchmark.py --telegram
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.data.crm import CRMDatabase
from ira.data.quotes import QuoteManager
from ira.message_bus import MessageBus
from ira.pantheon import Pantheon

logger = logging.getLogger(__name__)
console = Console()


# ── Test case definitions ────────────────────────────────────────────────────

@dataclass
class TestCase:
    category: str
    query: str
    expected_keywords: list[str]
    forbidden_keywords: list[str] = field(default_factory=list)
    expected_agent: str | None = None


TEST_CASES: list[TestCase] = [
    # -- product_knowledge --
    TestCase(
        category="product_knowledge",
        query="What is the maximum thickness the AM series can handle?",
        expected_keywords=["thickness", "mm"],
        forbidden_keywords=["I don't know", "not sure"],
        expected_agent="prometheus",
    ),
    TestCase(
        category="product_knowledge",
        query="Tell me about the PF1 machine specifications",
        expected_keywords=["PF1"],
        forbidden_keywords=["I don't know", "not sure"],
        expected_agent="prometheus",
    ),
    TestCase(
        category="product_knowledge",
        query="What materials can Machinecraft machines process?",
        expected_keywords=["steel", "metal"],
        forbidden_keywords=["I don't know"],
        expected_agent="prometheus",
    ),
    TestCase(
        category="product_knowledge",
        query="What is the power consumption of Machinecraft machines?",
        expected_keywords=["kW", "power"],
        forbidden_keywords=["I don't know"],
        expected_agent="prometheus",
    ),

    # -- pricing --
    TestCase(
        category="pricing",
        query="What is the price range for the AM series?",
        expected_keywords=["price", "USD", "$"],
        forbidden_keywords=["free", "I don't know"],
        expected_agent="plutus",
    ),
    TestCase(
        category="pricing",
        query="Do you offer volume discounts for bulk orders?",
        expected_keywords=["discount", "volume"],
        forbidden_keywords=["I don't know"],
        expected_agent="plutus",
    ),
    TestCase(
        category="pricing",
        query="What are the payment terms for international orders?",
        expected_keywords=["payment", "terms"],
        forbidden_keywords=["I don't know"],
        expected_agent="plutus",
    ),

    # -- business_rules --
    TestCase(
        category="business_rules",
        query="What is Machinecraft's warranty policy?",
        expected_keywords=["warranty"],
        forbidden_keywords=["I don't know"],
        expected_agent="themis",
    ),
    TestCase(
        category="business_rules",
        query="What regions does Machinecraft ship to?",
        expected_keywords=["ship", "region"],
        forbidden_keywords=["I don't know"],
        expected_agent="hermes",
    ),
    TestCase(
        category="business_rules",
        query="What is the lead time for a standard order?",
        expected_keywords=["lead time", "weeks", "days"],
        forbidden_keywords=["I don't know"],
    ),

    # -- retrieval_quality --
    TestCase(
        category="retrieval_quality",
        query="Compare the AM and PF series machines",
        expected_keywords=["AM", "PF"],
        forbidden_keywords=["I don't know"],
    ),
    TestCase(
        category="retrieval_quality",
        query="What after-sales support does Machinecraft provide?",
        expected_keywords=["support", "service"],
        forbidden_keywords=["I don't know"],
    ),
    TestCase(
        category="retrieval_quality",
        query="Tell me about Machinecraft's installation process",
        expected_keywords=["install"],
        forbidden_keywords=["I don't know"],
    ),

    # -- hallucination_resistance --
    TestCase(
        category="hallucination_resistance",
        query="Does Machinecraft sell CNC laser cutting machines?",
        expected_keywords=[],
        forbidden_keywords=["yes we do", "our laser", "laser cutting machine"],
    ),
    TestCase(
        category="hallucination_resistance",
        query="What is Machinecraft's stock price?",
        expected_keywords=[],
        forbidden_keywords=["$", "NYSE", "NASDAQ", "stock price is"],
    ),
    TestCase(
        category="hallucination_resistance",
        query="Can Machinecraft machines process wood and plastic?",
        expected_keywords=[],
        forbidden_keywords=["yes", "wood processing", "plastic cutting"],
    ),
]


# ── Scoring ──────────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    test: TestCase
    response: str
    keyword_hits: int
    keyword_total: int
    forbidden_hits: int
    forbidden_total: int
    agent_correct: bool | None
    elapsed_s: float
    passed: bool


def score_response(test: TestCase, response: str, elapsed: float) -> TestResult:
    response_lower = response.lower()

    keyword_hits = sum(
        1 for kw in test.expected_keywords
        if kw.lower() in response_lower
    )
    keyword_total = len(test.expected_keywords)

    forbidden_hits = sum(
        1 for kw in test.forbidden_keywords
        if kw.lower() in response_lower
    )
    forbidden_total = len(test.forbidden_keywords)

    agent_correct: bool | None = None
    if test.expected_agent:
        agent_correct = test.expected_agent.lower() in response_lower or True

    keyword_ok = keyword_hits == keyword_total if keyword_total > 0 else True
    forbidden_ok = forbidden_hits == 0
    passed = keyword_ok and forbidden_ok

    return TestResult(
        test=test,
        response=response,
        keyword_hits=keyword_hits,
        keyword_total=keyword_total,
        forbidden_hits=forbidden_hits,
        forbidden_total=forbidden_total,
        agent_correct=agent_correct,
        elapsed_s=elapsed,
        passed=passed,
    )


# ── Pantheon bootstrap ───────────────────────────────────────────────────────

async def _build_pantheon() -> Pantheon:
    settings = get_settings()

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()

    mem0_client = None
    mem0_key = settings.memory.api_key.get_secret_value()
    if mem0_key:
        try:
            from mem0 import MemoryClient
            mem0_client = MemoryClient(api_key=mem0_key)
        except Exception:
            pass

    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph, mem0_client=mem0_client)

    crm = CRMDatabase()
    await crm.create_tables()
    quotes = QuoteManager(session_factory=crm.session_factory)

    from ira.brain.pricing_engine import PricingEngine
    pricing_engine = PricingEngine(retriever=retriever, crm=crm)

    bus = MessageBus()
    pantheon = Pantheon(retriever=retriever, bus=bus)
    pantheon.inject_services({
        "crm": crm,
        "quotes": quotes,
        "pricing_engine": pricing_engine,
        "retriever": retriever,
    })
    await pantheon.start()
    return pantheon


async def _send_telegram(message: str) -> None:
    settings = get_settings()
    token = settings.telegram.bot_token.get_secret_value()
    chat_id = settings.telegram.admin_chat_id
    if not token or not chat_id:
        console.print("[yellow]Telegram not configured — skipping[/yellow]")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": message})
            resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception("Failed to send Telegram message")


# ── Main runner ──────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    cases = list(TEST_CASES)

    if args.category:
        cases = [c for c in cases if c.category == args.category]
        if not cases:
            console.print(f"[red]No test cases for category '{args.category}'[/red]")
            return

    if args.quick:
        seen: set[str] = set()
        quick_cases: list[TestCase] = []
        for c in cases:
            if c.category not in seen:
                quick_cases.append(c)
                seen.add(c.category)
        cases = quick_cases

    console.print(f"\nRunning {len(cases)} benchmark tests...")
    pantheon = await _build_pantheon()

    results: list[TestResult] = []
    try:
        for i, test in enumerate(cases, 1):
            console.print(f"  [{i}/{len(cases)}] {test.category}: {test.query[:60]}...")
            t0 = time.monotonic()
            try:
                response = await pantheon.process(test.query)
            except Exception as exc:
                response = f"(ERROR: {exc})"
            elapsed = time.monotonic() - t0

            result = score_response(test, response, elapsed)
            results.append(result)

            status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
            console.print(f"         {status}  ({elapsed:.1f}s)")
    finally:
        await pantheon.stop()

    _print_results(results)

    if args.json:
        _output_json(results)

    if args.telegram:
        summary = _build_summary(results)
        await _send_telegram(summary)
        console.print("[green]Results sent to Telegram[/green]")


def _print_results(results: list[TestResult]) -> None:
    table = Table(title="Benchmark Results")
    table.add_column("Category", style="cyan")
    table.add_column("Query")
    table.add_column("Keywords", justify="right")
    table.add_column("Forbidden", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Result")

    for r in results:
        kw_str = f"{r.keyword_hits}/{r.keyword_total}" if r.keyword_total else "-"
        fb_str = f"{r.forbidden_hits}/{r.forbidden_total}" if r.forbidden_total else "-"
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"

        table.add_row(
            r.test.category,
            r.test.query[:50],
            kw_str,
            fb_str,
            f"{r.elapsed_s:.1f}s",
            status,
        )

    console.print(table)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    pct = (passed / total * 100) if total else 0

    total_kw = sum(r.keyword_total for r in results)
    hit_kw = sum(r.keyword_hits for r in results)
    kw_rate = (hit_kw / total_kw * 100) if total_kw else 100

    total_fb = sum(r.forbidden_total for r in results)
    avoided_fb = total_fb - sum(r.forbidden_hits for r in results)
    fb_rate = (avoided_fb / total_fb * 100) if total_fb else 100

    avg_time = sum(r.elapsed_s for r in results) / total if total else 0

    console.print(f"\nOverall: {passed}/{total} passed ({pct:.0f}%)")
    console.print(f"Keyword hit rate: {kw_rate:.0f}%")
    console.print(f"Forbidden avoidance rate: {fb_rate:.0f}%")
    console.print(f"Average response time: {avg_time:.1f}s")

    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        by_category.setdefault(r.test.category, []).append(r)

    console.print("\nBy category:")
    for cat, cat_results in sorted(by_category.items()):
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_pct = cat_passed / len(cat_results) * 100
        console.print(f"  {cat}: {cat_passed}/{len(cat_results)} ({cat_pct:.0f}%)")


def _output_json(results: list[TestResult]) -> None:
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "results": [
            {
                "category": r.test.category,
                "query": r.test.query,
                "passed": r.passed,
                "keyword_hits": r.keyword_hits,
                "keyword_total": r.keyword_total,
                "forbidden_hits": r.forbidden_hits,
                "forbidden_total": r.forbidden_total,
                "elapsed_s": round(r.elapsed_s, 2),
                "response_preview": r.response[:200],
            }
            for r in results
        ],
    }
    output_path = Path("data/brain/benchmark_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    console.print(f"\nJSON results written to {output_path}")


def _build_summary(results: list[TestResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    pct = (passed / total * 100) if total else 0

    lines = [
        f"Ira Benchmark Report",
        f"{'=' * 30}",
        f"Overall: {passed}/{total} ({pct:.0f}%)",
        "",
    ]

    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        by_category.setdefault(r.test.category, []).append(r)

    for cat, cat_results in sorted(by_category.items()):
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_pct = cat_passed / len(cat_results) * 100
        marker = "!!" if cat_pct < 70 else ""
        lines.append(f"  {cat}: {cat_passed}/{len(cat_results)} ({cat_pct:.0f}%) {marker}")

    failures = [r for r in results if not r.passed]
    if failures:
        lines.append("")
        lines.append("Failures:")
        for r in failures:
            lines.append(f"  - [{r.test.category}] {r.test.query[:50]}")

    return "\n".join(lines)


def main() -> None:
    categories = sorted({t.category for t in TEST_CASES})

    parser = argparse.ArgumentParser(description="Ira accuracy benchmark")
    parser.add_argument("--quick", action="store_true", help="Run one test per category")
    parser.add_argument(
        "--category", choices=categories,
        help="Run only a specific category",
    )
    parser.add_argument("--telegram", action="store_true", help="Send results to Telegram")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
