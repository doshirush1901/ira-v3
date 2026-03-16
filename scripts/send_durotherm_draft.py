#!/usr/bin/env python3
"""Send Durotherm draft as a new email thread. Requires API server running and IRA_EMAIL_MODE=OPERATIONAL for send."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

DRAFT_PATH = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "draft_email_durotherm.md"
API_URL = "http://localhost:8000/api/email/send"

SUBJECT = "Reconnecting — how are you? (and a few things that might be useful)"
TO = "pavel.votruba@durotherm.cz"


def extract_body(content: str) -> str:
    start = content.find("## Email body (plain text)")
    if start == -1:
        start = content.find("## Email body")
    if start == -1:
        raise ValueError("Email body section not found")
    start = content.index("\n", start) + 1
    end = content.find("\n---\n", start)
    if end == -1:
        end = content.find("\n## Checklist", start)
    if end == -1:
        end = len(content)
    body = content[start:end].strip()
    body = re.sub(r"\r\n?", "\n", body)
    return body


def main() -> int:
    text = DRAFT_PATH.read_text(encoding="utf-8")
    body = extract_body(text)
    payload = {
        "to": TO,
        "subject": SUBJECT,
        "body": body,
    }
    try:
        r = httpx.post(API_URL, json=payload, timeout=30.0)
        r.raise_for_status()
        out = r.json()
        print("Sent successfully.")
        print("  message_id:", out.get("message_id"))
        print("  thread_id:", out.get("thread_id"))
        print("  sent_from:", out.get("sent_from"))
        return 0
    except httpx.HTTPStatusError as e:
        print("Send failed:", e.response.status_code, e.response.text, file=sys.stderr)
        return 1
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
