#!/usr/bin/env python3
"""Daily health report for all Ira subsystems.

Checks connectivity and configuration of every external service,
reports dream recency, knowledge health, and agent power levels.

Usage::

    python scripts/ira_vital_signs.py
    python scripts/ira_vital_signs.py --telegram
    python scripts/ira_vital_signs.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DREAM_LOG_PATH = PROJECT_ROOT / "dream_log.json"
POWER_LEVELS_PATH = PROJECT_ROOT / "data" / "brain" / "power_levels.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Ira's daily health check across all subsystems.",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Send the report to Telegram.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the report as JSON instead of a Rich table.",
    )
    return parser.parse_args()


async def check_qdrant() -> dict[str, Any]:
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.qdrant_manager import QdrantManager

    t0 = time.monotonic()
    try:
        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        collections = await qdrant._client.get_collections()
        latency = (time.monotonic() - t0) * 1000
        names = [c.name for c in collections.collections]
        expected = qdrant._default_collection
        found = expected in names
        await qdrant.close()
        return {
            "status": "OK" if found else "WARN",
            "latency_ms": round(latency, 1),
            "detail": f"collection '{expected}' {'found' if found else 'MISSING'} ({len(names)} total)",
        }
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def check_neo4j() -> dict[str, Any]:
    from ira.brain.knowledge_graph import KnowledgeGraph

    t0 = time.monotonic()
    try:
        graph = KnowledgeGraph()
        result = await graph.run_cypher("RETURN 1 AS ok")
        latency = (time.monotonic() - t0) * 1000
        await graph.close()
        ok = bool(result)
        return {
            "status": "OK" if ok else "WARN",
            "latency_ms": round(latency, 1),
            "detail": "RETURN 1 succeeded" if ok else "empty result",
        }
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def check_openai() -> dict[str, Any]:
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    key = settings.llm.openai_api_key.get_secret_value()
    if not key:
        return {"status": "FAIL", "latency_ms": None, "detail": "no API key configured"}

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4.1-nano",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Say OK"}],
                },
            )
            resp.raise_for_status()
        latency = (time.monotonic() - t0) * 1000
        return {"status": "OK", "latency_ms": round(latency, 1), "detail": "completion succeeded"}
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def check_voyage() -> dict[str, Any]:
    from ira.brain.embeddings import EmbeddingService

    t0 = time.monotonic()
    try:
        svc = EmbeddingService()
        vectors = await svc.embed_texts(["vital signs check"])
        latency = (time.monotonic() - t0) * 1000
        dim = len(vectors[0]) if vectors else 0
        return {"status": "OK", "latency_ms": round(latency, 1), "detail": f"dim={dim}"}
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def check_mem0() -> dict[str, Any]:
    from ira.config import get_settings

    settings = get_settings()
    key = settings.memory.api_key.get_secret_value()
    if not key:
        return {"status": "WARN", "latency_ms": None, "detail": "no API key configured"}

    t0 = time.monotonic()
    try:
        from mem0 import MemoryClient
        client = MemoryClient(api_key=key)
        _ = client.get_all(user_id="vital_signs_probe", limit=1)
        latency = (time.monotonic() - t0) * 1000
        return {"status": "OK", "latency_ms": round(latency, 1), "detail": "client connected"}
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


def check_last_dream() -> dict[str, Any]:
    if not DREAM_LOG_PATH.exists():
        return {"status": "WARN", "latency_ms": None, "detail": "dream_log.json not found"}

    try:
        data = json.loads(DREAM_LOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not data:
            return {"status": "WARN", "latency_ms": None, "detail": "empty dream log"}

        last = data[-1]
        ts = last.get("timestamp", last.get("cycle_date", ""))
        if not ts:
            return {"status": "WARN", "latency_ms": None, "detail": "no timestamp in last entry"}

        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        status = "OK" if age_hours < 36 else "WARN"
        return {
            "status": status,
            "latency_ms": None,
            "detail": f"last dream {age_hours:.1f}h ago ({dt.date().isoformat()})",
        }
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def check_knowledge_health() -> dict[str, Any]:
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.qdrant_manager import QdrantManager

    t0 = time.monotonic()
    try:
        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        col = qdrant._default_collection
        info = await qdrant._client.get_collection(col)
        latency = (time.monotonic() - t0) * 1000
        count = info.points_count
        await qdrant.close()
        status = "OK" if count and count > 0 else "WARN"
        return {
            "status": status,
            "latency_ms": round(latency, 1),
            "detail": f"{count} vectors in '{col}'",
        }
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


def check_power_levels() -> dict[str, Any]:
    if not POWER_LEVELS_PATH.exists():
        return {"status": "WARN", "latency_ms": None, "detail": "power_levels.json not found"}

    try:
        data = json.loads(POWER_LEVELS_PATH.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
        if not agents:
            return {"status": "WARN", "latency_ms": None, "detail": "no agents tracked"}

        sorted_agents = sorted(agents.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
        top3 = ", ".join(f"{name}={info.get('score', 0)}" for name, info in sorted_agents[:3])
        return {
            "status": "OK",
            "latency_ms": None,
            "detail": f"{len(agents)} agents tracked (top: {top3})",
        }
    except Exception as exc:
        return {"status": "FAIL", "latency_ms": None, "detail": str(exc)}


async def send_telegram(report: dict[str, dict[str, Any]]) -> None:
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    token = settings.telegram.bot_token.get_secret_value()
    chat_id = settings.telegram.admin_chat_id
    if not token or not chat_id:
        console.print("[yellow]Telegram not configured, skipping send.[/yellow]")
        return

    lines = ["Ira Vital Signs Report", ""]
    for name, info in report.items():
        status = info.get("status", "?")
        marker = {"OK": "+", "WARN": "~", "FAIL": "!!"}.get(status, "?")
        detail = info.get("detail", "")
        latency = info.get("latency_ms")
        lat_str = f" ({latency}ms)" if latency is not None else ""
        lines.append(f"[{marker}] {name}: {status}{lat_str}")
        if detail:
            lines.append(f"    {detail}")

    message = "\n".join(lines)

    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
    console.print("[green]Report sent to Telegram.[/green]")


def render_table(report: dict[str, dict[str, Any]]) -> None:
    table = Table(title="Ira Vital Signs")
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    table.add_column("Latency", justify="right")
    table.add_column("Detail")

    for name, info in report.items():
        status = info.get("status", "?")
        style = {"OK": "green", "WARN": "yellow", "FAIL": "red"}.get(status, "white")
        latency = info.get("latency_ms")
        lat_str = f"{latency}ms" if latency is not None else "-"
        detail = str(info.get("detail", ""))[:80]
        table.add_row(name, f"[{style}]{status}[/{style}]", lat_str, detail)

    console.print(table)


async def render_leaderboard() -> None:
    if not POWER_LEVELS_PATH.exists():
        return

    try:
        data = json.loads(POWER_LEVELS_PATH.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
    except (json.JSONDecodeError, OSError):
        return

    if not agents:
        return

    from ira.brain.power_levels import PowerLevelTracker

    tracker = PowerLevelTracker()
    await tracker._load()
    board = tracker.get_leaderboard()

    table = Table(title="Agent Power Levels")
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Agent", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Tier")
    table.add_column("W/L", justify="right")

    for i, row in enumerate(board[:15], 1):
        tier = row["tier"]
        tier_style = {
            "LEGEND": "bold magenta",
            "HERO": "bold yellow",
            "WARRIOR": "bold blue",
            "MORTAL": "dim",
        }.get(tier, "white")
        wl = f"{row.get('successes', 0)}/{row.get('failures', 0)}"
        table.add_row(str(i), row["agent"], str(row["score"]), f"[{tier_style}]{tier}[/{tier_style}]", wl)

    console.print(table)


async def main() -> None:
    args = parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print("\n[bold]Ira Vital Signs[/bold]\n")

    report: dict[str, dict[str, Any]] = {}

    qdrant_result, neo4j_result, openai_result, voyage_result, mem0_result, knowledge_result = (
        await asyncio.gather(
            check_qdrant(),
            check_neo4j(),
            check_openai(),
            check_voyage(),
            check_mem0(),
            check_knowledge_health(),
            return_exceptions=False,
        )
    )

    report["Qdrant"] = qdrant_result
    report["Neo4j"] = neo4j_result
    report["OpenAI"] = openai_result
    report["Voyage"] = voyage_result
    report["Mem0"] = mem0_result
    report["Last Dream"] = check_last_dream()
    report["Knowledge Health"] = knowledge_result
    report["Agent Power Levels"] = check_power_levels()

    if args.json:
        console.print_json(json.dumps(report, indent=2, default=str))
    else:
        render_table(report)
        await render_leaderboard()

    if args.telegram:
        await send_telegram(report)

    fail_count = sum(1 for v in report.values() if v.get("status") == "FAIL")
    warn_count = sum(1 for v in report.values() if v.get("status") == "WARN")
    ok_count = sum(1 for v in report.values() if v.get("status") == "OK")
    console.print(f"\n[bold]Summary:[/bold] {ok_count} OK, {warn_count} WARN, {fail_count} FAIL\n")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
