#!/usr/bin/env python3
"""Draft a lead engagement email with full context: recalled memory + contact history file.

Uses all relevant inputs for a data-driven, beautiful draft:
- GET /api/memory/recall (Mem0) for the contact
- Optional contact history MD from pull_contact_email_history.py (logic tree + recap)
- POST /api/email/draft with instructions to apply email_final_format_style + Rushabh voice

Usage:
  poetry run python scripts/draft_lead_email_enriched.py --to pinto@forma3d.pt --subject "Forma 3D — quick catch-up"
  poetry run python scripts/draft_lead_email_enriched.py --to pinto@forma3d.pt --history-file data/imports/24_WebSite_Leads/eduardo_forma3d_email_history.md --name "Eduardo Pinto"

Requires: Ira API running. MEM0_API_KEY for recall.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"


def recall_memory(contact_email: str, limit: int = 5) -> list[str]:
    """Recall memories for this contact (user_id=email) and a generic query."""
    try:
        r = httpx.get(
            f"{BASE}/api/memory/recall",
            params={
                "query": f"contact {contact_email} past interactions proposals feedback",
                "user_id": contact_email,
                "limit": limit,
            },
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json().get("memories", [])
    except Exception:
        return []


def build_context(
    contact_email: str,
    contact_name: str | None,
    history_path: Path | None,
    memories: list[str],
    news_hook: str | None = None,
    quote_block: str | None = None,
    long_and_warm: bool = False,
) -> str:
    """Assemble the draft context so Calliope produces an organised, data-driven email."""
    parts = [
        "You are drafting a single outbound email to this lead. Apply BOTH:",
        "1. prompts/email_rushabh_voice_brand.txt — Rushabh's voice, 'I' not 'we', short paragraphs, one CTA, sign-off Best regards, Rushabh Doshi, Director — Machinecraft, rushabh@machinecraft.org, www.machinecraft.org.",
        "2. prompts/email_final_format_style.txt — Structure: greeting → OPENING HOOK (news or personal) → CONTEXT/RECAP (past interactions in prose, MBB-style) → KEY DATA BLOCK (e.g. latest quote) → one CTA → sign-off. Use double line breaks between sections. Use section labels (e.g. WHERE WE LEFT OFF — or LATEST QUOTE WE SENT YOU —). Data-driven; professional, warm, human; MBB-style. No pipe tables; use bullets.",
        "",
        "Recipient: " + contact_email,
    ]
    if contact_name:
        parts.append(f"Contact name: {contact_name}")
    parts.append("")

    if news_hook:
        parts.append("--- OPENING NEWS HOOK (use this in the first 1–2 sentences; weave in naturally) ---")
        parts.append(news_hook)
        parts.append("")

    if memories:
        parts.append("--- RECALLED MEMORIES (use to personalise and avoid repeating) ---")
        for m in memories:
            parts.append(f"- {m}")
        parts.append("")

    if history_path and history_path.exists():
        parts.append("--- CONTACT HISTORY (logic tree + recap; use for context and MBB-style recap in prose) ---")
        parts.append(history_path.read_text(encoding="utf-8"))
        parts.append("")

    if quote_block:
        parts.append("--- LATEST QUOTE WE SENT (include this block in the email under a label like LATEST QUOTE WE SENT YOU —) ---")
        parts.append(quote_block)
        parts.append("")

    parts.append("--- INSTRUCTIONS ---")
    parts.append("Produce the email body only (no Subject: line in the body). Use the recalled memories and contact history to make the email specific and data-driven. If there is a Recap summary in the contact history, use it for the context/recap section. Keep the email scannable and professionally formatted.")
    if long_and_warm:
        parts.append("Make the email LONGER and WARMER: include a proper opening hook, a full MBB-style recap of past interactions in prose (2–4 sentences), the quote block, and a warm closing. No placeholder text; write a complete, send-ready email.")

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft lead email with memory + contact history")
    parser.add_argument("--to", required=True, help="Recipient email")
    parser.add_argument("--subject", default="", help="Subject line (optional; can be refined in draft)")
    parser.add_argument("--history-file", type=Path, help="Path to contact history MD from pull_contact_email_history.py")
    parser.add_argument("--name", help="Contact name (e.g. Eduardo Pinto)")
    parser.add_argument("--news-hook", default="", help="Opening news hook (e.g. Portugal packaging headline); weave into first 1-2 sentences")
    parser.add_argument("--quote-block", default="", help="Latest quote block (machines/prices) to include under LATEST QUOTE WE SENT YOU")
    parser.add_argument("--quote-file", type=Path, help="Read quote block from file (e.g. quote_summary.md or 3-line block)")
    parser.add_argument("--long-warm", action="store_true", help="Request longer, warmer email with full MBB-style recap and section labels")
    parser.add_argument("--no-recall", action="store_true", help="Skip memory recall")
    parser.add_argument("--out", type=Path, help="Write draft to this file (default: print)")
    args = parser.parse_args()

    if args.history_file and not args.history_file.is_absolute():
        args.history_file = PROJECT_ROOT / args.history_file
    if args.quote_file and not args.quote_file.is_absolute():
        args.quote_file = PROJECT_ROOT / args.quote_file

    quote_block = args.quote_block
    if not quote_block and args.quote_file and args.quote_file.exists():
        quote_block = args.quote_file.read_text(encoding="utf-8")

    memories = [] if args.no_recall else recall_memory(args.to)
    context = build_context(
        args.to,
        args.name,
        args.history_file,
        memories,
        news_hook=args.news_hook or None,
        quote_block=quote_block or None,
        long_and_warm=args.long_warm,
    )

    try:
        r = httpx.post(
            f"{BASE}/api/email/draft",
            json={
                "to": args.to,
                "subject": args.subject or "Following up",
                "context": context,
                "tone": "professional",
            },
            timeout=60.0,
        )
        r.raise_for_status()
        out = r.json()
        body = out.get("body", "")
        subject = out.get("subject", args.subject or "Following up")
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        return 1
    except Exception as e:
        print(e, file=sys.stderr)
        return 1

    draft = f"Subject: {subject}\n\n{body}"
    if args.out:
        out_path = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
        out_path.write_text(draft, encoding="utf-8")
        print(f"Wrote draft to {out_path}")
    else:
        print(draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
