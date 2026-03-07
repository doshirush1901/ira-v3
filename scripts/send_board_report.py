#!/usr/bin/env python3
"""Send the board meeting report as a Gmail draft.

Deletes the stale token (wrong scopes) and re-authenticates with
compose permissions, then creates the draft.
"""

import asyncio
import base64
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPORT_PATH = Path("data/board_meetings/20260307_012540_tim_urban_report_clean.html")
TO = "rushabh@machinecraft.org"
SUBJECT = "Your AI Board of Directors Just Had Their First Meeting"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def main():
    from ira.config import get_settings

    settings = get_settings()
    token_path = Path(settings.google.token_path)
    creds_path = Path(settings.google.credentials_path)

    html_body = REPORT_PATH.read_text()

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    needs_reauth = False
    creds = None

    if token_path.exists():
        import json
        token_data = json.loads(token_path.read_text())
        existing_scopes = set(token_data.get("scopes", []))
        required_scopes = set(SCOPES)
        if not required_scopes.issubset(existing_scopes):
            print(f"Token has scopes: {existing_scopes}")
            print(f"Need scopes: {required_scopes}")
            print("Removing old token — need broader permissions...")
            token_path.unlink()
            needs_reauth = True
        else:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token and not needs_reauth:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            print("\nOpening browser for Google OAuth...")
            print("Please authorize Gmail compose access.\n")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())
        print("Token saved with compose scopes.")

    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(html_body, "html")
    msg["to"] = TO
    msg["subject"] = SUBJECT
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )

    print(f"\nGmail draft created successfully!")
    print(f"Draft ID: {draft.get('id')}")
    print(f"To: {TO}")
    print(f"Subject: {SUBJECT}")
    print(f"\nCheck your Gmail drafts folder and hit send!")


if __name__ == "__main__":
    main()
