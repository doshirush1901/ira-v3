#!/usr/bin/env python3
"""Historical Gmail backfill for knowledge extraction.

Fetches email threads from Gmail, runs each through the DigestiveSystem
for nutrient extraction, and stores results in Qdrant + Neo4j.  Tracks
processed message IDs for resume support.

Usage::

    python scripts/ingest_mailbox.py
    python scripts/ingest_mailbox.py --since 2025-01-01 --limit 200
    python scripts/ingest_mailbox.py --query "from:client@example.com" --dry-run
    python scripts/ingest_mailbox.py --resume
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "brain" / "mailbox_ingestion_state.json"

_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def parse_args() -> argparse.Namespace:
    default_since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Backfill Gmail history into Ira's knowledge base.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=default_since,
        help=f"Earliest date to fetch (YYYY-MM-DD). Default: {default_since}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of email threads to process. Default: 100",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and display emails but do not ingest or persist.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip threads already processed (tracked in state file).",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="from:me OR to:me",
        help='Gmail search query. Default: "from:me OR to:me"',
    )
    return parser.parse_args()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"processed_ids": [], "last_run": None, "total_ingested": 0}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed_ids": [], "last_run": None, "total_ingested": 0}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")


def _build_gmail_service() -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    from ira.config import get_settings

    settings = get_settings()
    creds_path = Path(settings.google.credentials_path)
    token_path = Path(settings.google.token_path)

    creds: Credentials | None = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _GMAIL_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _fetch_thread_ids(service: Any, query: str, since: str, limit: int) -> list[str]:
    full_query = f"{query} after:{since}"
    thread_ids: list[str] = []
    page_token: str | None = None

    while len(thread_ids) < limit:
        batch_size = min(limit - len(thread_ids), 100)
        resp = (
            service.users()
            .threads()
            .list(userId="me", q=full_query, maxResults=batch_size, pageToken=page_token)
            .execute()
        )
        threads = resp.get("threads", [])
        if not threads:
            break
        thread_ids.extend(t["id"] for t in threads)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return thread_ids[:limit]


def _get_thread(service: Any, thread_id: str) -> dict[str, Any]:
    return service.users().threads().get(userId="me", id=thread_id, format="full").execute()


def _extract_thread_text(thread: dict[str, Any]) -> tuple[str, str, str]:
    """Extract plain-text body, subject, and sender from a thread."""
    messages = thread.get("messages", [])
    if not messages:
        return "", "", ""

    first_msg = messages[0]
    headers = {h["name"].lower(): h["value"] for h in first_msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "(no subject)")
    sender = headers.get("from", "")

    text_parts: list[str] = []
    for msg in messages:
        payload = msg.get("payload", {})
        _collect_text_parts(payload, text_parts)

    body = "\n\n---\n\n".join(text_parts) if text_parts else ""
    return body, subject, sender


def _collect_text_parts(payload: dict[str, Any], out: list[str]) -> None:
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            out.append(base64.urlsafe_b64decode(data).decode("utf-8", errors="replace"))
    for part in payload.get("parts", []):
        _collect_text_parts(part, out)


async def main() -> None:
    args = parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    console.print(
        f"\n[bold]Ira Mailbox Ingestion[/bold]"
        f"  since={args.since}  limit={args.limit}"
        f"  resume={args.resume}  dry_run={args.dry_run}\n"
    )

    state = _load_state() if args.resume else {"processed_ids": [], "last_run": None, "total_ingested": 0}
    processed_set = set(state.get("processed_ids", []))

    console.print("[dim]Authenticating with Gmail...[/dim]")
    service = await asyncio.to_thread(_build_gmail_service)

    console.print(f"[dim]Fetching threads matching: {args.query} after:{args.since}[/dim]")
    all_thread_ids = await asyncio.to_thread(_fetch_thread_ids, service, args.query, args.since, args.limit)
    console.print(f"Found {len(all_thread_ids)} threads.")

    if args.resume:
        thread_ids = [tid for tid in all_thread_ids if tid not in processed_set]
        skipped = len(all_thread_ids) - len(thread_ids)
        if skipped:
            console.print(f"[dim]Resuming: skipping {skipped} already-processed threads.[/dim]")
    else:
        thread_ids = all_thread_ids

    if not thread_ids:
        console.print("[yellow]No threads to process.[/yellow]")
        return

    from ira.brain.document_ingestor import DocumentIngestor
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.systems.digestive import DigestiveSystem

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)

    digestive = DigestiveSystem(
        ingestor=ingestor,
        knowledge_graph=graph,
        embedding_service=embedding,
        qdrant=qdrant,
    )

    total_chunks = 0
    total_entities: dict[str, int] = {"companies": 0, "people": 0, "machines": 0}
    total_processed = 0
    total_failed = 0
    cycle_start = time.monotonic()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting threads", total=len(thread_ids))

        for thread_id in thread_ids:
            try:
                thread = await asyncio.to_thread(_get_thread, service, thread_id)
                body, subject, sender = _extract_thread_text(thread)

                if not body.strip():
                    progress.advance(task)
                    continue

                if args.dry_run:
                    preview = body[:120].replace("\n", " ")
                    console.print(f"  [dim]DRY-RUN [{thread_id}] {subject}: {preview}...[/dim]")
                    total_processed += 1
                    progress.advance(task)
                    continue

                result = await digestive.ingest(
                    raw_data=body,
                    source=f"gmail:{sender}",
                    source_category="email_backfill",
                )

                total_chunks += result.get("chunks_created", 0)
                for key in total_entities:
                    total_entities[key] += result.get("entities_found", {}).get(key, 0)
                total_processed += 1

                processed_set.add(thread_id)

            except Exception:
                logging.getLogger(__name__).exception("Failed to process thread %s", thread_id)
                total_failed += 1

            progress.advance(task)

    elapsed = time.monotonic() - cycle_start

    if not args.dry_run:
        state["processed_ids"] = list(processed_set)
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["total_ingested"] = state.get("total_ingested", 0) + total_processed
        _save_state(state)

    await graph.close()
    await qdrant.close()

    console.rule("[bold green]Ingestion Complete")

    table = Table(title="Mailbox Ingestion Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Threads found", str(len(all_thread_ids)))
    table.add_row("Threads processed", str(total_processed))
    table.add_row("Threads failed", str(total_failed))
    table.add_row("Chunks created", str(total_chunks))
    table.add_row("Companies extracted", str(total_entities["companies"]))
    table.add_row("People extracted", str(total_entities["people"]))
    table.add_row("Machines extracted", str(total_entities["machines"]))
    table.add_row("Total time", f"{elapsed:.1f}s")
    table.add_row("Dry run", str(args.dry_run))

    console.print(table)
    console.print()


if __name__ == "__main__":
    asyncio.run(main())
