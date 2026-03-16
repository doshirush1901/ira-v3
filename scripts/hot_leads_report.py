#!/usr/bin/env python3
"""Print top 50 hot leads (by lead score) with last email sent, machine proposed, quote value, etc.

Requires Ira API running. Output: Markdown table to stdout (or JSON with --json).

Usage:
  poetry run python scripts/hot_leads_report.py
  poetry run python scripts/hot_leads_report.py --json
  poetry run python scripts/hot_leads_report.py --limit 20
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    httpx = None

API_URL = os.environ.get("IRA_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SECRET_KEY", "")


def _load_env() -> None:
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "API_SECRET_KEY":
                globals()["API_KEY"] = v
            elif k == "IRA_API_URL":
                globals()["API_URL"] = v.strip()


def main() -> None:
    import argparse
    _load_env()
    parser = argparse.ArgumentParser(description="Top 50 hot leads with last email, machine, quote value.")
    parser.add_argument("--limit", type=int, default=50, help="Number of leads (default 50).")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown.")
    args = parser.parse_args()

    if not httpx:
        print("Install httpx: poetry add httpx", file=sys.stderr)
        sys.exit(1)

    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        r = httpx.get(
            f"{API_URL}/api/deals/ranked",
            params={"limit": args.limit, "sort_by_score": "desc"},
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)

    deals = data.get("deals") or []

    if args.json:
        print(json.dumps({"deals": deals, "count": len(deals)}, indent=2))
        return

    # Markdown table
    print("# Top 50 hot leads (hottest to least)\n")
    print("| # | Company | Contact | Score | Stage | Machine | Quote value | Last email sent | Subject / preview |")
    print("|---|---------|---------|-------|-------|---------|-------------|-----------------|-------------------|")
    for i, d in enumerate(deals, 1):
        company = (d.get("company_name") or "—")[:30]
        contact = (d.get("contact_name") or d.get("contact_email") or "—")[:25]
        score = d.get("lead_score") or 0
        stage = (d.get("stage") or "—")[:12]
        machine = (d.get("machine_model") or "—")[:20]
        val = d.get("value")
        curr = (d.get("currency") or "USD")[:3]
        quote_val = f"{val:,.0f} {curr}" if val is not None and val else "—"
        last_at = (d.get("last_email_sent_at") or "—")[:10] if d.get("last_email_sent_at") else "—"
        subj = (d.get("last_email_subject") or d.get("last_email_preview") or "—")
        subj = subj.replace("|", " ").replace("\n", " ").strip()[:45]
        print(f"| {i} | {company} | {contact} | {score} | {stage} | {machine} | {quote_val} | {last_at} | {subj} |")
    print(f"\n*Total: {len(deals)} deals. Lead score = order size + interest + stage + existing customer + meeting (see data/knowledge/lead_ranker_formula.md).*")


if __name__ == "__main__":
    main()
