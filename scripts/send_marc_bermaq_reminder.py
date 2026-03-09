#!/usr/bin/env python3
"""
Send the reminder email to Marc (Bermaq) with offer summary.

Draft is in data/summaries/draft_email_marc_bermaq_reminder.txt.
Run after reviewing the draft. Uses Rushabh's Gmail (token.json).

Usage:
    python3 scripts/send_marc_bermaq_reminder.py          # dry run, print draft
    python3 scripts/send_marc_bermaq_reminder.py --send   # actually send
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DRAFT_PATH = PROJECT_ROOT / "data" / "summaries" / "draft_email_marc_bermaq_reminder.txt"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Actually send the email (default: dry run)")
    args = parser.parse_args()

    if not DRAFT_PATH.exists():
        print(f"Draft not found: {DRAFT_PATH}")
        sys.exit(1)

    text = DRAFT_PATH.read_text(encoding="utf-8").strip()
    lines = text.split("\n")
    to = ""
    subject = ""
    body_lines = []
    for line in lines:
        if line.startswith("To:"):
            to = line.replace("To:", "").strip()
        elif line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()

    if not to or not subject:
        print("Draft must have To: and Subject: lines")
        sys.exit(1)

    print("To:", to)
    print("Subject:", subject)
    print("\n--- Body ---\n")
    print(body)
    print("\n--- End ---\n")

    if not args.send:
        print("Dry run. To send, run: python3 scripts/send_marc_bermaq_reminder.py --send")
        return

    # Load google_tools and send
    import importlib.util
    gt_path = PROJECT_ROOT / "openclaw" / "agents" / "ira" / "src" / "tools" / "google_tools.py"
    spec = importlib.util.spec_from_file_location("google_tools", gt_path)
    google_tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(google_tools)
    result = google_tools.gmail_send(to=to, subject=subject, body=body)
    print(result)


if __name__ == "__main__":
    main()
