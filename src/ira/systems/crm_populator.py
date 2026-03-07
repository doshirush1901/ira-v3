"""CRM population pipeline — classify and import contacts.

Extracts contacts from Gmail inbox, the Qdrant knowledge base, and
Neo4j, classifies each via Delphi (with Clio-style cross-referencing
for evidence), and inserts only CRM-eligible contacts (live customer,
past customer, lead with interactions, lead without interactions).

Usage::

    ira populate-crm [--dry-run] [--source all|gmail|kb|neo4j]
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import httpx

from ira.agents.delphi import Delphi
from ira.config import get_settings
from ira.data.crm import CRMDatabase
from ira.data.models import ContactType
from ira.exceptions import DatabaseError, IraError, LLMError

logger = logging.getLogger(__name__)

_VALID_CRM_TYPES = {
    "LIVE_CUSTOMER": ContactType.LIVE_CUSTOMER,
    "PAST_CUSTOMER": ContactType.PAST_CUSTOMER,
    "LEAD_WITH_INTERACTIONS": ContactType.LEAD_WITH_INTERACTIONS,
    "LEAD_NO_INTERACTIONS": ContactType.LEAD_NO_INTERACTIONS,
}

_OWN_DOMAINS = frozenset({"machinecraft.org", "machinecraft.in"})

_REJECT_PREFIXES = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "billing",
    "alerts", "newsletter", "news", "notifications", "notify",
    "mailer", "marketing", "promo", "info@members", "hello@mail.",
    "hello@email.", "hello@e.", "share@email.", "team@mail.",
    "stories-recap", "support@mail.", "info@email.",
})

_REJECT_DOMAINS = frozenset({
    "instagram.com", "facebook.com", "twitter.com", "linkedin.com",
    "netflix.com", "spotify.com", "amazon.com", "google.com",
    "apple.com", "microsoft.com", "github.com", "openai.com",
    "moneycontrol.com", "squarespace.com", "medium.com",
    "substack.com", "mailchimp.com", "hubspot.com",
    "singaporeair.com", "shakeshack.com", "avg.com", "cursor.com",
    "railway.app", "sampark.gov.in", "yatramailers.com",
    "sunglasshut.com", "marcjacobs.com", "nordiskemedier.dk",
    "economictimesnews.com", "fairygodboss.com", "careem.com",
    "impactguru.com", "thomasnet.com", "freshplaza.com",
    "nin-nin.fr", "sarahssilks.com", "rforrabbit.com",
    "bombaysweetshop.com", "littletikes.com", "ethoswatches.com",
    "nevertoosmall.com", "zamaorganics.com", "mapmygenome.in",
    "cgboost.com", "strategyzer.com", "camsonline.com",
    "smarttouchswitch.io", "onepercentclub.io", "dsij.in",
    "msmegrowthhub.com", "danmartell.com",
})


def _is_obviously_not_business(email: str) -> bool:
    """Fast pre-filter to reject consumer newsletters and automated senders."""
    local, _, domain = email.partition("@")
    if not domain:
        return True

    if domain in _REJECT_DOMAINS:
        return True

    parent_domain = ".".join(domain.split(".")[-2:])
    if parent_domain in _REJECT_DOMAINS:
        return True

    for prefix in _REJECT_PREFIXES:
        if email.startswith(prefix):
            return True

    return False


class CRMPopulator:
    """Orchestrates contact extraction, classification, and CRM insertion."""

    def __init__(
        self,
        delphi: Delphi,
        crm: CRMDatabase,
        *,
        dry_run: bool = False,
        event_bus: Any | None = None,
    ) -> None:
        self._delphi = delphi
        self._crm = crm
        self._dry_run = dry_run
        self._event_bus = event_bus

        settings = get_settings()
        self._qdrant_url = settings.qdrant.url
        self._qdrant_api_key = settings.qdrant.api_key.get_secret_value()
        self._qdrant_collection = settings.qdrant.collection

        self._stats: dict[str, int] = {
            "total_extracted": 0,
            "classified": 0,
            "inserted": 0,
            "skipped_duplicate": 0,
            "skipped_rejected": 0,
            "skipped_no_email": 0,
            "errors": 0,
        }
        self._classifications: list[dict[str, Any]] = []

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def classifications(self) -> list[dict[str, Any]]:
        return list(self._classifications)

    async def populate(self, sources: list[str] | None = None) -> dict[str, Any]:
        """Run the full population pipeline."""
        use = set(sources) if sources else {"gmail", "kb", "neo4j"}

        contacts: list[dict[str, Any]] = []

        if "gmail" in use:
            contacts.extend(await self._extract_from_gmail())
        if "kb" in use:
            contacts.extend(await self._extract_from_kb())
        if "neo4j" in use:
            contacts.extend(await self._extract_from_neo4j())

        contacts = self._deduplicate(contacts)
        self._stats["total_extracted"] = len(contacts)
        logger.info("Extracted %d unique contacts", len(contacts))

        for i, contact in enumerate(contacts):
            try:
                await self._process_contact(contact)
                if (i + 1) % 10 == 0:
                    logger.info(
                        "Progress: %d/%d (inserted=%d, rejected=%d)",
                        i + 1, len(contacts),
                        self._stats["inserted"],
                        self._stats["skipped_rejected"],
                    )
            except (LLMError, DatabaseError, IraError, Exception):
                self._stats["errors"] += 1
                logger.exception(
                    "Failed to process contact: %s",
                    contact.get("email", "unknown"),
                )

        logger.info("CRM population complete: %s", self._stats)
        return {
            "stats": self._stats,
            "dry_run": self._dry_run,
            "classifications": self._classifications,
        }

    # ── Processing ───────────────────────────────────────────────────────

    async def _process_contact(self, contact: dict[str, Any]) -> None:
        email = contact.get("email", "").strip().lower()
        if not email or "@" not in email:
            self._stats["skipped_no_email"] += 1
            return

        domain = email.split("@", 1)[1]
        if domain in _OWN_DOMAINS:
            self._stats["skipped_rejected"] += 1
            self._classifications.append({
                "email": email, "company": contact.get("company", ""),
                "contact_type": "OWN_COMPANY", "confidence": "HIGH",
                "reasoning": "Internal Machinecraft domain",
            })
            return

        if _is_obviously_not_business(email):
            self._stats["skipped_rejected"] += 1
            self._classifications.append({
                "email": email, "company": contact.get("company", ""),
                "contact_type": "OTHER", "confidence": "HIGH",
                "reasoning": "Consumer/newsletter/automated sender (pre-filter)",
            })
            return

        existing = await self._crm.get_contact_by_email(email)
        if existing is not None:
            self._stats["skipped_duplicate"] += 1
            return

        evidence = await self._gather_evidence(contact)
        contact["order_history"] = evidence.get("order_history", "")
        contact["email_evidence"] = evidence.get("email_evidence", "")

        classification = await self._classify(contact)
        self._stats["classified"] += 1

        self._classifications.append({
            "email": email,
            "name": contact.get("name", ""),
            "company": contact.get("company", ""),
            **classification,
        })

        contact_type_str = classification.get("contact_type", "")
        if contact_type_str not in _VALID_CRM_TYPES:
            self._stats["skipped_rejected"] += 1
            logger.debug(
                "Rejected %s (%s): %s — %s",
                email, contact.get("company", ""),
                contact_type_str, classification.get("reasoning", ""),
            )
            return

        if self._dry_run:
            self._stats["inserted"] += 1
            logger.info(
                "[DRY RUN] Would insert: %s (%s) as %s [%s]",
                email, contact.get("company", ""),
                contact_type_str, classification.get("confidence", "?"),
            )
            return

        company_name = contact.get("company", "")
        company_id = None
        if company_name:
            company_id = await self._ensure_company(company_name, contact.get("region"))

        await self._crm.create_contact(
            name=contact.get("name", email.split("@")[0]),
            email=email,
            company_id=company_id,
            role=contact.get("role"),
            phone=contact.get("phone"),
            source=contact.get("source", "populator"),
            contact_type=_VALID_CRM_TYPES[contact_type_str],
            lead_score=0.0,
        )
        self._stats["inserted"] += 1
        logger.info("Inserted: %s (%s) as %s", email, company_name, contact_type_str)

        if self._event_bus is not None:
            from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
            try:
                await self._event_bus.emit(DataEvent(
                    event_type=EventType.CONTACT_CLASSIFIED,
                    entity_type="contact",
                    entity_id=email,
                    payload={
                        "email": email,
                        "name": contact.get("name", ""),
                        "company": company_name,
                        "contact_type": contact_type_str,
                        "confidence": classification.get("confidence", ""),
                        "reasoning": classification.get("reasoning", ""),
                        "source": contact.get("source", "populator"),
                    },
                    source_store=SourceStore.POPULATOR,
                ))
            except (IraError, Exception):
                logger.debug("Populator event emission failed", exc_info=True)

    # ── Evidence gathering (Clio cross-referencing) ──────────────────────

    async def _gather_evidence(self, contact: dict[str, Any]) -> dict[str, Any]:
        """Search the KB for order/quote documents mentioning this contact's company."""
        company = contact.get("company", "")
        email = contact.get("email", "")
        name = contact.get("name", "")

        if not company and not name:
            return {}

        search_term = company or name
        evidence: dict[str, Any] = {}

        try:
            headers = {"Content-Type": "application/json"}
            if self._qdrant_api_key:
                headers["api-key"] = self._qdrant_api_key

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._qdrant_url}/collections/{self._qdrant_collection}/points/scroll",
                    headers=headers,
                    json={
                        "limit": 200,
                        "with_payload": {"include": ["content", "source", "source_category"]},
                        "with_vector": False,
                    },
                )
                resp.raise_for_status()
                points = resp.json()["result"]["points"]

            order_hits: list[str] = []
            quote_hits: list[str] = []
            search_lower = search_term.lower()

            for pt in points:
                content = (pt["payload"].get("content") or "").lower()
                source = (pt["payload"].get("source") or "").lower()
                cat = (pt["payload"].get("source_category") or "").lower()

                if search_lower not in content and search_lower not in source:
                    continue

                if any(kw in cat for kw in ("order", "po", "purchase")):
                    order_hits.append(pt["payload"].get("content", "")[:300])
                elif any(kw in cat for kw in ("quote", "offer", "pricing", "proposal")):
                    quote_hits.append(pt["payload"].get("content", "")[:300])
                elif any(kw in content for kw in ("purchase order", "po number", "order confirmation", "delivery")):
                    order_hits.append(pt["payload"].get("content", "")[:300])
                elif any(kw in content for kw in ("quote", "quotation", "offer", "proposal")):
                    quote_hits.append(pt["payload"].get("content", "")[:300])

            if order_hits:
                evidence["order_history"] = f"Found {len(order_hits)} order/PO documents:\n" + "\n".join(
                    f"  - {h[:200]}" for h in order_hits[:3]
                )
            if quote_hits:
                existing = evidence.get("order_history", "")
                evidence["order_history"] = (
                    existing + f"\nFound {len(quote_hits)} quote documents:\n" + "\n".join(
                        f"  - {h[:200]}" for h in quote_hits[:3]
                    )
                ).strip()

        except (DatabaseError, Exception):
            logger.debug("KB evidence gathering failed for %s", search_term, exc_info=True)

        return evidence

    # ── Classification ───────────────────────────────────────────────────

    async def _classify(self, contact: dict[str, Any]) -> dict[str, Any]:
        raw = await self._delphi.handle(
            "Classify this contact for CRM inclusion.",
            {
                "task": "classify_contact",
                "contact_data": contact,
                "order_history": contact.get("order_history", ""),
                "email_history": contact.get("email_evidence", ""),
            },
        )

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Delphi returned non-JSON for %s: %s", contact.get("email"), raw[:200])
            return {"contact_type": "OTHER", "confidence": "LOW", "reasoning": "Parse failure"}

    async def _ensure_company(self, name: str, region: str | None = None) -> str | None:
        companies = await self._crm.list_companies()
        for c in companies:
            if c.name.lower() == name.lower():
                return str(c.id)
        company = await self._crm.create_company(name=name, region=region)
        return str(company.id)

    # ── Data extraction: Gmail ───────────────────────────────────────────

    async def _extract_from_gmail(self) -> list[dict[str, Any]]:
        """Extract unique contacts from Gmail sent and received messages."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
            token_path = Path("token.json")

            if not token_path.exists():
                logger.warning("No Gmail token.json — skipping Gmail extraction")
                return []

            def _fetch() -> list[dict[str, Any]]:
                creds = Credentials.from_authorized_user_file(str(token_path), scopes)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    token_path.write_text(creds.to_json())

                service = build("gmail", "v1", credentials=creds)

                resp = service.users().messages().list(
                    userId="me", maxResults=500,
                ).execute()
                stubs = resp.get("messages", [])

                contacts_by_email: dict[str, dict[str, Any]] = {}
                email_counts: dict[str, int] = {}

                for stub in stubs:
                    msg = service.users().messages().get(
                        userId="me", id=stub["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject"],
                    ).execute()
                    headers = {
                        h["name"].lower(): h["value"]
                        for h in msg.get("payload", {}).get("headers", [])
                    }
                    labels = msg.get("labelIds", [])

                    from_name, from_email = parseaddr(headers.get("from", ""))
                    to_name, to_email = parseaddr(headers.get("to", ""))

                    for addr_name, addr_email in [(from_name, from_email), (to_name, to_email)]:
                        if not addr_email or "@" not in addr_email:
                            continue
                        addr_email = addr_email.lower().strip()
                        domain = addr_email.split("@", 1)[1]
                        if domain in _OWN_DOMAINS:
                            continue

                        email_counts[addr_email] = email_counts.get(addr_email, 0) + 1

                        if addr_email not in contacts_by_email:
                            company_guess = domain.split(".")[0].title()
                            contacts_by_email[addr_email] = {
                                "email": addr_email,
                                "name": addr_name or addr_email.split("@")[0],
                                "company": company_guess,
                                "source": "gmail",
                            }

                for email, contact in contacts_by_email.items():
                    contact["email_count"] = email_counts.get(email, 0)
                    contact["has_interactions"] = email_counts.get(email, 0) > 0

                return list(contacts_by_email.values())

            results = await asyncio.to_thread(_fetch)
            logger.info("Extracted %d contacts from Gmail", len(results))
            return results

        except (IraError, Exception):
            logger.exception("Gmail extraction failed")
            return []

    # ── Data extraction: Knowledge Base ──────────────────────────────────

    async def _extract_from_kb(self) -> list[dict[str, Any]]:
        """Extract company/contact mentions from the Qdrant knowledge base."""
        try:
            headers = {"Content-Type": "application/json"}
            if self._qdrant_api_key:
                headers["api-key"] = self._qdrant_api_key

            all_points: list[dict[str, Any]] = []
            offset = None

            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    body: dict[str, Any] = {
                        "limit": 100,
                        "with_payload": {"include": ["content", "source", "source_category", "metadata"]},
                        "with_vector": False,
                    }
                    if offset is not None:
                        body["offset"] = offset

                    resp = await client.post(
                        f"{self._qdrant_url}/collections/{self._qdrant_collection}/points/scroll",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    result = resp.json()["result"]
                    points = result["points"]
                    all_points.extend(points)

                    offset = result.get("next_page_offset")
                    if not offset or not points:
                        break

            contacts: dict[str, dict[str, Any]] = {}
            for pt in all_points:
                payload = pt.get("payload", {})
                metadata = payload.get("metadata", {})
                content = payload.get("content", "")
                cat = payload.get("source_category", "")

                customer_name = metadata.get("customer", "")
                if customer_name and isinstance(customer_name, str) and len(customer_name) > 2:
                    key = customer_name.lower().strip()
                    if key not in contacts:
                        has_order = any(kw in cat.lower() for kw in ("order", "po"))
                        has_quote = any(kw in cat.lower() for kw in ("quote", "offer", "proposal"))
                        contacts[key] = {
                            "name": customer_name,
                            "company": customer_name,
                            "email": "",
                            "source": f"kb:{cat}",
                            "has_order": has_order,
                            "has_quote": has_quote,
                            "kb_category": cat,
                        }

            results = [c for c in contacts.values() if c.get("email") or c.get("company")]
            logger.info(
                "Extracted %d contacts from KB (%d with email, %d company-only)",
                len(results),
                sum(1 for c in results if c.get("email")),
                sum(1 for c in results if not c.get("email")),
            )
            return results

        except (DatabaseError, Exception):
            logger.exception("KB extraction failed")
            return []

    # ── Data extraction: Neo4j ───────────────────────────────────────────

    async def _extract_from_neo4j(self) -> list[dict[str, Any]]:
        try:
            from ira.brain.knowledge_graph import KnowledgeGraph
            graph = KnowledgeGraph()
            query = (
                "MATCH (p:Person) "
                "OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company) "
                "RETURN p, c LIMIT 500"
            )
            records = await graph.run_cypher(query)

            results: list[dict[str, Any]] = []
            for record in records:
                p_node = record.get("p")
                c_node = record.get("c")
                person = dict(p_node) if p_node and hasattr(p_node, "__iter__") else {}
                company = dict(c_node) if c_node and hasattr(c_node, "__iter__") else {}

                email = person.get("email", "")
                if not email:
                    continue
                results.append({
                    "email": email,
                    "name": person.get("name", ""),
                    "company": company.get("name", ""),
                    "region": company.get("region", ""),
                    "source": "neo4j",
                })
            logger.info("Extracted %d contacts from Neo4j", len(results))
            return results
        except (DatabaseError, Exception):
            logger.debug("Neo4j extraction failed", exc_info=True)
            return []

    # ── Deduplication ────────────────────────────────────────────────────

    def _deduplicate(self, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_email: dict[str, dict[str, Any]] = {}
        for c in contacts:
            email = (c.get("email") or "").strip().lower()
            if not email:
                continue
            if email not in by_email:
                by_email[email] = c
            else:
                existing = by_email[email]
                for key in ("company", "name", "role", "region", "phone"):
                    if not existing.get(key) and c.get(key):
                        existing[key] = c[key]
                for key in ("has_interactions", "has_order", "has_quote"):
                    if c.get(key):
                        existing[key] = True
                if c.get("email_count", 0) > existing.get("email_count", 0):
                    existing["email_count"] = c["email_count"]
        return list(by_email.values())
