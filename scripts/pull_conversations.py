#!/usr/bin/env python3
"""
Pull past conversations for a contact (CRM + Gmail).
Usage:
  python scripts/pull_conversations.py kasperovich@allcomp.com.ua
  python scripts/pull_conversations.py someone@example.com --gmail-only
"""

import argparse
import base64
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "openclaw/agents/ira/src/crm"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_gmail_service():
    """Minimal Gmail API client (no Ira agent imports)."""
    token_file = PROJECT_ROOT / "token.json"
    creds_file = PROJECT_ROOT / "credentials.json"
    if not token_file.exists() or not creds_file.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json())
        return build("gmail", "v1", credentials=creds)
    except Exception:
        return None


def _extract_body(payload):
    if not payload:
        return ""
    if payload.get("body", {}).get("data"):
        try:
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        except Exception:
            pass
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            try:
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
            except Exception:
                pass
        if "parts" in part:
            out = _extract_body(part)
            if out:
                return out
    return ""


def main():
    parser = argparse.ArgumentParser(description="Pull past conversations for a contact")
    parser.add_argument("email", help="Contact email (e.g. kasperovich@allcomp.com.ua)")
    parser.add_argument("--crm-only", action="store_true", help="Only show CRM data")
    parser.add_argument("--gmail-only", action="store_true", help="Only show Gmail threads")
    parser.add_argument("--gmail-limit", type=int, default=30, help="Max Gmail messages to fetch (default 30)")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if not email or "@" not in email:
        print("Invalid email.")
        sys.exit(1)

    out_lines = [f"\n{'='*60}", f"Conversations: {email}", "="*60]

    # --- CRM ---
    if not args.gmail_only:
        crm_db = PROJECT_ROOT / "crm" / "ira_crm.db"
        if crm_db.exists():
            try:
                from ira_crm import get_crm
                crm = get_crm()
                # Contact
                contact = crm.get_contact(email)
                if contact:
                    out_lines.append("\n[CRM CONTACT]")
                    out_lines.append(f"  Name: {getattr(contact, 'name', '') or '-'}")
                    out_lines.append(f"  Company: {getattr(contact, 'company', '') or '-'}")
                    out_lines.append(f"  Country: {getattr(contact, 'country', '') or '-'}")
                # Conversation context
                convos = crm.get_conversation_context(email, limit=50)
                if convos:
                    out_lines.append(f"\n[CRM CONVERSATIONS] ({len(convos)} entries)")
                    for c in convos:
                        direction = "SENT" if c.direction == "outbound" else "RECEIVED"
                        date = (c.date or "")[:19] if c.date else "-"
                        subj = (c.subject or "(no subject)")[:60]
                        preview = (c.preview or "")[:200].replace("\n", " ")
                        out_lines.append(f"  [{date}] {direction}: {subj}")
                        if preview:
                            out_lines.append(f"    {preview}")
                else:
                    out_lines.append("\n[CRM CONVERSATIONS] (none)")
                # Unified timeline (email_log + conversations + deal_events)
                activity = crm.get_recent_activity(email, limit=25)
                if activity:
                    out_lines.append(f"\n[CRM RECENT ACTIVITY] ({len(activity)} events)")
                    for a in activity:
                        ts = (a.get("ts") or "")[:19]
                        src = a.get("source", "")
                        direction = a.get("direction", "")
                        subj = (a.get("subject") or a.get("detail") or "")[:80]
                        out_lines.append(f"  [{ts}] {src} {direction}: {subj}")
            except Exception as e:
                out_lines.append(f"\n[CRM ERROR] {e}")
        else:
            out_lines.append(f"\n[CRM] Database not found at {crm_db}")

    # --- Gmail ---
    if not args.crm_only:
        try:
            service = _get_gmail_service()
            if not service:
                out_lines.append("\n[GMAIL] Not available (token.json / credentials.json).")
            else:
                query = f"(from:{email} OR to:{email})"
                results = service.users().messages().list(
                    userId="me", q=query, maxResults=min(args.gmail_limit, 50)
                ).execute()
                messages = results.get("messages", [])
                if not messages:
                    out_lines.append("\n[GMAIL] No messages found.")
                else:
                    out_lines.append(f"\n[GMAIL] Found {len(messages)} messages (showing up to {args.gmail_limit})")
                    details_list = []
                    for m in messages[: args.gmail_limit]:
                        try:
                            msg = service.users().messages().get(
                                userId="me", id=m["id"], format="full"
                            ).execute()
                            payload = msg.get("payload", {})
                            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                            body = _extract_body(payload)
                            details_list.append({
                                "from": headers.get("from", ""),
                                "to": headers.get("to", ""),
                                "subject": headers.get("subject", ""),
                                "date": headers.get("date", ""),
                                "body": body,
                                "snippet": msg.get("snippet", ""),
                            })
                        except Exception:
                            continue
                    # Sort by date
                    def date_key(x):
                        try:
                            from email.utils import parsedate_to_datetime
                            return parsedate_to_datetime(x.get("date") or "").timestamp()
                        except Exception:
                            return 0
                    details_list.sort(key=date_key)
                    for d in details_list:
                        from_addr = d.get("from", "")
                        to_addr = d.get("to", "")
                        is_from_contact = email in (from_addr or "").lower()
                        direction = "RECEIVED" if is_from_contact else "SENT"
                        date_str = (d.get("date") or "")[:30]
                        subj = (d.get("subject") or "(no subject)")[:70]
                        body = (d.get("body") or d.get("snippet") or "")[:400].replace("\n", " ")
                        out_lines.append(f"\n  --- {date_str} | {direction} ---")
                        out_lines.append(f"  From: {from_addr}")
                        out_lines.append(f"  To: {to_addr}")
                        out_lines.append(f"  Subject: {subj}")
                        if body:
                            out_lines.append(f"  {body}")
        except Exception as e:
            out_lines.append(f"\n[GMAIL ERROR] {e}")

    out_lines.append("\n" + "="*60)
    print("\n".join(out_lines))


if __name__ == "__main__":
    main()
