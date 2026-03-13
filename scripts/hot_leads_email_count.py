#!/usr/bin/env python3
"""Fetch email/reply counts for hot leads via Ira API (POST /api/email/search).

Run with Ira API running: poetry run python scripts/hot_leads_email_count.py

- Us→them: search to_address=contact (emails we sent to that contact).
- Them→us: search from_address=contact (replies we received from that contact).

Requires: IRA_API_URL (default http://localhost:8000), optional API_SECRET_KEY.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Install httpx: poetry add httpx", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_URL = os.environ.get("IRA_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SECRET_KEY", "")

# Hot + frozen leads from contact context (email only)
HOT_LEAD_EMAILS = [
    "emad@naffco.com",
    "ahmed@naffco.com",
    "ksa@naffco.com",
    "pinto@forma3d.pt",
    "aguilar@bascomhunter.com",
    "virkhov@streamtechno.org",
    "ms@extalon.com",
    "c.scaramella@mininiplastic.it",
    "andreas@q-plas.co.za",
    "abhishekpkn@gmail.com",
]
FROZEN_LEAD_EMAILS = [
    "nick.mcnamara@geminimade.com",
    "annalisa.genovesi@uniroma3.it",
]


def search(to_address: str = "", from_address: str = "", max_results: int = 100) -> int:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    payload = {
        "to_address": to_address,
        "from_address": from_address,
        "max_results": max_results,
    }
    try:
        r = httpx.post(f"{API_URL}/api/email/search", json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json().get("count", 0)
    except Exception as e:
        print(f"  [error] {e}", file=sys.stderr)
        return -1


def main() -> None:
    print("Hot leads — email counts (Ira API must be running)\n")
    print(f"{'Email':<45} {'Us→them':>8} {'Them→us':>8}")
    print("-" * 65)

    for email in HOT_LEAD_EMAILS:
        sent = search(to_address=email)
        recv = search(from_address=email)
        print(f"{email:<45} {sent:>8} {recv:>8}")

    print("\nFrozen (was hot, not replying)\n")
    for email in FROZEN_LEAD_EMAILS:
        sent = search(to_address=email)
        recv = search(from_address=email)
        print(f"{email:<45} {sent:>8} {recv:>8}")

    print("\nPaste the numbers into HOT_LEADS_SUMMARY.md or use for your own tracking.")


if __name__ == "__main__":
    main()
