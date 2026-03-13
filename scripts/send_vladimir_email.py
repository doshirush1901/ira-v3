#!/usr/bin/env python3
"""Send or create draft for the Vladimir Komplektant email via Ira API.

Usage:
  python3 scripts/send_vladimir_email.py           # Send (requires IRA_EMAIL_MODE=OPERATIONAL)
  python3 scripts/send_vladimir_email.py --draft   # Create Gmail draft so you can send from your mailbox
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
body_path = PROJECT_ROOT / "data/imports/24_WebSite_Leads/email_vladimir_kilunin_FINAL_RUSHABH_VOICE.md"

content = body_path.read_text(encoding="utf-8")
# Body from "Hi Vladimir," through "www.machinecraft.in"
start = content.find("Hi Vladimir,")
end = content.find("www.machinecraft.in") + len("www.machinecraft.in")
body = content[start:end].strip()

payload = {
    "to": "kiluninv@gmail.com",
    "subject": "PF1-X-2012 Thermoforming for Komplektant — Sanitary-Ware Specs, Price & References",
    "body": body,
    "cc": "sales@machinecraft.org",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Send or draft Vladimir email via Ira API")
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create a Gmail draft instead of sending (open Gmail and send from your mailbox)",
    )
    args = parser.parse_args()

    endpoint = "http://localhost:8000/api/email/create-draft" if args.draft else "http://localhost:8000/api/email/send"

    import urllib.request

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read().decode())
            print(json.dumps(out, indent=2))
            if args.draft:
                print("Draft created in your Gmail. Open Gmail → Drafts and send from your mailbox.")
            else:
                print("Email sent.")
    except urllib.error.HTTPError as e:
        print("HTTP error:", e.code, e.reason)
        print(e.read().decode())
        sys.exit(1)
    except OSError as e:
        print("Request failed (is Ira API running?):", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
