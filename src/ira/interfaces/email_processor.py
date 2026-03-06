"""Email processor — Gmail inbox observation and analysis pipeline.

Supports two modes controlled by the ``IRA_EMAIL_MODE`` environment variable:

* **TRAINING** (default): Read-only observation of ``rushabh@machinecraft.org``.
  Fetches sent and received emails, classifies them via Delphi, digests them
  through the DigestiveSystem, resolves sender identity, and logs interactions
  in the CRM.  **Never** sends, drafts, or modifies emails.

* **OPERATIONAL**: Stub for ``ira@machinecraft.org`` — will be implemented
  during the graduation phase.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ira.config import EmailMode, get_settings
from ira.data.models import Channel, Direction, Email

logger = logging.getLogger(__name__)

_TRAINING_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class EmailProcessor:
    """Gmail inbox observer with a full classification/ingestion pipeline."""

    def __init__(
        self,
        delphi: Any,
        digestive: Any,
        sensory: Any,
        crm: Any,
        *,
        settings: Any | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._google = cfg.google
        self._mode = self._google.email_mode

        if self._mode is EmailMode.OPERATIONAL:
            logger.warning(
                "EmailProcessor started in OPERATIONAL mode — "
                "all methods are stubbed until graduation phase"
            )
            self._delphi = None
            self._digestive = None
            self._sensory = None
            self._crm = None
            self._service = None
            return

        assert self._mode is EmailMode.TRAINING, (
            f"Unknown email mode: {self._mode}"
        )

        self._delphi = delphi
        self._digestive = digestive
        self._sensory = sensory
        self._crm = crm
        self._service: Any | None = None
        self._training_email = self._google.training_email

        logger.info(
            "EmailProcessor initialised in TRAINING mode for %s",
            self._training_email,
        )

    # ── Gmail authentication ──────────────────────────────────────────────

    async def _build_gmail_service(self) -> Any:
        """Authenticate with Gmail API (readonly) and cache the service."""
        if self._service is not None:
            return self._service

        if self._mode is EmailMode.OPERATIONAL:
            raise NotImplementedError("OPERATIONAL mode not yet implemented")

        creds_path = Path(self._google.credentials_path)
        token_path = Path(self._google.token_path)

        def _authenticate() -> Any:
            creds: Credentials | None = None

            if token_path.exists():
                creds = Credentials.from_authorized_user_file(
                    str(token_path), _TRAINING_SCOPES,
                )

            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), _TRAINING_SCOPES,
                )
                creds = flow.run_local_server(port=0)

            token_path.write_text(creds.to_json())
            return build("gmail", "v1", credentials=creds)

        self._service = await asyncio.to_thread(_authenticate)
        logger.info("Gmail service built (readonly scope)")
        return self._service

    # ── Inbox observation ─────────────────────────────────────────────────

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
            except Exception:
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

    # ── Thread retrieval ──────────────────────────────────────────────────

    async def get_thread(self, thread_id: str) -> list[Email]:
        """Fetch a full email thread and return as a sorted list of Email models."""
        if self._mode is EmailMode.OPERATIONAL:
            raise NotImplementedError("OPERATIONAL mode not yet implemented")

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
        """Continuously observe the inbox at a fixed interval.

        Runs forever; designed to be launched as a background task.
        """
        if self._mode is EmailMode.OPERATIONAL:
            logger.warning("poll_inbox called in OPERATIONAL mode — no-op")
            return

        logger.info(
            "Starting inbox polling every %d seconds", interval_seconds,
        )
        while True:
            try:
                results = await self.observe_inbox()
                logger.info(
                    "Poll cycle complete — %d emails processed", len(results),
                )
            except Exception:
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

        await self._crm.create_interaction(
            contact_id=str(contact.id),
            channel=Channel.EMAIL,
            direction=direction,
            subject=email.subject,
            content=analysis_summary,
        )

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
        """Determine if an email is inbound or outbound relative to the training mailbox."""
        _, from_email = parseaddr(email.from_address)
        if from_email.lower() == self._training_email.lower():
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
