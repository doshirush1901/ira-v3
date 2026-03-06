#!/usr/bin/env python3
"""Comprehensive sleep/learning cycle that chains all dream phases.

Runs the full nightly consolidation pipeline:
  1. Process feedback backlog
  2. Nemesis sleep training (corrections)
  3. Full dream mode cycle
  4. Graph consolidation
  5. Morning summary to Telegram

Usage::

    python scripts/nap.py
    python scripts/nap.py --quick
    python scripts/nap.py --dry-run --time 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_BACKLOG_PATH = PROJECT_ROOT / "data" / "brain" / "feedback_backlog.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Ira's full sleep/learning cycle.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip slow phases (graph consolidation, quality review).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log all actions but do not persist changes.",
    )
    parser.add_argument(
        "--time",
        type=int,
        default=None,
        help="Override the cycle time limit in seconds.",
    )
    return parser.parse_args()


async def run_phase(name: str, coro, stats: dict) -> None:
    """Execute a single phase with timing and error handling."""
    console.rule(f"[bold cyan]{name}")
    t0 = time.monotonic()
    try:
        result = await coro
        elapsed = time.monotonic() - t0
        stats[name] = {"status": "OK", "elapsed_s": round(elapsed, 2), "detail": result}
        console.print(f"  [green]OK[/green] in {elapsed:.1f}s")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        stats[name] = {"status": "FAIL", "elapsed_s": round(elapsed, 2), "error": str(exc)}
        console.print(f"  [red]FAIL[/red] in {elapsed:.1f}s — {exc}")


async def phase_feedback_backlog(dry_run: bool) -> dict:
    from ira.brain.correction_store import CorrectionStore

    if not FEEDBACK_BACKLOG_PATH.exists():
        return {"items": 0, "note": "no backlog file"}

    entries = []
    with FEEDBACK_BACKLOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        return {"items": 0}

    store = CorrectionStore()
    await store.initialize()
    ingested = 0

    for entry in entries:
        entity = entry.get("entity", entry.get("query", ""))
        new_value = entry.get("new_value", entry.get("correction", ""))
        if not entity:
            continue
        if dry_run:
            console.print(f"    [dim]DRY-RUN: would ingest correction for '{entity}'[/dim]")
        else:
            await store.add_correction(
                entity=entity,
                new_value=new_value,
                category=entry.get("category", "GENERAL"),
                severity=entry.get("severity", "MEDIUM"),
                old_value=entry.get("old_value", ""),
                source="feedback_backlog",
            )
        ingested += 1

    if not dry_run and ingested > 0:
        FEEDBACK_BACKLOG_PATH.write_text("", encoding="utf-8")

    return {"items": ingested, "dry_run": dry_run}


async def phase_sleep_training(dry_run: bool) -> dict:
    from ira.brain.correction_store import CorrectionStore
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.sleep_trainer import SleepTrainer

    store = CorrectionStore()
    await store.initialize()
    pending = await store.get_pending_corrections()
    if not pending:
        return {"corrections": 0, "note": "nothing pending"}

    if dry_run:
        return {"corrections": len(pending), "dry_run": True, "note": "would train"}

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    trainer = SleepTrainer(
        correction_store=store,
        qdrant_manager=qdrant,
        embedding_service=embedding,
    )
    stats = await trainer.run_training()
    await qdrant.close()
    return stats


async def phase_dream_cycle(dry_run: bool) -> dict:
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.data.crm import CRMDatabase
    from ira.memory.conversation import ConversationMemory
    from ira.memory.dream_mode import DreamMode
    from ira.memory.episodic import EpisodicMemory
    from ira.memory.long_term import LongTermMemory
    from ira.systems.musculoskeletal import MusculoskeletalSystem

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)

    crm = CRMDatabase()
    await crm.create_tables()

    long_term = LongTermMemory()
    episodic = EpisodicMemory(long_term=long_term)
    await episodic.initialize()
    conversation = ConversationMemory()
    await conversation.initialize()
    musculoskeletal = MusculoskeletalSystem()
    await musculoskeletal.create_tables()

    dream = DreamMode(
        long_term=long_term,
        episodic=episodic,
        conversation=conversation,
        musculoskeletal=musculoskeletal,
        retriever=retriever,
        crm=crm,
    )
    await dream.initialize()

    if dry_run:
        await dream.close()
        await graph.close()
        await qdrant.close()
        return {"dry_run": True, "note": "would run full dream cycle"}

    report = await dream.run_dream_cycle()

    await dream.close()
    await conversation.close()
    await episodic.close()
    await musculoskeletal.close()
    await graph.close()
    await qdrant.close()

    return {
        "memories_consolidated": report.memories_consolidated,
        "gaps": len(report.gaps_identified),
        "connections": len(report.creative_connections),
        "campaign_insights": len(report.campaign_insights),
    }


async def phase_graph_consolidation(dry_run: bool) -> dict:
    from ira.brain.graph_consolidation import GraphConsolidation
    from ira.brain.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph()
    gc = GraphConsolidation(knowledge_graph=graph)

    if dry_run:
        co_access = await gc.build_co_access_matrix()
        await graph.close()
        return {"dry_run": True, "retrieval_pairs": len(co_access)}

    stats = await gc.run_consolidation()
    await graph.close()
    return stats


async def phase_morning_summary(stats: dict, dry_run: bool) -> dict:
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    token = settings.telegram.bot_token.get_secret_value()
    chat_id = settings.telegram.admin_chat_id
    if not token or not chat_id:
        return {"sent": False, "reason": "telegram not configured"}

    dream_detail = stats.get("Dream Cycle", {}).get("detail", {})
    training_detail = stats.get("Sleep Training", {}).get("detail", {})

    lines = [
        "Nap cycle complete.",
        "",
        f"Feedback backlog: {stats.get('Feedback Backlog', {}).get('detail', {}).get('items', '?')} items",
        f"Sleep training: {training_detail.get('corrections', '?')} corrections",
        f"Dream cycle: {dream_detail.get('memories_consolidated', '?')} memories, "
        f"{dream_detail.get('gaps', '?')} gaps, "
        f"{dream_detail.get('connections', '?')} connections",
    ]
    for phase_name, phase_data in stats.items():
        status = phase_data.get("status", "?")
        elapsed = phase_data.get("elapsed_s", "?")
        lines.append(f"  {phase_name}: {status} ({elapsed}s)")

    message = "\n".join(lines)

    if dry_run:
        console.print(f"    [dim]DRY-RUN: would send to Telegram:[/dim]\n{message}")
        return {"sent": False, "dry_run": True}

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
    return {"sent": True}


async def main() -> None:
    args = parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print(
        f"\n[bold]Ira Nap Cycle[/bold]"
        f"  quick={args.quick}  dry_run={args.dry_run}"
        f"  time_limit={args.time or 'none'}\n"
    )

    cycle_start = time.monotonic()
    stats: dict = {}

    await run_phase(
        "Feedback Backlog",
        phase_feedback_backlog(dry_run=args.dry_run),
        stats,
    )

    await run_phase(
        "Sleep Training",
        phase_sleep_training(dry_run=args.dry_run),
        stats,
    )

    await run_phase(
        "Dream Cycle",
        phase_dream_cycle(dry_run=args.dry_run),
        stats,
    )

    if not args.quick:
        await run_phase(
            "Graph Consolidation",
            phase_graph_consolidation(dry_run=args.dry_run),
            stats,
        )

    await run_phase(
        "Morning Summary",
        phase_morning_summary(stats, dry_run=args.dry_run),
        stats,
    )

    total_elapsed = time.monotonic() - cycle_start

    console.rule("[bold green]Nap Complete")

    table = Table(title="Phase Summary")
    table.add_column("Phase", style="cyan")
    table.add_column("Status")
    table.add_column("Time (s)", justify="right")
    table.add_column("Detail")

    for phase_name, phase_data in stats.items():
        status = phase_data.get("status", "?")
        style = "green" if status == "OK" else "red"
        elapsed = str(phase_data.get("elapsed_s", "?"))
        detail = phase_data.get("detail", phase_data.get("error", ""))
        if isinstance(detail, dict):
            detail = ", ".join(f"{k}={v}" for k, v in detail.items())
        table.add_row(phase_name, f"[{style}]{status}[/{style}]", elapsed, str(detail)[:80])

    console.print(table)
    console.print(f"\n[bold]Total time:[/bold] {total_elapsed:.1f}s\n")


if __name__ == "__main__":
    asyncio.run(main())
