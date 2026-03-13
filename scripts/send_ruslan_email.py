#!/usr/bin/env python3
"""Send the Ruslan (lead 2) engagement email from rushabh@machinecraft.org.

Reads body and subject from data/imports/24_WebSite_Leads/email_lead2_ruslan_didenko_TO_SEND.md
and POSTs to /api/email/send. Requires Ira API running and Gmail token for rushabh@machinecraft.org.

  poetry run python scripts/send_ruslan_email.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TO_SEND = PROJECT_ROOT / "data/imports/24_WebSite_Leads/email_lead2_ruslan_didenko_TO_SEND.md"


def extract_body(text: str) -> str:
    """From first 'Hi Ruslan,' through 'www.machinecraft.org' (inclusive). Strip metadata."""
    start = text.find("Hi Ruslan,")
    if start == -1:
        start = text.find("Subject:")
        if start != -1:
            start = text.find("\n\n", start) + 2
    if start == -1:
        return text
    rest = text[start:]
    end_marker = "www.machinecraft.org"
    end = rest.rfind(end_marker)
    if end != -1:
        rest = rest[: end + len(end_marker)]
    # Plain-text: remove markdown bold
    rest = re.sub(r"\*\*([^*]+)\*\*", r"\1", rest)
    return rest.strip()


def extract_subject(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Subject:"):
            return line.replace("Subject:", "").strip()
    return "Your PF1 2000×2000 inquiry — EU references, Dutch Tides, and a quick catch-up"


def main() -> None:
    import httpx

    if not TO_SEND.exists():
        print(f"Missing {TO_SEND}", file=sys.stderr)
        sys.exit(1)
    raw = TO_SEND.read_text(encoding="utf-8")
    subject = extract_subject(raw)
    body = extract_body(raw)
    to = "ruslan.didenko@safariotomotiv.com"

    url = "http://localhost:8000/api/email/send"
    payload = {"to": to, "subject": subject, "body": body}
    try:
        r = httpx.post(url, json=payload, timeout=30.0)
        r.raise_for_status()
        out = r.json()
        print("Sent:", out.get("message_id"), "from", out.get("sent_from"))
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
