#!/usr/bin/env python3
"""Send Lead 45 (Frank Cristiano, Tricomposite Pty Ltd) email as new message."""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TO_SEND = PROJECT_ROOT / "data/imports/24_WebSite_Leads/email_lead45_frank_cristiano_TO_SEND.md"

SUBJECT_NEW = "Tricomposite — catching up (and has the capex picture changed?)"
TO_EMAIL = "frank.cristiano@tricomposite.com.au"


def extract_body(text: str) -> str:
    start = text.find("Hi Frank,")
    if start == -1:
        return text
    rest = text[start:]
    end = rest.rfind("www.machinecraft.org")
    if end != -1:
        rest = rest[: end + len("www.machinecraft.org")]
    rest = re.sub(r"\*\*([^*]+)\*\*", r"\1", rest)
    return rest.strip()


def main() -> None:
    import httpx

    if not TO_SEND.exists():
        print(f"Missing {TO_SEND}", file=sys.stderr)
        sys.exit(1)
    raw = TO_SEND.read_text(encoding="utf-8")
    body = extract_body(raw)
    url = "http://localhost:8000/api/email/send"
    payload = {"to": TO_EMAIL, "subject": SUBJECT_NEW, "body": body}
    try:
        r = httpx.post(url, json=payload, timeout=30.0)
        r.raise_for_status()
        out = r.json()
        print("Sent:", out.get("message_id"), "thread:", out.get("thread_id"), "from", out.get("sent_from"))
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
