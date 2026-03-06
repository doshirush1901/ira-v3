#!/usr/bin/env python3
"""Sync Gmail conversations with the CRM interaction log.

For each contact in the CRM, searches Gmail for threads involving that
contact, extracts recent messages, logs new interactions, detects reply
status, and updates deal-stage hints based on email content.

Usage::

    python scripts/crm_gmail_sync.py
    python scripts/crm_gmail_sync.py --full --days 30
    python scripts/crm_gmail_sync.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.config import get_settings
from ira.data.crm import CRMDatabase
from ira.data.models import Channel, Direction

logger = logging.getLogger(__name__)
console = Console()

_STATE_PATH = Path("data/brain/gmail_sync_state.json")
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_STAGE_KEYWORDS: dict[str, list[str]] = {
    "ENGAGED": ["interested", "tell me more", "can you share", "brochure", "catalog"],
    "QUALIFIED": ["budget", "timeline", "decision maker", "requirements", "specifications"],
    "PROPOSAL": ["quote", "proposal", "pricing", "offer", "quotation"],
    "NEGOTIATION": ["discount", "negotiate", "terms", "payment terms", "counter"],
    "WON": ["purchase order", "PO", "confirmed", "go ahead", "proceed"],
    "LOST": ["not interested", "went with another", "no longer", "cancel"],
}


def _load_state() -> dict[str, str]:
    if not _STATE_PATH.exists():
        return {}
    return json.loads(_STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict[str, str]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


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


def _search_threads(service: object, email: str, after_date: str) -> list[dict]:
    query = f"from:{email} OR to:{email} after:{after_date}"
    results: list[dict] = []
    page_token: str | None = None

    while True:
        resp = (
            service.users()
            .threads()
            .list(userId="me", q=query, pageToken=page_token)
            .execute()
        )
        results.extend(resp.get("threads", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def _get_thread_messages(service: object, thread_id: str) -> list[dict]:
    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="metadata")
        .execute()
    )
    return thread.get("messages", [])


def _extract_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _detect_stage_hint(subject: str, snippet: str) -> str | None:
    text = f"{subject} {snippet}".lower()
    for stage, keywords in _STAGE_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            return stage
    return None


def _detect_reply_status(
    messages: list[dict], contact_email: str, our_email: str,
) -> dict:
    contact_replied = False
    last_reply_at: str | None = None
    last_sender: str | None = None

    for msg in messages:
        headers = msg.get("payload", {}).get("headers", [])
        from_addr = _extract_header(headers, "From").lower()
        date_str = _extract_header(headers, "Date")

        if contact_email.lower() in from_addr:
            contact_replied = True
            last_reply_at = date_str
            last_sender = "contact"
        elif our_email.lower() in from_addr:
            last_sender = "us"

    return {
        "contact_replied": contact_replied,
        "last_reply_at": last_reply_at,
        "last_sender": last_sender,
        "awaiting_reply": last_sender == "us",
    }


async def sync_contact(
    crm: CRMDatabase,
    service: object,
    contact: object,
    after_date: str,
    our_email: str,
    dry_run: bool,
) -> dict:
    email = contact.email
    contact_id = str(contact.id)

    threads = await asyncio.to_thread(_search_threads, service, email, after_date)

    stats = {
        "contact": contact.name,
        "email": email,
        "threads_found": len(threads),
        "interactions_logged": 0,
        "reply_status": None,
        "stage_hint": None,
    }

    if not threads:
        return stats

    for thread_stub in threads:
        thread_id = thread_stub["id"]
        messages = await asyncio.to_thread(_get_thread_messages, service, thread_id)

        if not messages:
            continue

        latest = messages[-1]
        headers = latest.get("payload", {}).get("headers", [])
        from_addr = _extract_header(headers, "From")
        subject = _extract_header(headers, "Subject")
        snippet = latest.get("snippet", "")

        direction = (
            Direction.INBOUND
            if email.lower() in from_addr.lower()
            else Direction.OUTBOUND
        )

        if not dry_run:
            await crm.create_interaction(
                contact_id=contact_id,
                channel=Channel.EMAIL,
                direction=direction,
                subject=subject,
                content=json.dumps({
                    "thread_id": thread_id,
                    "snippet": snippet[:500],
                    "message_count": len(messages),
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }),
            )
        stats["interactions_logged"] += 1

        reply_info = _detect_reply_status(messages, email, our_email)
        stats["reply_status"] = reply_info

        hint = _detect_stage_hint(subject, snippet)
        if hint:
            stats["stage_hint"] = hint
            if not dry_run:
                deals = await crm.get_deals_for_contact(contact_id)
                for deal in deals:
                    if deal.get("stage") not in ("WON", "LOST"):
                        await crm.update_deal(deal["id"], notes=f"[gmail_sync] Stage hint: {hint}")

    return stats


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    our_email = settings.google.training_email

    crm = CRMDatabase()
    await crm.create_tables()

    service = await asyncio.to_thread(_build_gmail_service)

    state = _load_state()

    if args.full:
        after_date = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y/%m/%d")
    else:
        after_date = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y/%m/%d")

    contacts = await crm.list_contacts()
    if not contacts:
        console.print("[yellow]No contacts found in CRM[/yellow]")
        return

    console.print(f"\nSyncing {len(contacts)} contacts (lookback: {args.days} days)")
    if args.dry_run:
        console.print("[yellow]DRY RUN — no CRM writes[/yellow]")

    results: list[dict] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Syncing...", total=len(contacts))

        for contact in contacts:
            progress.update(task, description=f"Syncing {contact.name}...")
            try:
                result = await sync_contact(
                    crm, service, contact, after_date, our_email, args.dry_run,
                )
                results.append(result)

                if not args.full:
                    state[contact.email] = datetime.now(timezone.utc).isoformat()
            except Exception:
                logger.exception("Failed to sync contact %s", contact.email)
                results.append({
                    "contact": contact.name,
                    "email": contact.email,
                    "error": True,
                })
            progress.advance(task)

    if not args.dry_run:
        _save_state(state)

    table = Table(title="Gmail Sync Results")
    table.add_column("Contact", style="cyan")
    table.add_column("Email")
    table.add_column("Threads", justify="right")
    table.add_column("Logged", justify="right")
    table.add_column("Replied?")
    table.add_column("Awaiting?")
    table.add_column("Stage Hint")

    for r in results:
        if r.get("error"):
            table.add_row(r["contact"], r["email"], "-", "-", "-", "-", "[red]ERROR[/red]")
            continue

        reply = r.get("reply_status") or {}
        table.add_row(
            r["contact"],
            r["email"],
            str(r["threads_found"]),
            str(r["interactions_logged"]),
            "[green]Yes[/green]" if reply.get("contact_replied") else "[red]No[/red]",
            "[yellow]Yes[/yellow]" if reply.get("awaiting_reply") else "No",
            r.get("stage_hint") or "-",
        )

    console.print(table)

    total_threads = sum(r.get("threads_found", 0) for r in results if not r.get("error"))
    total_logged = sum(r.get("interactions_logged", 0) for r in results if not r.get("error"))
    errors = sum(1 for r in results if r.get("error"))

    console.print(f"\nTotal: {total_threads} threads, {total_logged} interactions logged, {errors} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Gmail conversations with CRM")
    parser.add_argument("--full", action="store_true", help="Full sync (ignore last-sync state)")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default: 7)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to CRM")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
