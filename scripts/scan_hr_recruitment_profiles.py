#!/usr/bin/env python3
"""
Scan Gmail for job applicants in the HR / Recruitment CVs folder.

Searches by Gmail label (e.g. "HR", "Recruitment CVs", or "HR, Recruitment CVs"),
optionally restricting to emails with attachments (CVs). Outputs a table of
applicant threads: from, subject, date, thread_id.

Usage:
  # With API server running (default label: HR)
  poetry run python scripts/scan_hr_recruitment_profiles.py

  # Custom label (use exact Gmail label name; spaces allowed)
  poetry run python scripts/scan_hr_recruitment_profiles.py --label "Recruitment CVs"

  # Only emails with attachments (likely CVs)
  poetry run python scripts/scan_hr_recruitment_profiles.py --label "HR" --has-attachment

  # Limit and date range
  poetry run python scripts/scan_hr_recruitment_profiles.py --label "HR" --max 50 --after 2024/01/01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan Gmail HR/Recruitment label for job applicant emails (profiles)."
    )
    parser.add_argument(
        "--label",
        default="HR",
        help='Gmail label/folder name (e.g. "HR", "Recruitment CVs"). Use exact name as in Gmail. Default: HR',
    )
    parser.add_argument(
        "--subject",
        default="",
        help="Filter by subject keyword (e.g. 'application', 'CV', 'resume', 'Plant Manager').",
    )
    parser.add_argument(
        "--has-attachment",
        action="store_true",
        help="Restrict to emails that have attachments (likely CVs).",
    )
    parser.add_argument(
        "--after",
        default="",
        help="Only emails after this date (YYYY/MM/DD).",
    )
    parser.add_argument(
        "--before",
        default="",
        help="Only emails before this date (YYYY/MM/DD).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=30,
        help="Max number of emails to return (default 30).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("IRA_API_BASE_URL", "http://localhost:8000"),
        help="API base URL (default from IRA_API_BASE_URL or http://localhost:8000).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of a markdown table.",
    )
    args = parser.parse_args()

    query = "has:attachment" if args.has_attachment else ""
    payload = {
        "label": args.label,
        "subject": args.subject,
        "query": query,
        "after": args.after,
        "before": args.before,
        "max_results": args.max,
    }

    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"{args.base_url.rstrip('/')}/api/email/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"API error {e.code}: {body}", file=sys.stderr)
        return 1
    except OSError as e:
        print(
            f"Cannot reach API at {args.base_url}. Start the server with:\n"
            "  poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000",
            file=sys.stderr,
        )
        print(f"Error: {e}", file=sys.stderr)
        return 1

    emails = data.get("emails", [])
    count = data.get("count", 0)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0

    if not emails:
        print(f"No emails found in label '{args.label}'.")
        if query:
            print(f"  (query: {query})")
        return 0

    print(f"**Applicant threads in label '{args.label}'** ({count} emails)\n")
    print("| Date | From | Subject | Thread ID |")
    print("|------|------|---------|-----------|")
    for e in emails:
        date = e.get("date", "")[:10] if e.get("date") else ""
        from_addr = e.get("from", "")
        subject = (e.get("subject", "") or "")[:60]
        if len(e.get("subject", "") or "") > 60:
            subject += "..."
        thread_id = e.get("thread_id", "")
        print(f"| {date} | {from_addr} | {subject} | {thread_id} |")

    print(f"\nUse thread_id with: GET /api/email/thread/{{thread_id}} or Ira: read_email_thread(thread_id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
