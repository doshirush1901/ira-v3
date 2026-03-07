"""Email processor — Gmail inbox observation and analysis pipeline.

Supports two modes controlled by the ``IRA_EMAIL_MODE`` environment variable:

* **TRAINING** (default): Read-only observation of the training email address.
  Fetches sent and received emails, classifies them via Delphi, digests them
  through the DigestiveSystem, resolves sender identity, and logs interactions
  in the CRM.  **Never** sends, drafts, or modifies emails.

* **OPERATIONAL**: Active processing of ``ira@machinecraft.org``.  Fetches
  unread emails, runs the full analysis pipeline, generates reply drafts via
  Pantheon agents for actionable intents, saves drafts to Gmail, sends a
  Telegram notification, and marks originals as read.  Human-in-the-loop:
  drafts must be manually reviewed and sent.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ira.config import EmailMode, get_settings
from ira.data.models import Channel, Direction, Email
from ira.exceptions import DatabaseError, IraError, LLMError, ToolExecutionError

logger = logging.getLogger(__name__)

_TRAINING_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_OPERATIONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]

_REPLY_INTENTS = frozenset({
    "QUOTE_REQUEST", "SUPPORT", "GENERAL_INQUIRY",
    "PARTNERSHIP", "COMPLAINT", "FOLLOW_UP",
})


class EmailProcessor:
    """Gmail inbox observer with a full classification/ingestion pipeline."""

    def __init__(
        self,
        delphi: Any,
        digestive: Any,
        sensory: Any,
        crm: Any,
        *,
        pantheon: Any = None,
        unified_context: Any = None,
        settings: Any | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._google = cfg.google
        self._mode = self._google.email_mode

        self._delphi = delphi
        self._digestive = digestive
        self._sensory = sensory
        self._crm = crm
        self._pantheon = pantheon
        self._unified_ctx = unified_context
        self._service: Any | None = None

        if self._mode is EmailMode.OPERATIONAL:
            self._operational_email = self._google.ira_email
            logger.info(
                "EmailProcessor initialised in OPERATIONAL mode for %s",
                self._operational_email,
            )
        else:
            assert self._mode is EmailMode.TRAINING, (
                f"Unknown email mode: {self._mode}"
            )
            self._training_email = self._google.training_email
            logger.info(
                "EmailProcessor initialised in TRAINING mode for %s",
                self._training_email,
            )

    # ── Gmail authentication ──────────────────────────────────────────────

    async def _build_gmail_service(self) -> Any:
        """Authenticate with Gmail API and cache the service."""
        if self._service is not None:
            return self._service

        scopes = (
            _OPERATIONAL_SCOPES
            if self._mode is EmailMode.OPERATIONAL
            else _TRAINING_SCOPES
        )

        creds_path = Path(self._google.credentials_path)
        token_path = Path(self._google.token_path)

        def _authenticate() -> Any:
            creds: Credentials | None = None

            if token_path.exists():
                creds = Credentials.from_authorized_user_file(
                    str(token_path), scopes,
                )

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), scopes,
                )
                creds = flow.run_local_server(port=0)

            token_path.write_text(creds.to_json())
            return build("gmail", "v1", credentials=creds)

        self._service = await asyncio.to_thread(_authenticate)
        logger.info("Gmail service built (mode=%s)", self._mode.value)
        return self._service

    # ── Inbox observation (TRAINING) ──────────────────────────────────────

    async def observe_inbox(self, max_results: int = 20) -> list[dict[str, Any]]:
        """Fetch recent sent and received emails and run the analysis pipeline.

        TRAINING mode only.  Never sends, drafts, or marks emails as read.
        """
        if self._mode is EmailMode.OPERATIONAL:
            return []

        service = await self._build_gmail_service()

        messages = await self._fetch_messages(service, max_results)
        logger.info("Fetched %d messages for observation", len(messages))

        results: list[dict[str, Any]] = []
        for raw_msg in messages:
            try:
                email = self._parse_message(raw_msg)
                analysis = await self._analyze_email(email)
                results.append(analysis)
            except (LLMError, DatabaseError, IraError, Exception):
                msg_id = raw_msg.get("id", "unknown")
                logger.exception("Failed to process message %s", msg_id)

        logger.info(
            "Observation complete: %d/%d emails analysed",
            len(results),
            len(messages),
        )
        return results

    async def _fetch_messages(
        self, service: Any, max_results: int,
    ) -> list[dict[str, Any]]:
        """List and fetch full message payloads (sent + received)."""

        def _list_and_get() -> list[dict[str, Any]]:
            resp = (
                service.users()
                .messages()
                .list(userId="me", maxResults=max_results)
                .execute()
            )
            message_stubs = resp.get("messages", [])

            full_messages: list[dict[str, Any]] = []
            for stub in message_stubs:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=stub["id"], format="full")
                    .execute()
                )
                full_messages.append(msg)
            return full_messages

        return await asyncio.to_thread(_list_and_get)

    # ── Inbox processing (OPERATIONAL) ────────────────────────────────────

    async def process_inbox(self, max_results: int = 20) -> list[dict[str, Any]]:
        """Fetch unread emails, analyse, draft replies, and mark as read.

        OPERATIONAL mode entry point.  Creates Gmail drafts for actionable
        intents and sends a Telegram notification for each.  Never sends
        emails directly — a human must review and send each draft.
        """
        service = await self._build_gmail_service()
        messages = await self._fetch_unread(service, max_results)
        logger.info("Fetched %d unread messages", len(messages))

        results: list[dict[str, Any]] = []
        for raw_msg in messages:
            try:
                email = self._parse_message(raw_msg)
                analysis = await self._analyze_email(email)
                classification = analysis.get("classification", {})
                intent = classification.get("intent", "")

                draft_created = False
                if intent in _REPLY_INTENTS:
                    reply_body = await self._generate_reply(email, classification)
                    if reply_body:
                        await self._create_draft(
                            service, email.from_address, email.subject,
                            reply_body, email.thread_id,
                        )
                        await self._send_telegram_notification(email.subject)
                        draft_created = True

                await self._mark_as_read(service, email.id)
                analysis["draft_created"] = draft_created
                results.append(analysis)
            except (ToolExecutionError, LLMError, DatabaseError, IraError, Exception):
                logger.exception(
                    "Failed to process message %s", raw_msg.get("id", "unknown"),
                )

        logger.info(
            "Processing complete: %d/%d emails handled", len(results), len(messages),
        )
        return results

    async def _fetch_unread(
        self, service: Any, max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch unread messages from the inbox."""

        def _list_and_get() -> list[dict[str, Any]]:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=max_results)
                .execute()
            )
            stubs = resp.get("messages", [])
            return [
                service.users()
                .messages()
                .get(userId="me", id=s["id"], format="full")
                .execute()
                for s in stubs
            ]

        return await asyncio.to_thread(_list_and_get)

    async def _generate_reply(
        self, email: Email, classification: dict[str, Any],
    ) -> str:
        """Route to the suggested Pantheon agent and generate a reply."""
        agent_name = classification.get("suggested_agent", "athena")
        agent = self._pantheon.get_agent(agent_name) if self._pantheon else None
        if agent is None and self._pantheon:
            agent = self._pantheon.get_agent("athena")
        if agent is None:
            return ""

        context = {
            "task": "draft_email_reply",
            "original_from": email.from_address,
            "original_subject": email.subject,
            "intent": classification.get("intent", "GENERAL_INQUIRY"),
            "urgency": classification.get("urgency", "MEDIUM"),
        }
        return await agent.handle(
            f"Draft a professional reply to this email:\n\n{email.body}",
            context,
        )

    async def _create_draft(
        self,
        service: Any,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None,
    ) -> dict[str, Any]:
        """Create a Gmail draft with the given reply content."""
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        def _create() -> dict[str, Any]:
            return (
                service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )

        return await asyncio.to_thread(_create)

    async def _mark_as_read(self, service: Any, message_id: str) -> None:
        """Remove the UNREAD label from a message."""

        def _modify() -> None:
            service.users().messages().modify(
                userId="me", id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

        await asyncio.to_thread(_modify)

    async def _send_telegram_notification(self, subject: str) -> None:
        """Notify the admin that a new draft has been created."""
        settings = get_settings()
        token = settings.telegram.bot_token.get_secret_value()
        chat_id = settings.telegram.admin_chat_id

        if not token or not chat_id:
            logger.warning("Telegram not configured — skipping draft notification")
            return

        text = (
            f"New draft email created for [{subject}]. "
            "Please review and send."
        )
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": text})
                resp.raise_for_status()
        except (IraError, Exception):
            logger.exception("Failed to send Telegram draft notification")

    # ── Thread retrieval ──────────────────────────────────────────────────

    async def get_thread(self, thread_id: str) -> list[Email]:
        """Fetch a full email thread and return as a sorted list of Email models."""
        service = await self._build_gmail_service()

        def _fetch_thread() -> dict[str, Any]:
            return (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

        thread_data = await asyncio.to_thread(_fetch_thread)
        raw_messages = thread_data.get("messages", [])

        emails = [self._parse_message(msg) for msg in raw_messages]
        emails.sort(key=lambda e: e.received_at)
        return emails

    # ── Polling ───────────────────────────────────────────────────────────

    async def poll_inbox(self, interval_seconds: int = 300) -> None:
        """Continuously observe/process the inbox at a fixed interval.

        Runs forever; designed to be launched as a background task.
        Delegates to ``observe_inbox`` in TRAINING mode and
        ``process_inbox`` in OPERATIONAL mode.
        """
        logger.info(
            "Starting inbox polling every %d seconds (mode=%s)",
            interval_seconds,
            self._mode.value,
        )
        while True:
            try:
                if self._mode is EmailMode.OPERATIONAL:
                    results = await self.process_inbox()
                else:
                    results = await self.observe_inbox()
                logger.info(
                    "Poll cycle complete — %d emails processed", len(results),
                )
            except (IraError, Exception):
                logger.exception("Poll cycle failed — will retry next cycle")
            await asyncio.sleep(interval_seconds)

    # ── Analysis pipeline ─────────────────────────────────────────────────

    async def _analyze_email(self, email: Email) -> dict[str, Any]:
        """Run the full analysis pipeline on a single email.

        1. CLASSIFY via Delphi
        2. DIGEST via DigestiveSystem
        3. RESOLVE IDENTITY via SensorySystem
        4. LOG interaction in CRM
        """
        direction = self._infer_direction(email)

        # 1. Classify
        classification_raw = await self._delphi.handle(
            email.body,
            {"subject": email.subject, "from": email.from_address},
        )
        classification = self._safe_parse_json(classification_raw)

        # 2. Digest
        digest_result = await self._digestive.ingest_email(email)

        # 3. Resolve identity
        identity_address = (
            email.from_address
            if direction is Direction.INBOUND
            else email.to_address
        )
        _, identity_name = parseaddr(identity_address)
        contact = await self._sensory.resolve_identity(
            Channel.EMAIL.value,
            identity_address,
            identity_name or None,
        )

        # 4. Log interaction
        analysis_summary = json.dumps(
            {
                "classification": classification,
                "digest": {
                    "chunks_created": digest_result.get("chunks_created", 0),
                    "entities_found": digest_result.get("entities_found", {}),
                },
            },
            default=str,
        )

        crm_contact = await self._crm.get_contact_by_email(contact.email)
        if crm_contact is None:
            try:
                crm_contact = await self._crm.create_contact(
                    name=contact.name,
                    email=contact.email,
                    company=contact.company,
                    source="email_inbound",
                )
            except (DatabaseError, Exception):
                logger.warning("Could not create CRM contact for %s", contact.email)

        if crm_contact is not None:
            await self._crm.create_interaction(
                contact_id=str(crm_contact.id),
                channel=Channel.EMAIL,
                direction=direction,
                subject=email.subject,
                content=analysis_summary,
            )

        if self._unified_ctx is not None:
            try:
                user_id = contact.email
                summary = f"[{direction.value}] {email.subject}"
                self._unified_ctx.record_turn(
                    user_id,
                    "email",
                    email.body[:500] if direction is Direction.INBOUND else summary,
                    analysis_summary[:500] if direction is Direction.INBOUND else email.body[:500],
                )
            except (IraError, Exception):
                logger.exception("UnifiedContextManager recording failed for email")

        return {
            "email_id": email.id,
            "thread_id": email.thread_id,
            "subject": email.subject,
            "from": email.from_address,
            "to": email.to_address,
            "direction": direction.value,
            "classification": classification,
            "digest": digest_result,
            "contact": {
                "name": contact.name,
                "email": contact.email,
            },
        }

    # ── Message parsing ───────────────────────────────────────────────────

    def _parse_message(self, raw: dict[str, Any]) -> Email:
        """Convert a Gmail API message resource into an Email model."""
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        from_addr = headers.get("from", "")
        to_addr = headers.get("to", "")
        subject = headers.get("subject", "(no subject)")
        date_str = headers.get("date", "")
        thread_id = raw.get("threadId")
        labels = raw.get("labelIds", [])

        body = self._extract_body(raw.get("payload", {}))

        received_at = self._parse_date(date_str)

        return Email(
            id=raw["id"],
            from_address=from_addr,
            to_address=to_addr,
            subject=subject,
            body=body,
            received_at=received_at,
            thread_id=thread_id,
            labels=labels,
        )

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Recursively extract the plain-text body from a Gmail payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            nested = EmailProcessor._extract_body(part)
            if nested:
                return nested

        return ""

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Best-effort parse of an email Date header."""
        from email.utils import parsedate_to_datetime

        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    def _infer_direction(self, email: Email) -> Direction:
        """Determine if an email is inbound or outbound relative to the active mailbox."""
        _, from_email = parseaddr(email.from_address)
        reference = (
            self._training_email
            if self._mode is EmailMode.TRAINING
            else self._operational_email
        )
        if from_email.lower() == reference.lower():
            return Direction.OUTBOUND
        return Direction.INBOUND

    @staticmethod
    def _safe_parse_json(raw: str) -> dict[str, Any]:
        """Attempt to parse a JSON string, returning a fallback dict on failure."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return {"raw_response": raw}


class GmailDraftSender:
    """Adapter that satisfies the DripEngine's ``GmailSenderProtocol``.

    Creates Gmail drafts (never sends directly) and notifies the admin
    via Telegram so a human can review before sending.
    """

    def __init__(self, email_processor: EmailProcessor) -> None:
        self._processor = email_processor

    async def create_draft(
        self, to: str, subject: str, body: str,
    ) -> dict[str, Any]:
        service = await self._processor._build_gmail_service()
        return await self._processor._create_draft(
            service, to, subject, body, thread_id=None,
        )

    async def send_notification(self, message: str) -> None:
        settings = get_settings()
        token = settings.telegram.bot_token.get_secret_value()
        chat_id = settings.telegram.admin_chat_id

        if not token or not chat_id:
            logger.warning("Telegram not configured — skipping drip notification")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": message})
                resp.raise_for_status()
        except (IraError, Exception):
            logger.exception("Failed to send Telegram drip notification")

    async def check_replies(self, thread_id: str) -> list[dict[str, Any]]:
        service = await self._processor._build_gmail_service()

        def _list() -> list[dict[str, Any]]:
            resp = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="metadata")
                .execute()
            )
            return resp.get("messages", [])

        try:
            return await asyncio.to_thread(_list)
        except (IraError, Exception):
            logger.exception("Failed to check replies for thread %s", thread_id)
            return []
