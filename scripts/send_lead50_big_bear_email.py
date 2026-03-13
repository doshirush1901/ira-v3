#!/usr/bin/env python3
"""Send Lead 50 (Big Bear) to up to 3 contacts at the company.

Steve Church has left; we search the mailbox for current contacts (e.g. Emma + others)
and send to all so if one fails, others get it.

Usage:
  poetry run python scripts/send_lead50_big_bear_email.py

Requires: Ira API running. TO_SEND file with body (create draft first if missing).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TO_SEND = PROJECT_ROOT / "data/imports/24_WebSite_Leads/email_lead50_big_bear_TO_SEND.md"

SUBJECT = "Big Bear — catching up on your 3×5 m thermoforming idea (and a UK reference)"


def find_contacts(company: str, domain: str | None = None, max_contacts: int = 3) -> list[str]:
    """Run find_company_contacts script and return list of emails."""
    script = PROJECT_ROOT / "scripts" / "find_company_contacts.py"
    cmd = [
        sys.executable,
        str(script),
        company,
        "--max",
        str(max_contacts),
        "--search-max",
        "50",
    ]
    if domain:
        cmd.extend(["--domain", domain])
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip() and "@" in line]


def extract_body(text: str) -> str:
    """Strip metadata and normalize body for plain-text send."""
    # Start after first Hi / Dear
    for start in ("Hi all,", "Hi team,", "Hi "):
        idx = text.find(start)
        if idx != -1:
            text = text[idx:]
            break
    # End at signature / URL
    end = text.rfind("www.machinecraft.org")
    if end != -1:
        text = text[: end + len("www.machinecraft.org")]
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def main() -> None:
    if not TO_SEND.exists():
        print(f"Missing {TO_SEND}. Create the draft first (full workflow for Lead 50).", file=sys.stderr)
        sys.exit(1)

    contacts = find_contacts("Big Bear", domain="big-bear.co.uk")
    if not contacts:
        # Fallback: try without domain filter
        contacts = find_contacts("Big Bear")
    if not contacts:
        print("No contacts found for Big Bear. Run: poetry run python scripts/find_company_contacts.py \"Big Bear\"", file=sys.stderr)
        sys.exit(1)

    to_email = contacts[0]
    cc_emails = contacts[1:3]  # up to 2 more
    cc_str = ", ".join(cc_emails) if cc_emails else None

    raw = TO_SEND.read_text(encoding="utf-8")
    body = extract_body(raw)

    url = "http://localhost:8000/api/email/send"
    payload = {"to": to_email, "subject": SUBJECT, "body": body}
    if cc_str:
        payload["cc"] = cc_str

    try:
        r = httpx.post(url, json=payload, timeout=30.0)
        r.raise_for_status()
        out = r.json()
        print("Sent:", out.get("message_id"), "thread:", out.get("thread_id"))
        print("To:", to_email, "Cc:", cc_str or "(none)")
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
