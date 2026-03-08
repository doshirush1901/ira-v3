"""Circulatory System -- keeps CRM, Neo4j, and Qdrant in sync.

Subscribes to :class:`~ira.systems.data_event_bus.DataEventBus` events
and propagates changes across stores.  Also maintains a persistent
change ledger for auditability and replay.

Named after the biological circulatory system: it circulates data
between organs (stores) the way blood carries nutrients between
body systems.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ira.data.models import KnowledgeItem
from ira.exceptions import DatabaseError, IraError
from ira.systems.data_event_bus import (
    DataEvent,
    DataEventBus,
    EventType,
    SourceStore,
)

logger = logging.getLogger(__name__)

_LEDGER_PATH = Path("data/brain/data_ledger.jsonl")


class CirculatorySystem:
    """Wires sync handlers to the DataEventBus and maintains the change ledger."""

    def __init__(
        self,
        event_bus: DataEventBus,
        *,
        crm: Any = None,
        graph: Any = None,
        qdrant: Any = None,
        embedding: Any = None,
    ) -> None:
        self._bus = event_bus
        self._crm = crm
        self._graph = graph
        self._qdrant = qdrant
        self._embedding = embedding

        self._ledger_path = _LEDGER_PATH
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

        self._register_handlers()

    def _register_handlers(self) -> None:
        """Subscribe all sync handlers to the event bus."""
        self._bus.subscribe_all(self._ledger_handler)

        if self._graph:
            self._bus.subscribe(EventType.CONTACT_CREATED, self._crm_to_neo4j_contact)
            self._bus.subscribe(EventType.CONTACT_UPDATED, self._crm_to_neo4j_contact)
            self._bus.subscribe(EventType.CONTACT_CLASSIFIED, self._crm_to_neo4j_contact)
            self._bus.subscribe(EventType.COMPANY_CREATED, self._crm_to_neo4j_company)
            self._bus.subscribe(EventType.DEAL_CREATED, self._crm_to_neo4j_deal)
            self._bus.subscribe(EventType.RELATIONSHIP_DISCOVERED, self._relationship_to_neo4j)

        if self._qdrant and self._embedding:
            self._bus.subscribe(EventType.CONTACT_CREATED, self._crm_to_qdrant)
            self._bus.subscribe(EventType.CONTACT_UPDATED, self._crm_to_qdrant)
            self._bus.subscribe(EventType.CONTACT_CLASSIFIED, self._crm_to_qdrant)
            self._bus.subscribe(EventType.COMPANY_CREATED, self._company_to_qdrant)
            self._bus.subscribe(EventType.DEAL_CREATED, self._deal_to_qdrant)

        if self._crm:
            self._bus.subscribe(EventType.ENTITY_ADDED, self._neo4j_to_crm)

        logger.info(
            "CirculatorySystem registered handlers (graph=%s, qdrant=%s, crm=%s)",
            self._graph is not None,
            self._qdrant is not None,
            self._crm is not None,
        )

    # ── Change Ledger ────────────────────────────────────────────────────

    async def _ledger_handler(self, event: DataEvent) -> None:
        """Append every event to the persistent JSONL ledger."""
        entry = {
            "timestamp": event.timestamp.isoformat(),
            "event_type": event.event_type.value,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "source_store": event.source_store.value,
            "payload_keys": list(event.payload.keys()),
        }
        try:
            with open(self._ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except (IraError, Exception):
            logger.debug("Ledger write failed", exc_info=True)

    # ── CRM → Neo4j ─────────────────────────────────────────────────────

    async def _crm_to_neo4j_contact(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.NEO4J:
            return
        p = event.payload
        email = p.get("email", "")
        if not email:
            return

        try:
            await self._graph.add_person(
                name=p.get("name", ""),
                email=email,
                company_name=p.get("company", ""),
                role=p.get("role", ""),
            )

            contact_type = p.get("contact_type", "")
            if contact_type:
                await self._graph._run_cypher_write(
                    "MATCH (p:Person {email: $email}) "
                    "SET p.contact_type = $ct, p.lead_score = $score",
                    {"email": email, "ct": contact_type, "score": p.get("lead_score", 0)},
                )

            logger.debug("Synced contact %s to Neo4j", email)
        except (DatabaseError, Exception):
            logger.exception("CRM→Neo4j sync failed for %s", email)

    async def _crm_to_neo4j_company(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.NEO4J:
            return
        p = event.payload
        name = p.get("name", "")
        if not name:
            return

        try:
            await self._graph.add_company(
                name=name,
                region=p.get("region", ""),
                industry=p.get("industry", ""),
            )
            logger.debug("Synced company %s to Neo4j", name)
        except (DatabaseError, Exception):
            logger.exception("CRM→Neo4j sync failed for company %s", name)

    async def _crm_to_neo4j_deal(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.NEO4J:
            return
        p = event.payload
        try:
            deal_id = p.get("id", event.entity_id)
            company = p.get("company", "")
            machine = p.get("machine_model", "")

            if company:
                await self._graph.add_company(name=company)

            if machine:
                await self._graph._run_cypher_write(
                    "MERGE (m:Machine {model: $model})",
                    {"model": machine},
                )
                if company:
                    await self._graph._run_cypher_write(
                        "MATCH (c:Company {name: $company}), (m:Machine {model: $model}) "
                        "MERGE (c)-[:INTERESTED_IN]->(m)",
                        {"company": company, "model": machine},
                    )

            logger.debug("Synced deal %s to Neo4j", deal_id)
        except (DatabaseError, Exception):
            logger.exception("CRM→Neo4j deal sync failed for %s", event.entity_id)

    async def _relationship_to_neo4j(self, event: DataEvent) -> None:
        """Write an agent-discovered relationship to Neo4j."""
        p = event.payload
        try:
            await self._graph.add_relationship(
                from_type=p.get("from_type", ""),
                from_key=p.get("from_key", ""),
                rel_type=p.get("rel", ""),
                to_type=p.get("to_type", ""),
                to_key=p.get("to_key", ""),
                properties=p.get("properties"),
            )
            logger.debug(
                "Synced relationship %s-[%s]->%s to Neo4j",
                p.get("from_key"), p.get("rel"), p.get("to_key"),
            )
        except (DatabaseError, Exception):
            logger.exception("Relationship→Neo4j sync failed for %s", event.entity_id)

    # ── CRM → Qdrant ────────────────────────────────────────────────────

    async def _crm_to_qdrant(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.QDRANT:
            return
        p = event.payload
        email = p.get("email", "")
        if not email:
            return

        contact_type = p.get("contact_type", "unknown")
        company = p.get("company", "")
        name = p.get("name", "")

        content = (
            f"CRM Contact: {name} ({email})\n"
            f"Company: {company}\n"
            f"Type: {contact_type}\n"
            f"Role: {p.get('role', 'N/A')}\n"
            f"Lead Score: {p.get('lead_score', 0)}\n"
            f"Source: {p.get('source', 'N/A')}"
        )

        item = KnowledgeItem(
            id=uuid4(),
            source=f"crm:contact:{email}",
            source_category="crm_contact",
            content=content,
            metadata={
                "email": email,
                "name": name,
                "company": company,
                "contact_type": contact_type,
                "lead_score": p.get("lead_score", 0),
                "entity_type": "contact",
            },
        )

        try:
            await self._qdrant.upsert_items([item])
            logger.debug("Synced contact %s to Qdrant", email)
        except (DatabaseError, Exception):
            logger.exception("CRM→Qdrant sync failed for %s", email)

    async def _company_to_qdrant(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.QDRANT:
            return
        p = event.payload
        name = p.get("name", "")
        if not name:
            return

        content = (
            f"CRM Company: {name}\n"
            f"Region: {p.get('region', 'N/A')}\n"
            f"Industry: {p.get('industry', 'N/A')}"
        )

        item = KnowledgeItem(
            id=uuid4(),
            source=f"crm:company:{name}",
            source_category="crm_company",
            content=content,
            metadata={
                "name": name,
                "region": p.get("region", ""),
                "industry": p.get("industry", ""),
                "entity_type": "company",
            },
        )

        try:
            await self._qdrant.upsert_items([item])
            logger.debug("Synced company %s to Qdrant", name)
        except (DatabaseError, Exception):
            logger.exception("CRM→Qdrant sync failed for company %s", name)

    async def _deal_to_qdrant(self, event: DataEvent) -> None:
        if event.source_store == SourceStore.QDRANT:
            return
        p = event.payload

        content = (
            f"CRM Deal: {p.get('title', 'Untitled')}\n"
            f"Company: {p.get('company', 'N/A')}\n"
            f"Machine: {p.get('machine_model', 'N/A')}\n"
            f"Value: {p.get('currency', 'USD')} {p.get('value', 0)}\n"
            f"Stage: {p.get('stage', 'NEW')}"
        )

        item = KnowledgeItem(
            id=uuid4(),
            source=f"crm:deal:{event.entity_id}",
            source_category="crm_deal",
            content=content,
            metadata={
                "deal_id": event.entity_id,
                "title": p.get("title", ""),
                "machine_model": p.get("machine_model", ""),
                "stage": p.get("stage", "NEW"),
                "value": p.get("value", 0),
                "entity_type": "deal",
            },
        )

        try:
            await self._qdrant.upsert_items([item])
            logger.debug("Synced deal %s to Qdrant", event.entity_id)
        except (DatabaseError, Exception):
            logger.exception("CRM→Qdrant deal sync failed for %s", event.entity_id)

    # ── Neo4j → CRM ─────────────────────────────────────────────────────

    async def _neo4j_to_crm(self, event: DataEvent) -> None:
        """When a new entity is extracted, ensure it exists in CRM.

        Handles person and company entities.  Machine entities are
        intentionally skipped -- they are product catalog items stored
        in Neo4j only, not CRM records.
        """
        if event.source_store == SourceStore.CRM:
            return
        p = event.payload
        entity_type = p.get("entity_type", event.entity_type)

        if entity_type == "machine":
            return

        try:
            if entity_type == "person":
                email = p.get("email", "")
                if not email or "@" not in email:
                    return
                existing = await self._crm.get_contact_by_email(email)
                if existing is None:
                    await self._crm.create_contact(
                        name=p.get("name", email.split("@")[0]),
                        email=email,
                        source="neo4j_sync",
                    )
                    logger.debug("Created CRM contact from Neo4j entity: %s", email)

            elif entity_type == "company":
                name = p.get("name", "")
                if not name:
                    return
                companies = await self._crm.list_companies()
                if not any(c.name.lower() == name.lower() for c in companies):
                    await self._crm.create_company(
                        name=name,
                        region=p.get("region", ""),
                        industry=p.get("industry", ""),
                    )
                    logger.debug("Created CRM company from Neo4j entity: %s", name)

        except (DatabaseError, Exception):
            logger.exception("Neo4j→CRM sync failed for %s", event.entity_id)

    # ── Ledger queries ───────────────────────────────────────────────────

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the most recent events from the ledger."""
        if not self._ledger_path.exists():
            return []
        try:
            lines = self._ledger_path.read_text(encoding="utf-8").strip().split("\n")
            events = [json.loads(line) for line in lines[-limit:] if line.strip()]
            events.reverse()
            return events
        except (IraError, Exception):
            logger.debug("Ledger read failed", exc_info=True)
            return []

    def event_count(self) -> int:
        if not self._ledger_path.exists():
            return 0
        try:
            return sum(1 for _ in open(self._ledger_path, encoding="utf-8"))
        except (IraError, Exception):
            return 0
