#!/usr/bin/env python3
"""When takeout ingest process exits, send a completion report to the given email.

Usage:
  poetry run python scripts/takeout_notify_when_done.py [--pid PID] [--to EMAIL]

If --pid is given, waits for that process to exit before sending. Otherwise sends immediately
using the latest checkpoint (for use after ingest has already finished).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def wait_for_pid(pid: int, poll_seconds: int = 60) -> None:
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(poll_seconds)


def load_checkpoint() -> dict:
    path = PROJECT_ROOT / "data/brain/takeout_ingest_batch-takeout.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_qdrant_count() -> int | None:
    import subprocess
    try:
        out = subprocess.run(
            ["poetry", "run", "ira", "takeout", "verify"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return None
        for line in out.stdout.splitlines():
            if "takeout_email_protein" in line and ":" in line:
                try:
                    return int(line.split(":")[-1].strip())
                except ValueError:
                    pass
    except Exception:
        pass
    return None


def build_report(checkpoint: dict, qdrant_count: int | None) -> str:
    stats = checkpoint.get("stats", {})
    entities = stats.get("entities", {})
    lines = [
        "Takeout protein ingestion complete. You can ingest new data when ready.",
        "",
        "Summary:",
        f"  mbox_files: {stats.get('mbox_files', 0)}",
        f"  messages_seen: {stats.get('messages_seen', 0)}",
        f"  messages_skipped_checkpoint: {stats.get('messages_skipped_checkpoint', 0)}",
        f"  messages_skipped_noise: {stats.get('messages_skipped_noise', 0)}",
        f"  messages_skipped_low_signal: {stats.get('messages_skipped_low_signal', 0)}",
        f"  messages_processed: {stats.get('messages_processed', 0)}",
        f"  messages_with_protein: {stats.get('messages_with_protein', 0)}",
        f"  chunks_created: {stats.get('chunks_created', 0)}",
        f"  mem0_written: {stats.get('mem0_written', 0)}",
        f"  entities: companies={entities.get('companies', 0)} people={entities.get('people', 0)} machines={entities.get('machines', 0)} relationships={entities.get('relationships', 0)}",
    ]
    if qdrant_count is not None:
        lines.append(f"  Qdrant points (takeout_email_protein): {qdrant_count}")
    lines.append("")
    lines.append("Checkpoint: data/brain/takeout_ingest_batch-takeout.json")
    return "\n".join(lines)


async def send_report(to: str, body: str) -> None:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from ira.interfaces.email_processor import send_simple_notification
    subject = "Ira: Takeout protein ingestion complete — ready for new data"
    result = await send_simple_notification(to, subject, body)
    print(f"Sent to {to} (message_id={result.get('id', '')})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send takeout completion report email when ingest finishes.")
    parser.add_argument("--pid", type=int, default=None, help="Process ID to wait for (optional)")
    parser.add_argument("--to", type=str, default="rushabh@machinecraft.org", help="Email address to notify")
    parser.add_argument("--poll", type=int, default=60, help="Seconds between PID checks")
    args = parser.parse_args()

    if args.pid is not None:
        print(f"Waiting for PID {args.pid} to exit (poll every {args.poll}s)...")
        wait_for_pid(args.pid, args.poll)
        print("Process exited. Building report...")

    checkpoint = load_checkpoint()
    if not checkpoint:
        print("No checkpoint found. Exiting.", file=sys.stderr)
        sys.exit(1)

    qdrant_count = get_qdrant_count()
    body = build_report(checkpoint, qdrant_count)
    asyncio.run(send_report(args.to, body))


if __name__ == "__main__":
    main()
