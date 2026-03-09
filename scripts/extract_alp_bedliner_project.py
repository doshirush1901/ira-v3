#!/usr/bin/env python3
"""
Extract all email data for the Customer-H automotive bedliner project.

Searches Gmail for all conversations with contact1@example-customer.com and
contact2@example-customer.com, reads full threads, downloads attachments,
and saves a structured JSON + markdown summary for case study prep.
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "openclaw" / "agents" / "ira" / "src" / "tools"))

from google_tools import (
    gmail_search,
    gmail_get_thread,
    gmail_read_message,
    gmail_get_attachments,
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "case_studies" / "alp_bedliner"
ATTACHMENTS_DIR = OUTPUT_DIR / "attachments"

CONTACTS = [
    "contact1@example-customer.com",
    "contact2@example-customer.com",
]

SEARCH_QUERIES = [
    "(from:{c} OR to:{c})",
]

BEDLINER_KEYWORDS = [
    "bedliner", "bed liner", "pickup", "pick up", "truck",
    "hdpe", "tooling", "trimming", "customer_h", "customer_h_parent", "customer_h_alias",
    "pf1-3520", "pf1-3020", "pf1-1510", "pf1-2530", "pf1-1520",
]


def extract_ids(search_result: str) -> list[dict]:
    """Parse message and thread IDs from gmail_search output."""
    entries = []
    blocks = search_result.strip().split("\n\n")
    for block in blocks:
        msg_match = re.search(r"\[id:(\S+?)\]", block)
        thread_match = re.search(r"\[thread:(\S+?)\]", block)
        subject_match = re.search(r"Subject:\s*(.+)", block)
        date_match = re.search(r"Date:\s*(.+)", block)
        from_match = re.search(r"From:\s*(.+)", block)

        if msg_match:
            entries.append({
                "message_id": msg_match.group(1),
                "thread_id": thread_match.group(1) if thread_match else "",
                "subject": subject_match.group(1).strip() if subject_match else "",
                "date": date_match.group(1).strip() if date_match else "",
                "from": from_match.group(1).strip() if from_match else "",
            })
    return entries


def search_all_emails() -> list[dict]:
    """Search for all emails involving the two contacts."""
    all_entries = []
    seen_ids = set()

    for contact in CONTACTS:
        query = f"(from:{contact} OR to:{contact})"
        print(f"\n--- Searching: {query} ---")
        result = gmail_search(query, max_results=20)
        print(result[:500])

        entries = extract_ids(result)
        for e in entries:
            if e["message_id"] not in seen_ids:
                seen_ids.add(e["message_id"])
                all_entries.append(e)

        time.sleep(0.5)

    # Also search by bedliner keywords in case there are emails with other participants
    for kw in ["bedliner Customer-H", "pickup truck bedliner", "HDPE bedliner machinecraft"]:
        query = kw
        print(f"\n--- Searching: {query} ---")
        result = gmail_search(query, max_results=10)
        print(result[:500])

        entries = extract_ids(result)
        for e in entries:
            if e["message_id"] not in seen_ids:
                seen_ids.add(e["message_id"])
                all_entries.append(e)

        time.sleep(0.5)

    print(f"\n=== Total unique messages found: {len(all_entries)} ===")
    return all_entries


def fetch_threads(entries: list[dict]) -> dict[str, str]:
    """Fetch full thread content for each unique thread ID."""
    thread_ids = list({e["thread_id"] for e in entries if e["thread_id"]})
    print(f"\n=== Fetching {len(thread_ids)} unique threads ===")

    threads = {}
    for tid in thread_ids:
        print(f"  Fetching thread {tid}...")
        content = gmail_get_thread(tid, max_messages=30)
        threads[tid] = content
        time.sleep(0.3)

    return threads


def download_attachments(entries: list[dict]) -> list[dict]:
    """Download all attachments from found messages."""
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    all_attachments = []

    print(f"\n=== Downloading attachments from {len(entries)} messages ===")
    for e in entries:
        msg_id = e["message_id"]
        atts = gmail_get_attachments(msg_id, download_dir=str(ATTACHMENTS_DIR))
        if atts:
            for a in atts:
                a["source_message_id"] = msg_id
                a["source_subject"] = e.get("subject", "")
                a["source_date"] = e.get("date", "")
                print(f"  Downloaded: {a['filename']} ({a['size_bytes']} bytes) from '{e.get('subject', '')}'")
            all_attachments.extend(atts)
        time.sleep(0.2)

    print(f"\n=== Total attachments downloaded: {len(all_attachments)} ===")
    return all_attachments


def build_markdown_summary(entries, threads, attachments):
    """Build a markdown document with all extracted data."""
    lines = [
        "# Customer-H Automotive Bedliner Project — Email Data Extract",
        "",
        f"**Extracted:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Contacts:** {', '.join(CONTACTS)}",
        f"**Total messages found:** {len(entries)}",
        f"**Unique threads:** {len(threads)}",
        f"**Attachments downloaded:** {len(attachments)}",
        "",
        "---",
        "",
        "## Email Index",
        "",
    ]

    # Group by thread
    thread_groups: dict[str, list[dict]] = {}
    for e in entries:
        tid = e.get("thread_id", "no_thread")
        thread_groups.setdefault(tid, []).append(e)

    for i, (tid, msgs) in enumerate(thread_groups.items(), 1):
        first = msgs[0]
        lines.append(f"### Thread {i}: {first.get('subject', '(no subject)')}")
        lines.append(f"- **Thread ID:** `{tid}`")
        lines.append(f"- **Messages:** {len(msgs)}")
        lines.append(f"- **Date range:** {msgs[0].get('date', '?')} → {msgs[-1].get('date', '?')}")
        lines.append("")

        # Thread attachments
        thread_atts = [a for a in attachments if a.get("source_message_id") in {m["message_id"] for m in msgs}]
        if thread_atts:
            lines.append("**Attachments:**")
            for a in thread_atts:
                lines.append(f"- `{a['filename']}` ({a['size_bytes']:,} bytes) — {a.get('mime_type', '')}")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("## Full Thread Contents")
    lines.append("")

    for i, (tid, content) in enumerate(threads.items(), 1):
        subject_for_thread = next(
            (e["subject"] for e in entries if e.get("thread_id") == tid and e.get("subject")),
            "(unknown)"
        )
        lines.append(f"### Thread {i}: {subject_for_thread}")
        lines.append("")
        lines.append("```")
        lines.append(content)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Attachments List")
    lines.append("")
    if attachments:
        lines.append("| # | Filename | Size | Type | From Email |")
        lines.append("|---|----------|------|------|------------|")
        for j, a in enumerate(attachments, 1):
            lines.append(
                f"| {j} | `{a['filename']}` | {a['size_bytes']:,} B | {a.get('mime_type', '')} | {a.get('source_subject', '')} |"
            )
    else:
        lines.append("No attachments found.")

    lines.append("")
    return "\n".join(lines)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Customer-H Bedliner Project — Email Data Extraction")
    print("=" * 60)

    # Step 1: Search
    entries = search_all_emails()
    if not entries:
        print("No emails found. Check Gmail auth tokens.")
        return

    # Step 2: Fetch threads
    threads = fetch_threads(entries)

    # Step 3: Download attachments
    attachments = download_attachments(entries)

    # Step 4: Save structured JSON
    data = {
        "extracted_at": datetime.now().isoformat(),
        "contacts": CONTACTS,
        "messages": entries,
        "threads": {tid: content for tid, content in threads.items()},
        "attachments": [
            {k: v for k, v in a.items() if k != "path"}
            for a in attachments
        ],
    }
    json_path = OUTPUT_DIR / "email_data.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nJSON saved: {json_path}")

    # Step 5: Build markdown summary
    md = build_markdown_summary(entries, threads, attachments)
    md_path = OUTPUT_DIR / "email_extract.md"
    md_path.write_text(md)
    print(f"Markdown saved: {md_path}")

    # Step 6: Summary
    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print(f"  Messages:    {len(entries)}")
    print(f"  Threads:     {len(threads)}")
    print(f"  Attachments: {len(attachments)}")
    print(f"  Output dir:  {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
