#!/usr/bin/env python3
"""Scan sent emails (last 4 months) for customers we sent proposals/quotes to.

Uses POST /api/email/search with from_address = our send address so we get
emails WE sent. Filters by date and by query (quote, proposal, machine terms).
Output: list of recipients (to) with subject and date.

Usage:
  # 1. Start Ira API (so Gmail can be used)
  uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000

  # 2. Run script (scans last 4 months of SENT mail from rushabh@machinecraft.org)
  poetry run python scripts/scan_sent_proposals_quotes.py
  poetry run python scripts/scan_sent_proposals_quotes.py --output data/reports/sent_proposals_4months.json

  # CSV export (same data, spreadsheet-friendly)
  poetry run python scripts/scan_sent_proposals_quotes.py --output data/reports/sent_proposals_4months.csv
  poetry run python scripts/scan_sent_proposals_quotes.py --csv data/reports/sent_proposals_4months.csv

  # Optional: change lookback or sender
  poetry run python scripts/scan_sent_proposals_quotes.py --months 6 --from-address rushabh@machinecraft.org
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

API_BASE = "http://localhost:8000"
# Default: emails sent FROM this address (our sent folder)
FROM_ADDRESS = "rushabh@machinecraft.org"
# Gmail query to narrow to proposal/quote-like emails (machine terms + commercial)
QUERY = "quote OR proposal OR offer OR machine OR PF1 OR FCS OR thermoform OR ex-works OR INR OR EUR OR Lakhs OR Crore"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan sent emails for proposals/quotes (last 4 months)")
    parser.add_argument("--output", "-o", type=str, default="", help="Write report to this path (.json or .csv)")
    parser.add_argument("--csv", type=str, default="", help="Write CSV to this path (alternative to --output)")
    parser.add_argument("--from-address", type=str, default=FROM_ADDRESS, help="Sender email (our sent mail)")
    parser.add_argument("--months", type=int, default=4, help="Look back N months")
    parser.add_argument("--max-results", type=int, default=200, help="Max emails to fetch")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    after_date = today - timedelta(days=args.months * 31)
    after_str = after_date.strftime("%Y/%m/%d")
    before_str = today.strftime("%Y/%m/%d")

    if not httpx:
        print("httpx required: pip install httpx")
        sys.exit(1)

    payload = {
        "from_address": args.from_address,
        "to_address": "",
        "subject": "",
        "query": QUERY,
        "after": after_str,
        "before": before_str,
        "max_results": args.max_results,
    }

    try:
        r = httpx.post(
            f"{API_BASE}/api/email/search",
            json=payload,
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.ConnectError as e:
        print(f"Could not connect to API at {API_BASE}. Start the server (e.g. uvicorn ira.interfaces.server:app).")
        print(f"Error: {e}")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"API error: {e.response.status_code} {e.response.text}")
        sys.exit(1)

    emails = data.get("emails") or []
    count = data.get("count", len(emails))

    # Build list of unique recipients with latest subject and date
    by_to: dict[str, list[dict]] = {}
    for e in emails:
        to_addr = (e.get("to") or "").strip().lower()
        if not to_addr or "@" not in to_addr:
            continue
        subj = (e.get("subject") or "").strip()
        date = (e.get("date") or "")[:10]
        by_to.setdefault(to_addr, []).append({"subject": subj, "date": date})

    # Sort by most recent email per recipient
    report = []
    for to_addr, items in sorted(by_to.items(), key=lambda x: max(x[1], key=lambda i: i["date"])["date"], reverse=True):
        latest = max(items, key=lambda i: i["date"])
        report.append({
            "to": to_addr,
            "subject": latest["subject"],
            "date": latest["date"],
            "sent_count": len(items),
        })

    summary = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "from_address": args.from_address,
        "after": after_str,
        "before": before_str,
        "query_used": QUERY,
        "total_emails_matched": count,
        "unique_recipients": len(report),
        "recipients": report,
    }

    print(f"Sent proposals/quotes (last {args.months} months): {len(report)} unique recipients, {count} emails matched")
    print()
    for i, row in enumerate(report[:80], 1):
        print(f"  {i}. {row['to']}")
        print(f"     Subject: {row['subject'][:70]}{'...' if len(row['subject'])>70 else ''}")
        print(f"     Date: {row['date']}  (sent {row['sent_count']} time(s))")
        print()
    if len(report) > 80:
        print(f"  ... and {len(report) - 80} more (see JSON output)")

    # Write output: JSON and/or CSV
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if str(out_path).lower().endswith(".csv"):
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["to", "subject", "date", "sent_count"])
                for row in report:
                    w.writerow([row["to"], row["subject"], row["date"], row["sent_count"]])
            print(f"\nCSV written to {out_path}")
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            print(f"\nReport written to {out_path}")
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["to", "subject", "date", "sent_count"])
            for row in report:
                w.writerow([row["to"], row["subject"], row["date"], row["sent_count"]])
        print(f"\nCSV written to {csv_path}")


if __name__ == "__main__":
    main()
