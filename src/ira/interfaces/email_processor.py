"""Email processor — Gmail inbox observation and analysis pipeline.

Supports two modes controlled by the ``IRA_EMAIL_MODE`` environment variable:

* **TRAINING** (default): Read-only observation of the training email address.
  Fetches sent and received emails, classifies them via Delphi, digests them
  through the DigestiveSystem, resolves sender identity, and logs interactions
  in the CRM.  **Never** sends, drafts, or modifies emails.

* **OPERATIONAL**: Active processing of the configured ``GOOGLE_IRA_EMAIL``.  Fetches
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
import re
from datetime import datetime, timezone
from decimal import Decimal
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
from ira.data.models import Channel, DealStage, Direction, Email
from ira.exceptions import DatabaseError, IraError, LLMError, ToolExecutionError

logger = logging.getLogger(__name__)

_TRAINING_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_OPERATIONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

_REPLY_INTENTS = frozenset({
    "QUOTE_REQUEST", "SUPPORT", "GENERAL_INQUIRY",
    "PARTNERSHIP", "COMPLAINT", "FOLLOW_UP",
})

_DEAL_INTENTS = frozenset({
    "QUOTE_REQUEST", "FOLLOW_UP", "PARTNERSHIP",
})

_DEAL_SUBJECT_PATTERNS = re.compile(
    r"(?i)(quote|proposal|offer|PF1|PF2|ATF|AM[-\s]|IMG|FCS|"
    r"thermoform|vacuum\s*form|machine\s+inquiry|pricing|"
    r"techno.?commercial)",
)

_NON_BUSINESS_DOMAINS = frozenset({
    "instagram.com", "facebook.com", "twitter.com", "linkedin.com",
    "netflix.com", "spotify.com", "amazon.com", "google.com",
    "apple.com", "microsoft.com", "github.com", "openai.com",
    "moneycontrol.com", "squarespace.com", "medium.com",
    "substack.com", "mailchimp.com", "hubspot.com",
})

_NON_BUSINESS_PREFIXES = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "notifications", "notify", "mailer", "newsletter",
    "marketing", "promo", "alerts", "billing",
})


def _is_non_business_sender(email_addr: str) -> bool:
    """Fast pre-filter to skip consumer newsletters and automated senders."""
    local, _, domain = email_addr.lower().partition("@")
    if not domain:
        return False
    parent = ".".join(domain.split(".")[-2:])
    if domain in _NON_BUSINESS_DOMAINS or parent in _NON_BUSINESS_DOMAINS:
        return True
    return any(local.startswith(p) for p in _NON_BUSINESS_PREFIXES)


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
        self._poll_lock = asyncio.Lock()

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

    # ── Deal creation from email signals ────────────────────────────────

    async def _maybe_create_deal(
        self,
        crm_contact: Any,
        email: Email,
        classification: dict[str, Any],
        digest_result: dict[str, Any],
    ) -> None:
        """Create a CRM deal when an email carries proposal/quote signals.

        Checks both the Delphi classification intent and subject-line
        patterns for machine models and sales keywords.  Skips if the
        contact already has a deal whose title overlaps with this thread.
        """
        intent = classification.get("intent", "") if classification else ""
        subject = email.subject or ""

        has_deal_intent = intent in _DEAL_INTENTS
        has_deal_subject = bool(_DEAL_SUBJECT_PATTERNS.search(subject))

        if not has_deal_intent and not has_deal_subject:
            return

        try:
            existing_deals = await self._crm.get_deals_for_contact(
                str(crm_contact.id),
            )
            subject_lower = subject.lower()
            for deal in existing_deals:
                deal_title = (deal.get("title") or "").lower()
                if (
                    deal_title
                    and (deal_title in subject_lower or subject_lower in deal_title)
                ):
                    return

            machine = self._extract_machine_model(subject, digest_result)
            value = self._extract_deal_value(digest_result)
            stage = DealStage.PROPOSAL if has_deal_subject else DealStage.ENGAGED
            title = f"{machine} — {subject[:120]}" if machine else subject[:200]

            await self._crm.create_deal(
                contact_id=str(crm_contact.id),
                title=title,
                value=value,
                currency="USD",
                stage=stage,
                machine_model=machine or None,
                notes=f"Auto-created from email thread. Intent: {intent}",
            )
            logger.info(
                "Created deal for %s: %s (stage=%s)",
                crm_contact.email, title, stage,
            )
        except (DatabaseError, Exception):
            logger.warning(
                "Could not create deal from email for %s", crm_contact.email,
                exc_info=True,
            )

    @staticmethod
    def _extract_machine_model(
        subject: str, digest_result: dict[str, Any],
    ) -> str:
        """Pull the first Machinecraft machine model from subject or digest metadata."""
        pattern = re.compile(
            r"(?i)(PF[12][-\s]?(?:XL[-\s]?|X[-\s]?|C[-\s]?)?[\d]{3,4})"
            r"|(ATF[-\s]?[\d]{3,4})"
            r"|(AM[-\s]?V?[-\s]?[\d]{3,4})"
            r"|(IMG[-\s]?[\d]{3,4})"
            r"|(FCS[-\s]?[\d]{3,4})"
            r"|(SAM[-\s]?[\d]{3,4})"
        )
        m = pattern.search(subject)
        if m:
            return m.group(0).strip()

        meta = digest_result.get("email_metadata") or {}
        machines = meta.get("machine_mentions") or []
        if machines:
            return str(machines[0])
        return ""

    @staticmethod
    def _extract_deal_value(digest_result: dict[str, Any]) -> Decimal:
        """Best-effort extraction of a monetary value from digest metadata."""
        meta = digest_result.get("email_metadata") or {}
        for mention in meta.get("pricing_mentions") or []:
            nums = re.findall(r"[\d,]+(?:\.\d+)?", str(mention))
            for n in nums:
                try:
                    val = Decimal(n.replace(",", ""))
                    if val > 0:
                        return val
                except Exception:
                    continue
        return Decimal("0")

    # ── Deep historical scan ─────────────────────────────────────────────

    async def deep_scan(
        self,
        after: str = "",
        before: str = "",
        batch_size: int = 100,
        throttle: float = 0.1,
        resume: bool = False,
        dry_run: bool = False,
        progress_callback: Any | None = None,
        artemis: Any | None = None,
        triage_batch_size: int = 20,
        gmail_query: str = "",
    ) -> dict[str, Any]:
        """Scan historical Gmail messages through the full analysis pipeline.

        Parameters
        ----------
        gmail_query : str
            Additional Gmail search operators appended to the date range.
            Use this to narrow the scan to specific senders, keywords, or
            labels — e.g. ``"{from:machinecraft.org OR subject:PF1}"``.

        When *artemis* is provided, the scan uses a two-phase approach:

        1. **Batch triage** — fetch lightweight metadata for all messages,
           then ask Artemis to classify batches of *triage_batch_size* as
           BUSINESS_HIGH / BUSINESS_LOW / NOISE.  Only BUSINESS_HIGH
           emails proceed to full processing.
        2. **Deep processing** — fetch full body and run through
           ``_analyze_email()`` (Delphi + DigestiveSystem + CRM).

        Without *artemis*, every email is fetched and processed (original
        behaviour, much slower for large mailboxes).
        """
        checkpoint_path = Path("data/.deep_scan_checkpoint.json")
        processed_ids: set[str] = set()
        if resume and checkpoint_path.exists():
            try:
                data = json.loads(checkpoint_path.read_text())
                processed_ids = set(data.get("processed_ids", []))
                logger.info("Resuming deep scan — %d messages already processed", len(processed_ids))
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not read checkpoint file — starting fresh")

        parts: list[str] = []
        if after:
            parts.append(f"after:{after}")
        if before:
            parts.append(f"before:{before}")
        if gmail_query:
            parts.append(gmail_query)
        q = " ".join(parts).strip() or "in:anywhere"

        service = await self._build_gmail_service()

        stats: dict[str, int] = {
            "total_listed": 0,
            "fetched": 0,
            "processed": 0,
            "triaged_business_high": 0,
            "triaged_noise": 0,
            "skipped_duplicate": 0,
            "skipped_non_business": 0,
            "contacts_found": 0,
            "deals_created": 0,
            "inbound_emails": 0,
            "outbound_emails": 0,
            "proposal_signals": 0,
            "errors": 0,
        }

        threads_with_inbound: set[str] = set()
        threads_with_outbound: set[str] = set()

        all_stubs = await self._paginate_message_list(service, q, batch_size)
        stats["total_listed"] = len(all_stubs)
        logger.info("Deep scan: %d messages listed for q=%r", len(all_stubs), q)

        # Phase 1: Batch triage via Artemis (if available)
        business_ids: set[str] | None = None
        if artemis is not None:
            logger.info("Artemis batch triage: classifying %d messages in batches of %d",
                        len(all_stubs), triage_batch_size)
            business_ids = set()
            new_stubs = [s for s in all_stubs if s["id"] not in processed_ids]

            for batch_start in range(0, len(new_stubs), triage_batch_size):
                batch = new_stubs[batch_start:batch_start + triage_batch_size]

                metadata_batch = await self._fetch_metadata_batch(service, batch)

                triage_input = []
                for meta in metadata_batch:
                    _, from_email = parseaddr(meta.get("from", ""))
                    if from_email and _is_non_business_sender(from_email):
                        stats["skipped_non_business"] += 1
                        processed_ids.add(meta["id"])
                        continue
                    triage_input.append({
                        "id": meta["id"],
                        "from": meta.get("from", ""),
                        "subject": meta.get("subject", ""),
                        "snippet": meta.get("snippet", ""),
                    })

                if not triage_input:
                    continue

                try:
                    triage_json = json.dumps(triage_input)
                    result = await artemis.handle(
                        "Triage this batch of emails.",
                        {"task": "batch_triage", "batch": triage_json},
                    )

                    classifications = json.loads(result) if isinstance(result, str) else result
                    if isinstance(classifications, list):
                        for item in classifications:
                            cat = item.get("category", "SKIP").upper()
                            if cat in ("SALES", "BUSINESS_HIGH"):
                                business_ids.add(item["id"])
                                stats["triaged_business_high"] += 1
                            else:
                                stats["triaged_noise"] += 1
                                processed_ids.add(item["id"])
                    else:
                        for item in triage_input:
                            business_ids.add(item["id"])
                            stats["triaged_business_high"] += 1
                except (LLMError, IraError, json.JSONDecodeError, Exception):
                    logger.warning("Artemis triage failed for batch — falling back to process all",
                                   exc_info=True)
                    for item in triage_input:
                        business_ids.add(item["id"])

                if progress_callback is not None:
                    progress_callback(
                        stats["triaged_business_high"] + stats["triaged_noise"],
                        len(new_stubs),
                        stats,
                    )

            logger.info(
                "Artemis triage complete: %d BUSINESS_HIGH, %d NOISE out of %d",
                stats["triaged_business_high"], stats["triaged_noise"], len(new_stubs),
            )

        # Phase 2: Deep processing of business-relevant emails
        for i, stub in enumerate(all_stubs):
            msg_id = stub["id"]

            if msg_id in processed_ids:
                stats["skipped_duplicate"] += 1
                continue

            if business_ids is not None and msg_id not in business_ids:
                continue

            try:
                raw_msg = await self._fetch_single_message(service, msg_id)
                stats["fetched"] += 1

                email = self._parse_message(raw_msg)

                _, from_email = parseaddr(email.from_address)
                if from_email and _is_non_business_sender(from_email):
                    stats["skipped_non_business"] += 1
                    processed_ids.add(msg_id)
                    continue

                direction = self._infer_direction(email)
                if direction is Direction.INBOUND:
                    stats["inbound_emails"] += 1
                    if email.thread_id:
                        threads_with_inbound.add(email.thread_id)
                else:
                    stats["outbound_emails"] += 1
                    if email.thread_id:
                        threads_with_outbound.add(email.thread_id)

                if _DEAL_SUBJECT_PATTERNS.search(email.subject or ""):
                    stats["proposal_signals"] += 1

                if not dry_run:
                    analysis = await self._analyze_email(email)

                    if analysis.get("contact", {}).get("email"):
                        stats["contacts_found"] += 1

                    classification = analysis.get("classification", {})
                    intent = classification.get("intent", "")
                    if intent in _DEAL_INTENTS or _DEAL_SUBJECT_PATTERNS.search(email.subject or ""):
                        stats["deals_created"] += 1

                stats["processed"] += 1
                processed_ids.add(msg_id)

                if (stats["processed"]) % 50 == 0:
                    self._save_checkpoint(checkpoint_path, processed_ids, stats)

                if progress_callback is not None:
                    progress_callback(stats["processed"], stats["total_listed"], stats)

            except (LLMError, DatabaseError, IraError, Exception):
                stats["errors"] += 1
                logger.exception("Deep scan failed on message %s", msg_id)
                processed_ids.add(msg_id)

            if throttle > 0:
                await asyncio.sleep(throttle)

        unanswered_threads = threads_with_inbound - threads_with_outbound
        stats["unanswered_inbound_threads"] = len(unanswered_threads)

        self._save_checkpoint(checkpoint_path, processed_ids, stats)

        logger.info("Deep scan complete: %s", stats)
        return stats

    async def _paginate_message_list(
        self, service: Any, q: str, page_size: int,
    ) -> list[dict[str, Any]]:
        """List all message stubs matching *q*, paging through ``nextPageToken``."""

        def _list_all() -> list[dict[str, Any]]:
            all_stubs: list[dict[str, Any]] = []
            page_token: str | None = None

            while True:
                kwargs: dict[str, Any] = {
                    "userId": "me",
                    "q": q,
                    "maxResults": min(page_size, 500),
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                resp = service.users().messages().list(**kwargs).execute()
                stubs = resp.get("messages", [])
                all_stubs.extend(stubs)

                page_token = resp.get("nextPageToken")
                if not page_token or not stubs:
                    break

            return all_stubs

        return await asyncio.to_thread(_list_all)

    async def _fetch_metadata_batch(
        self, service: Any, stubs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fetch lightweight metadata (From, To, Subject, snippet) for a batch of messages.

        Uses ``format=metadata`` which is much cheaper than ``format=full``
        (~2 quota units vs 5) and avoids downloading message bodies.
        """

        def _get_batch() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            for stub in stubs:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=stub["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject"],
                    )
                    .execute()
                )
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                results.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId", ""),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "snippet": msg.get("snippet", ""),
                })
            return results

        return await asyncio.to_thread(_get_batch)

    async def _fetch_single_message(
        self, service: Any, msg_id: str,
    ) -> dict[str, Any]:
        """Fetch a single full message payload in a thread-safe manner."""

        def _get() -> dict[str, Any]:
            return (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )

        return await asyncio.to_thread(_get)

    @staticmethod
    def _save_checkpoint(
        path: Path, processed_ids: set[str], stats: dict[str, int],
    ) -> None:
        """Persist scan progress so the scan can be resumed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "processed_ids": list(processed_ids),
            "stats": stats,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }))

    # ── Email search ─────────────────────────────────────────────────────

    async def search_emails(
        self,
        *,
        from_address: str = "",
        to_address: str = "",
        subject: str = "",
        query: str = "",
        after: str = "",
        before: str = "",
        max_results: int = 10,
    ) -> list[Email]:
        """Search Gmail using native query syntax and return parsed Email models.

        Parameters build a Gmail ``q`` string.  For example
        ``from_address="contact@acme-corp.com"`` becomes ``from:contact@acme-corp.com``.
        ``query`` is appended verbatim for free-form Gmail search operators.
        ``after`` / ``before`` accept ``YYYY/MM/DD`` strings.
        """
        parts: list[str] = []
        if from_address:
            parts.append(f"from:{from_address}")
        if to_address:
            parts.append(f"to:{to_address}")
        if subject:
            parts.append(f"subject:{subject}")
        if after:
            parts.append(f"after:{after}")
        if before:
            parts.append(f"before:{before}")
        if query:
            parts.append(query)

        q = " ".join(parts).strip()
        if not q:
            q = "in:anywhere"

        service = await self._build_gmail_service()

        def _search() -> list[dict[str, Any]]:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=q, maxResults=max_results)
                .execute()
            )
            stubs = resp.get("messages", [])
            results: list[dict[str, Any]] = []
            for stub in stubs:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=stub["id"], format="full")
                    .execute()
                )
                results.append(msg)
            return results

        raw_messages = await asyncio.to_thread(_search)
        logger.info("Gmail search q=%r returned %d results", q, len(raw_messages))
        return [self._parse_message(m) for m in raw_messages]

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
            if self._poll_lock.locked():
                logger.warning("Previous poll cycle still running, skipping")
            else:
                async with self._poll_lock:
                    try:
                        if self._mode is EmailMode.OPERATIONAL:
                            results = await self.process_inbox()
                        else:
                            results = await self.observe_inbox()
                        logger.info(
                            "Poll cycle complete — %d emails processed",
                            len(results),
                        )
                    except (IraError, Exception):
                        logger.exception(
                            "Poll cycle failed — will retry next cycle"
                        )
            await asyncio.sleep(interval_seconds)

    async def run_single_poll_cycle(self) -> list[dict[str, Any]]:
        """Execute exactly one poll cycle and return results.

        Unlike ``poll_inbox`` this does not loop — it processes the inbox
        once and returns, making it suitable for CLI / on-demand use.
        """
        async with self._poll_lock:
            if self._mode is EmailMode.OPERATIONAL:
                return await self.process_inbox()
            return await self.observe_inbox()

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

            await self._maybe_create_deal(
                crm_contact, email, classification, digest_result,
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
