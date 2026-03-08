#!/usr/bin/env python3
"""Replay founder email threads through Ira and score responses.

Fetches Rushabh's sent emails from Gmail, extracts the original inbound
inquiry and his actual reply, runs the inquiry through Ira's pipeline,
then uses an LLM to score Ira's response against the founder's on eight
sales dimensions.

Usage::

    python scripts/shadow_training.py
    python scripts/shadow_training.py --limit 20 --since 2025-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
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

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SCORING_DIMENSIONS = [
    "technical_accuracy",
    "warmth",
    "urgency_handling",
    "price_sensitivity",
    "cultural_awareness",
    "follow_up_timing",
    "objection_handling",
    "closing_technique",
]

_SCORING_SYSTEM_PROMPT = """\
You are an expert sales coach evaluating AI-generated email responses against
a founder's actual replies for a B2B industrial machinery company (Machinecraft).

Score the AI response compared to the founder's response on each dimension
from 1 (poor) to 10 (excellent). Return ONLY valid JSON with this structure:

{
  "scores": {
    "technical_accuracy": <1-10>,
    "warmth": <1-10>,
    "urgency_handling": <1-10>,
    "price_sensitivity": <1-10>,
    "cultural_awareness": <1-10>,
    "follow_up_timing": <1-10>,
    "objection_handling": <1-10>,
    "closing_technique": <1-10>
  },
  "strengths": ["..."],
  "weaknesses": ["..."],
  "overall_notes": "..."
}

Scoring guide:
- technical_accuracy: Does the AI provide correct specs, model info, capabilities?
- warmth: Is the tone friendly, personal, relationship-building?
- urgency_handling: Does it match the urgency level of the inquiry?
- price_sensitivity: Does it handle pricing questions tactfully?
- cultural_awareness: Does it adapt to the sender's cultural context?
- follow_up_timing: Does it suggest appropriate next steps and timing?
- objection_handling: Does it address concerns effectively?
- closing_technique: Does it move the conversation toward a sale?"""


@dataclass
class ThreadScore:
    thread_id: str
    subject: str
    inquiry: str
    founder_reply: str
    ira_response: str
    scores: dict[str, int] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    notes: str = ""
    elapsed_s: float = 0.0
    error: str | None = None


# ── Gmail helpers ────────────────────────────────────────────────────────────

def _build_gmail_service() -> object:
    settings = get_settings()
    creds_path = Path(settings.google.credentials_path)
    token_path = Path(settings.google.token_path)

    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        nested = _extract_body(part)
        if nested:
            return nested

    return ""


def _extract_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_date(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _fetch_sent_threads(
    service: object, our_email: str, since: str | None, limit: int,
) -> list[dict]:
    query = f"from:{our_email} in:sent"
    if since:
        query += f" after:{since.replace('-', '/')}"

    resp = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=min(limit * 3, 500))
        .execute()
    )
    stubs = resp.get("messages", [])

    seen_threads: set[str] = set()
    thread_ids: list[str] = []
    for stub in stubs:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=stub["id"], format="metadata")
            .execute()
        )
        tid = msg.get("threadId", "")
        if tid and tid not in seen_threads:
            seen_threads.add(tid)
            thread_ids.append(tid)
        if len(thread_ids) >= limit:
            break

    threads: list[dict] = []
    for tid in thread_ids:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=tid, format="full")
            .execute()
        )
        threads.append(thread)

    return threads


def _extract_thread_pair(
    thread: dict, our_email: str,
) -> tuple[str, str, str, str] | None:
    """Extract (thread_id, subject, inbound_inquiry, founder_reply) from a thread.

    Returns None if the thread doesn't contain a clear inbound->reply pair.
    """
    messages = thread.get("messages", [])
    if len(messages) < 2:
        return None

    inbound_msg = None
    founder_reply_msg = None

    for msg in messages:
        headers = msg.get("payload", {}).get("headers", [])
        from_addr = _extract_header(headers, "From")
        _, from_email = parseaddr(from_addr)

        if from_email.lower() != our_email.lower() and inbound_msg is None:
            inbound_msg = msg

        if from_email.lower() == our_email.lower() and inbound_msg is not None:
            founder_reply_msg = msg
            break

    if not inbound_msg or not founder_reply_msg:
        return None

    inbound_headers = inbound_msg.get("payload", {}).get("headers", [])
    subject = _extract_header(inbound_headers, "Subject")

    inquiry_body = _extract_body(inbound_msg.get("payload", {}))
    reply_body = _extract_body(founder_reply_msg.get("payload", {}))

    if not inquiry_body.strip() or not reply_body.strip():
        return None

    return thread["id"], subject, inquiry_body, reply_body


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


# ── LLM scoring ──────────────────────────────────────────────────────────────

async def _score_with_llm(
    inquiry: str, founder_reply: str, ira_response: str,
) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.llm.openai_api_key.get_secret_value()
    model = settings.llm.openai_model

    user_message = (
        f"ORIGINAL INQUIRY:\n{inquiry[:3000]}\n\n"
        f"FOUNDER'S ACTUAL REPLY:\n{founder_reply[:3000]}\n\n"
        f"IRA'S GENERATED RESPONSE:\n{ira_response[:3000]}"
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SCORING_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    return json.loads(cleaned)


# ── Main runner ──────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    our_email = settings.google.training_email

    console.print(f"\nFetching sent emails from {our_email}...")
    service = await asyncio.to_thread(_build_gmail_service)

    raw_threads = await asyncio.to_thread(
        _fetch_sent_threads, service, our_email, args.since, args.limit * 2,
    )
    console.print(f"Fetched {len(raw_threads)} candidate threads")

    pairs: list[tuple[str, str, str, str]] = []
    for thread in raw_threads:
        pair = _extract_thread_pair(thread, our_email)
        if pair:
            pairs.append(pair)
        if len(pairs) >= args.limit:
            break

    if not pairs:
        console.print("[yellow]No valid inbound->reply thread pairs found[/yellow]")
        return

    console.print(f"Found {len(pairs)} threads with inbound->reply pairs\n")

    pantheon = await _build_pantheon()
    results: list[ThreadScore] = []

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Processing...", total=len(pairs))

            for thread_id, subject, inquiry, founder_reply in pairs:
                progress.update(task, description=f"Processing: {subject[:40]}...")
                ts = ThreadScore(
                    thread_id=thread_id,
                    subject=subject,
                    inquiry=inquiry[:1000],
                    founder_reply=founder_reply[:1000],
                    ira_response="",
                )

                t0 = time.monotonic()
                try:
                    ira_response = await pantheon.process(inquiry[:2000])
                    ts.ira_response = ira_response

                    scoring = await _score_with_llm(inquiry, founder_reply, ira_response)
                    ts.scores = scoring.get("scores", {})
                    ts.strengths = scoring.get("strengths", [])
                    ts.weaknesses = scoring.get("weaknesses", [])
                    ts.notes = scoring.get("overall_notes", "")
                except Exception as exc:
                    logger.exception("Failed on thread %s", thread_id)
                    ts.error = str(exc)

                ts.elapsed_s = time.monotonic() - t0
                results.append(ts)
                progress.advance(task)
    finally:
        await pantheon.stop()

    _print_results(results)



def _print_results(results: list[ThreadScore]) -> None:
    table = Table(title="Shadow Training Results")
    table.add_column("Subject", style="cyan", max_width=30)
    for dim in SCORING_DIMENSIONS:
        table.add_column(dim.replace("_", "\n"), justify="right", max_width=8)
    table.add_column("Avg", justify="right", style="bold")

    valid_results = [r for r in results if r.scores and not r.error]

    for r in valid_results:
        row = [r.subject[:30]]
        dim_scores: list[int] = []
        for dim in SCORING_DIMENSIONS:
            score = r.scores.get(dim, 0)
            dim_scores.append(score)
            color = "green" if score >= 7 else "yellow" if score >= 5 else "red"
            row.append(f"[{color}]{score}[/{color}]")

        avg = sum(dim_scores) / len(dim_scores) if dim_scores else 0
        color = "green" if avg >= 7 else "yellow" if avg >= 5 else "red"
        row.append(f"[{color}]{avg:.1f}[/{color}]")
        table.add_row(*row)

    console.print(table)

    if not valid_results:
        console.print("[yellow]No valid scored results[/yellow]")
        return

    console.print("\nAggregate Scores:")
    agg: dict[str, list[int]] = {dim: [] for dim in SCORING_DIMENSIONS}
    for r in valid_results:
        for dim in SCORING_DIMENSIONS:
            if dim in r.scores:
                agg[dim].append(r.scores[dim])

    agg_table = Table()
    agg_table.add_column("Dimension", style="cyan")
    agg_table.add_column("Avg", justify="right")
    agg_table.add_column("Min", justify="right")
    agg_table.add_column("Max", justify="right")

    for dim in SCORING_DIMENSIONS:
        vals = agg[dim]
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        color = "green" if avg >= 7 else "yellow" if avg >= 5 else "red"
        agg_table.add_row(
            dim.replace("_", " ").title(),
            f"[{color}]{avg:.1f}[/{color}]",
            str(min(vals)),
            str(max(vals)),
        )

    console.print(agg_table)

    all_scores = [s for r in valid_results for s in r.scores.values()]
    overall = sum(all_scores) / len(all_scores) if all_scores else 0
    console.print(f"\nOverall average: {overall:.1f}/10 across {len(valid_results)} threads")

    errors = [r for r in results if r.error]
    if errors:
        console.print(f"[red]{len(errors)} thread(s) failed[/red]")


def _build_summary(results: list[ThreadScore]) -> str:
    valid = [r for r in results if r.scores and not r.error]
    if not valid:
        return "Shadow Training: No valid results to report."

    agg: dict[str, list[int]] = {dim: [] for dim in SCORING_DIMENSIONS}
    for r in valid:
        for dim in SCORING_DIMENSIONS:
            if dim in r.scores:
                agg[dim].append(r.scores[dim])

    lines = [
        "Ira Shadow Training Report",
        "=" * 30,
        f"Threads analysed: {len(valid)}",
        "",
    ]

    weak_dims: list[str] = []
    for dim in SCORING_DIMENSIONS:
        vals = agg[dim]
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        marker = " << WEAK" if avg < 5 else ""
        if avg < 5:
            weak_dims.append(dim.replace("_", " ").title())
        lines.append(f"  {dim.replace('_', ' ').title()}: {avg:.1f}/10{marker}")

    all_scores = [s for r in valid for s in r.scores.values()]
    overall = sum(all_scores) / len(all_scores) if all_scores else 0
    lines.append(f"\nOverall: {overall:.1f}/10")

    if weak_dims:
        lines.append(f"\nPriority training areas: {', '.join(weak_dims)}")

    errors = sum(1 for r in results if r.error)
    if errors:
        lines.append(f"\n{errors} thread(s) failed to process")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow training — score Ira against founder replies")
    parser.add_argument("--limit", type=int, default=10, help="Max threads to process (default: 10)")
    parser.add_argument("--since", type=str, default=None, help="Only threads after this date (YYYY-MM-DD)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
