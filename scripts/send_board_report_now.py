#!/usr/bin/env python3
"""Send the board meeting report email directly (not as draft)."""

import base64
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPORT_PATH = Path("data/board_meetings/20260307_012540_tim_urban_report_clean.html")
TO = os.environ.get("BOARD_RECIPIENT", "founder@example.com")
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

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())

    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(html_body, "html")
    msg["to"] = TO
    msg["subject"] = SUBJECT
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    result = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )

    print(f"Email SENT successfully!")
    print(f"Message ID: {result.get('id')}")
    print(f"To: {TO}")
    print(f"Subject: {SUBJECT}")


if __name__ == "__main__":
    main()
