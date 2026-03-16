"""CRM database layer using SQLAlchemy 2.0 async ORM.

Defines the relational schema for Machinecraft's CRM (companies, contacts,
deals, interactions, drip campaigns) and exposes a :class:`CRMDatabase`
service class with CRUD, analytics, and protocol-compatible query methods.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)

from ira.config import get_settings
from ira.data.models import Channel, ContactType, DealStage, Direction, WarmthLevel
from ira.exceptions import IraError

_str_uuid = lambda: str(uuid4())  # noqa: E731

logger = logging.getLogger(__name__)

_LEAD_EXCLUSION_LIST_PATH = Path(__file__).resolve().parents[3] / "data" / "knowledge" / "lead_campaign_exclusion_list.txt"


def _load_lead_campaign_excluded_emails() -> set[str]:
    """Load emails excluded from lead campaigns (agency/partner, not customers). One email per line; # = comment."""
    excluded: set[str] = set()
    if not _LEAD_EXCLUSION_LIST_PATH.exists():
        return excluded
    try:
        for line in _LEAD_EXCLUSION_LIST_PATH.read_text(encoding="utf-8").splitlines():
            s = line.strip().lower()
            if s and not s.startswith("#") and "@" in s:
                excluded.add(s)
    except Exception as e:
        logger.warning("Could not load lead exclusion list %s: %s", _LEAD_EXCLUSION_LIST_PATH, e)
    return excluded


# ── SQLAlchemy declarative base ──────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────


class CampaignStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


# ── ORM Models ──────────────────────────────────────────────────────────────


class CompanyModel(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(500))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    contacts: Mapped[list[ContactModel]] = relationship(back_populates="company")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "region": self.region,
            "industry": self.industry,
            "website": self.website,
            "employee_count": self.employee_count,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ContactModel(Base):
    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    company_id: Mapped[UUID | None] = mapped_column(
        String(36), ForeignKey("companies.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(100))
    lead_score: Mapped[float] = mapped_column(Float, default=0.0)
    contact_type: Mapped[str | None] = mapped_column(
        Enum(ContactType, native_enum=False, create_constraint=False),
    )
    warmth_level: Mapped[str | None] = mapped_column(
        Enum(WarmthLevel, native_enum=False, create_constraint=False),
    )
    tags: Mapped[dict | None] = mapped_column(JSON)
    account_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    company: Mapped[CompanyModel | None] = relationship(back_populates="contacts")
    deals: Mapped[list[DealModel]] = relationship(back_populates="contact")
    interactions: Mapped[list[InteractionModel]] = relationship(back_populates="contact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "company_id": str(self.company_id) if self.company_id else None,
            "company_name": self.company.name if self.company is not None else None,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "source": self.source,
            "contact_type": self.contact_type.value if self.contact_type else None,
            "lead_score": self.lead_score,
            "warmth_level": self.warmth_level.value if self.warmth_level else None,
            "tags": self.tags,
            "account_summary": self.account_summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DealModel(Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("value >= 0", name="ck_deals_value_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    contact_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("contacts.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    stage: Mapped[str] = mapped_column(
        Enum(DealStage, native_enum=False, create_constraint=False),
        default=DealStage.NEW,
    )
    machine_model: Mapped[str | None] = mapped_column(String(255))
    application: Mapped[str | None] = mapped_column(String(255))
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime)
    actual_close_date: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    contact: Mapped[ContactModel] = relationship(back_populates="deals")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "contact_id": str(self.contact_id),
            "title": self.title,
            "value": float(self.value) if self.value else 0,
            "currency": self.currency,
            "stage": self.stage.value if isinstance(self.stage, DealStage) else self.stage,
            "machine_model": self.machine_model,
            "application": self.application,
            "expected_close_date": (
                self.expected_close_date.isoformat() if self.expected_close_date else None
            ),
            "actual_close_date": (
                self.actual_close_date.isoformat() if self.actual_close_date else None
            ),
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InteractionModel(Base):
    __tablename__ = "interactions"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    contact_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("contacts.id"), nullable=False
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        String(36), ForeignKey("deals.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(
        Enum(Channel, native_enum=False, create_constraint=False),
    )
    direction: Mapped[str] = mapped_column(
        Enum(Direction, native_enum=False, create_constraint=False),
    )
    subject: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contact: Mapped[ContactModel] = relationship(back_populates="interactions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "contact_id": str(self.contact_id),
            "deal_id": str(self.deal_id) if self.deal_id else None,
            "channel": self.channel.value if isinstance(self.channel, Channel) else self.channel,
            "direction": (
                self.direction.value if isinstance(self.direction, Direction) else self.direction
            ),
            "subject": self.subject,
            "content": self.content,
            "sentiment": self.sentiment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DripCampaignModel(Base):
    __tablename__ = "drip_campaigns"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_segment: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        Enum(CampaignStatus, native_enum=False, create_constraint=False),
        default=CampaignStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    steps: Mapped[list[DripStepModel]] = relationship(back_populates="campaign")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "target_segment": self.target_segment,
            "status": (
                self.status.value
                if isinstance(self.status, CampaignStatus)
                else self.status
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DripStepModel(Base):
    __tablename__ = "drip_steps"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    campaign_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("drip_campaigns.id"), nullable=False
    )
    contact_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("contacts.id"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    email_subject: Mapped[str | None] = mapped_column(String(500))
    email_body: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    reply_received: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_content: Mapped[str | None] = mapped_column(Text)
    opened: Mapped[bool] = mapped_column(Boolean, default=False)

    campaign: Mapped[DripCampaignModel] = relationship(back_populates="steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "campaign_id": str(self.campaign_id),
            "contact_id": str(self.contact_id),
            "step_number": self.step_number,
            "email_subject": self.email_subject,
            "email_body": self.email_body,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "reply_received": self.reply_received,
            "reply_content": self.reply_content,
            "opened": self.opened,
        }


# ── CRMDatabase service ─────────────────────────────────────────────────────


class CRMDatabase:
    """Async CRM service backed by PostgreSQL (or SQLite for tests)."""

    _instances: dict[str, CRMDatabase] = {}

    def __new__(cls, database_url: str | None = None, **kwargs: Any) -> CRMDatabase:
        url = database_url or get_settings().database.url
        if url not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[url] = instance
        return cls._instances[url]

    def __init__(self, database_url: str | None = None, event_bus: Any | None = None) -> None:
        if self._initialized:
            return
        url = database_url or get_settings().database.url
        self._engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._event_bus = event_bus
        self._closed = False
        self._initialized = True

    @classmethod
    def _reset_instances(cls) -> None:
        """Reset singleton instances (for testing only)."""
        cls._instances.clear()

    def set_event_bus(self, event_bus: Any) -> None:
        """Late-bind the event bus after construction."""
        self._event_bus = event_bus

    async def _emit(self, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
        try:
            await self._event_bus.emit(DataEvent(
                event_type=EventType(event_type),
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
                source_store=SourceStore.CRM,
            ))
        except (IraError, Exception):
            logger.debug("CRM event emission failed for %s", event_type, exc_info=True)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Dispose the SQLAlchemy engine (idempotent)."""
        if self._closed:
            return
        await self._engine.dispose()
        self._closed = True

    # ── Company CRUD ─────────────────────────────────────────────────────

    async def create_company(self, **kwargs: Any) -> CompanyModel:
        company = CompanyModel(**kwargs)
        async with self._session_factory() as session:
            session.add(company)
            await session.commit()
            await session.refresh(company)
        await self._emit("company_created", "company", str(company.id), company.to_dict())
        return company

    async def get_company(self, company_id: str | UUID) -> CompanyModel | None:
        async with self._session_factory() as session:
            return await session.get(CompanyModel, str(company_id))

    async def update_company(
        self, company_id: str | UUID, **kwargs: Any
    ) -> CompanyModel | None:
        async with self._session_factory() as session:
            company = await session.get(CompanyModel, str(company_id))
            if not company:
                return None
            for k, v in kwargs.items():
                setattr(company, k, v)
            await session.commit()
            await session.refresh(company)
        return company

    async def list_companies(
        self, filters: dict[str, Any] | None = None
    ) -> list[CompanyModel]:
        stmt = select(CompanyModel)
        if filters:
            if "region" in filters:
                stmt = stmt.where(CompanyModel.region == filters["region"])
            if "industry" in filters:
                stmt = stmt.where(CompanyModel.industry == filters["industry"])
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Contact CRUD ─────────────────────────────────────────────────────

    async def create_contact(self, **kwargs: Any) -> ContactModel:
        contact = ContactModel(**kwargs)
        async with self._session_factory() as session:
            session.add(contact)
            await session.commit()
            await session.refresh(contact)
            # Eager-load company so to_dict() works after session closes (async-safe)
            result = await session.execute(
                select(ContactModel).options(selectinload(ContactModel.company)).where(ContactModel.id == contact.id)
            )
            contact = result.unique().scalar_one()
        await self._emit("contact_created", "contact", str(contact.id), contact.to_dict())
        return contact

    async def get_contact(self, contact_id: str | UUID) -> ContactModel | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ContactModel)
                .options(selectinload(ContactModel.company))
                .where(ContactModel.id == str(contact_id))
            )
            return result.unique().scalar_one_or_none()

    async def get_contact_by_email(self, email: str) -> ContactModel | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ContactModel).where(ContactModel.email == email)
            )
            return result.scalar_one_or_none()

    async def update_contact(
        self, contact_id: str | UUID, **kwargs: Any
    ) -> ContactModel | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ContactModel)
                .options(selectinload(ContactModel.company))
                .where(ContactModel.id == str(contact_id))
            )
            contact = result.unique().scalar_one_or_none()
            if not contact:
                return None
            for k, v in kwargs.items():
                setattr(contact, k, v)
            await session.commit()
            await session.refresh(contact)
            payload = contact.to_dict()
        await self._emit("contact_updated", "contact", str(contact.id), payload)
        return contact

    async def list_contacts(
        self, filters: dict[str, Any] | None = None
    ) -> list[ContactModel]:
        stmt = select(ContactModel)
        if filters:
            if "region" in filters:
                stmt = stmt.join(CompanyModel, isouter=True).where(
                    CompanyModel.region == filters["region"]
                )
            if "industry" in filters:
                stmt = stmt.join(CompanyModel, isouter=True).where(
                    CompanyModel.industry == filters["industry"]
                )
            if "contact_type" in filters:
                ct = filters["contact_type"]
                if isinstance(ct, list):
                    stmt = stmt.where(ContactModel.contact_type.in_(ct))
                else:
                    stmt = stmt.where(ContactModel.contact_type == ct)
            if "warmth_level" in filters:
                levels = filters["warmth_level"]
                if isinstance(levels, list):
                    stmt = stmt.where(ContactModel.warmth_level.in_(levels))
                else:
                    stmt = stmt.where(ContactModel.warmth_level == levels)
            if "lead_score_min" in filters:
                stmt = stmt.where(ContactModel.lead_score >= filters["lead_score_min"])
            if "lead_score_max" in filters:
                stmt = stmt.where(ContactModel.lead_score <= filters["lead_score_max"])
        stmt = stmt.options(selectinload(ContactModel.company))
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.unique().scalars().all())

    # ── Deal CRUD ────────────────────────────────────────────────────────

    async def create_deal(self, **kwargs: Any) -> DealModel:
        deal = DealModel(**kwargs)
        async with self._session_factory() as session:
            session.add(deal)
            await session.commit()
            await session.refresh(deal)
        await self._emit("deal_created", "deal", str(deal.id), deal.to_dict())
        return deal

    async def get_deal(self, deal_id: str | UUID) -> DealModel | None:
        async with self._session_factory() as session:
            return await session.get(DealModel, str(deal_id))

    _VALID_STAGE_TRANSITIONS: dict[DealStage, set[DealStage]] = {
        DealStage.NEW: {DealStage.CONTACTED, DealStage.ENGAGED, DealStage.LOST},
        DealStage.CONTACTED: {DealStage.ENGAGED, DealStage.QUALIFIED, DealStage.LOST},
        DealStage.ENGAGED: {DealStage.QUALIFIED, DealStage.PROPOSAL, DealStage.LOST},
        DealStage.QUALIFIED: {DealStage.PROPOSAL, DealStage.LOST},
        DealStage.PROPOSAL: {DealStage.NEGOTIATION, DealStage.WON, DealStage.LOST},
        DealStage.NEGOTIATION: {DealStage.WON, DealStage.LOST},
        DealStage.WON: set(),
        DealStage.LOST: {DealStage.NEW},
    }

    async def update_deal(
        self, deal_id: str | UUID, force: bool = False, **kwargs: Any
    ) -> DealModel | None:
        if "value" in kwargs and kwargs["value"] is not None and kwargs["value"] < 0:
            raise ValueError("Deal value cannot be negative")

        async with self._session_factory() as session:
            deal = await session.get(DealModel, str(deal_id))
            if not deal:
                return None

            if "stage" in kwargs and not force:
                new_stage = kwargs["stage"]
                if isinstance(new_stage, str):
                    new_stage = DealStage(new_stage)
                current = deal.stage if isinstance(deal.stage, DealStage) else DealStage(deal.stage)
                valid = self._VALID_STAGE_TRANSITIONS.get(current, set())
                if new_stage not in valid:
                    logger.warning(
                        "Invalid stage transition %s -> %s for deal %s (use force=True to override)",
                        current.value, new_stage.value, deal_id,
                    )

            for k, v in kwargs.items():
                setattr(deal, k, v)
            if "updated_at" not in kwargs:
                # Column is TIMESTAMP WITHOUT TIME ZONE; use naive UTC for asyncpg
                deal.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
            await session.refresh(deal)
        await self._emit("deal_updated", "deal", str(deal.id), deal.to_dict())
        return deal

    async def list_deals(
        self, filters: dict[str, Any] | None = None
    ) -> list[DealModel]:
        stmt = select(DealModel)
        if filters:
            if "contact_id" in filters:
                stmt = stmt.where(DealModel.contact_id == str(filters["contact_id"]))
            if "stage" in filters:
                stmt = stmt.where(DealModel.stage == filters["stage"])
            if "machine_model" in filters:
                stmt = stmt.where(DealModel.machine_model == filters["machine_model"])
            if "date_from" in filters:
                stmt = stmt.where(DealModel.created_at >= filters["date_from"])
            if "date_to" in filters:
                stmt = stmt.where(DealModel.created_at <= filters["date_to"])
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_deals_with_details(
        self, limit: int = 200
    ) -> list[dict[str, Any]]:
        """List deals with contact and company loaded for dashboard/API."""
        stmt = (
            select(DealModel)
            .options(selectinload(DealModel.contact).selectinload(ContactModel.company))
            .order_by(DealModel.updated_at.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            deals = list(result.scalars().unique().all())
        out: list[dict[str, Any]] = []
        for d in deals:
            contact = d.contact
            company_name = contact.company.name if contact and contact.company else None
            out.append({
                "id": str(d.id),
                "title": d.title,
                "stage": d.stage.value if isinstance(d.stage, DealStage) else str(d.stage),
                "value": float(d.value) if d.value else 0,
                "currency": d.currency or "USD",
                "machine_model": d.machine_model,
                "application": d.application,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "contact_id": str(d.contact_id),
                "contact_name": contact.name if contact else None,
                "contact_email": contact.email if contact else None,
                "contact_type": contact.contact_type.value if contact and contact.contact_type else None,
                "company_name": company_name,
                "account_summary": contact.account_summary if contact else None,
            })
        return out

    async def list_deals_with_heat(
        self,
        limit: int = 200,
        sort_heat: str = "desc",
    ) -> list[dict[str, Any]]:
        """List deals with contact/company and a heat score (hottest = we sent quote and customer replied).

        Heat: 2 = has outbound + inbound (quote sent, they replied), 1 = outbound only, 0 = else.
        sort_heat: 'desc' = hottest first, 'asc' = least hot first.
        """
        # Per-contact interaction flags in one query
        outbound = (
            select(InteractionModel.contact_id)
            .where(InteractionModel.direction == Direction.OUTBOUND)
            .distinct()
        )
        inbound = (
            select(InteractionModel.contact_id)
            .where(InteractionModel.direction == Direction.INBOUND)
            .distinct()
        )
        async with self._session_factory() as session:
            out_res = await session.execute(outbound)
            inbound_res = await session.execute(inbound)
        contact_has_outbound = {str(r[0]) for r in out_res.all()}
        contact_has_inbound = {str(r[0]) for r in inbound_res.all()}

        def heat_for_contact(cid: str | None) -> int:
            if not cid:
                return 0
            o = cid in contact_has_outbound
            i = cid in contact_has_inbound
            if o and i:
                return 2
            if o:
                return 1
            return 0

        deals = await self.list_deals_with_details(limit=limit)
        for d in deals:
            cid = d.get("contact_id")
            h = heat_for_contact(cid)
            d["heat_score"] = h
            d["heat_label"] = "hot" if h == 2 else ("warm" if h == 1 else "cold")
        reverse = sort_heat.lower() == "desc"
        deals.sort(key=lambda x: (x["heat_score"], x.get("updated_at") or ""), reverse=reverse)
        return deals

    async def list_deals_with_lead_score(
        self,
        limit: int = 200,
        sort_by_score: str = "desc",
        engagement_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List deals with contact/company and a 0–100 lead score (order size, interest, stage, customer, meeting).

        Uses lead_ranker formula; see data/knowledge/lead_ranker_formula.md.
        sort_by_score: 'desc' = hottest first.
        engagement_only: if True, only include deals where the lead has replied at least once (inbound email).
        Excludes list-import / no-thread records that are not genuine leads.
        """
        from ira.brain.lead_ranker import (
            had_meeting_or_web_call,
            score_lead,
        )

        deals = await self.list_deals_with_details(limit=limit * 3)
        if not deals:
            return []

        contact_ids = [d["contact_id"] for d in deals if d.get("contact_id")]
        if not contact_ids:
            for d in deals:
                d["lead_score"] = 0
                d["lead_score_breakdown"] = {}
            return deals[:limit]

        # Per-contact: inbound count; channels (for meeting/web); last outbound (email) for "last email we sent"
        stmt = select(
            InteractionModel.contact_id,
            InteractionModel.channel,
            InteractionModel.direction,
        ).where(InteractionModel.contact_id.in_(contact_ids))
        stmt_last_out = (
            select(
                InteractionModel.contact_id,
                InteractionModel.subject,
                InteractionModel.content,
                InteractionModel.created_at,
            )
            .where(
                InteractionModel.contact_id.in_(contact_ids),
                InteractionModel.direction == Direction.OUTBOUND,
            )
            .order_by(InteractionModel.created_at.desc())
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()
            result_last = await session.execute(stmt_last_out)
            rows_last = result_last.all()

        contact_inbound_count: dict[str, int] = {cid: 0 for cid in contact_ids}
        contact_channels: dict[str, list[str]] = {cid: [] for cid in contact_ids}
        last_outbound_by_contact: dict[str, dict[str, Any]] = {}
        for contact_id, subject, content, created_at in rows_last:
            cid = str(contact_id)
            if cid not in last_outbound_by_contact:
                last_outbound_by_contact[cid] = {
                    "last_email_sent_at": created_at.isoformat() if created_at else None,
                    "last_email_subject": (subject or "")[:500] if subject else None,
                    "last_email_preview": (content or "")[:400].strip() if content else None,
                }
        for contact_id, channel, direction in rows:
            cid = str(contact_id)
            if cid not in contact_inbound_count:
                continue
            contact_channels[cid].append(channel.value if isinstance(channel, Channel) else str(channel))
            if direction == Direction.INBOUND:
                contact_inbound_count[cid] = contact_inbound_count.get(cid, 0) + 1

        # Simple USD conversion for value (approximate)
        def to_usd(value: float, currency: str | None) -> float:
            if not value or value <= 0:
                return 0.0
            c = (currency or "USD").strip().upper()
            if c in ("USD", "$"):
                return float(value)
            if c in ("EUR", "€"):
                return float(value) * 1.08
            if c in ("INR", "Rs"):
                return float(value) / 83.0
            return float(value)

        for d in deals:
            cid = d.get("contact_id")
            value_usd = to_usd(d.get("value") or 0, d.get("currency"))
            stage = d.get("stage")
            contact_type = d.get("contact_type")
            emails_from_them = contact_inbound_count.get(cid, 0) if cid else 0
            had_meeting = had_meeting_or_web_call(contact_channels.get(cid))

            score, breakdown = score_lead(
                value_usd=value_usd,
                stage=stage,
                contact_type=contact_type,
                emails_from_them=emails_from_them or None,
                had_meeting_or_web_call=had_meeting,
            )
            d["lead_score"] = score
            d["lead_score_breakdown"] = breakdown
            last_out = last_outbound_by_contact.get(cid) if cid else None
            d["last_email_sent_at"] = last_out.get("last_email_sent_at") if last_out else None
            d["last_email_subject"] = last_out.get("last_email_subject") if last_out else None
            d["last_email_preview"] = last_out.get("last_email_preview") if last_out else None

        if engagement_only:
            # Only include deals where the lead has replied at least once (genuine lead).
            deals = [d for d in deals if (contact_inbound_count.get(d.get("contact_id") or "", 0) or 0) >= 1]

        # Exclude contacts on the lead-campaign exclusion list (agency/partner, not customers).
        excluded_emails = _load_lead_campaign_excluded_emails()
        if excluded_emails:
            deals = [d for d in deals if (d.get("contact_email") or "").strip().lower() not in excluded_emails]

        reverse = sort_by_score.lower() == "desc"
        deals.sort(key=lambda x: (x.get("lead_score") or 0, x.get("updated_at") or ""), reverse=reverse)
        return deals[:limit]

    # ── Interaction CRUD ─────────────────────────────────────────────────

    async def create_interaction(self, **kwargs: Any) -> InteractionModel:
        interaction = InteractionModel(**kwargs)
        async with self._session_factory() as session:
            session.add(interaction)
            await session.commit()
            await session.refresh(interaction)
        await self._emit("interaction_logged", "interaction", str(interaction.id), interaction.to_dict())
        return interaction

    async def get_interaction(
        self, interaction_id: str | UUID
    ) -> InteractionModel | None:
        async with self._session_factory() as session:
            return await session.get(InteractionModel, str(interaction_id))

    async def list_interactions(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[InteractionModel]:
        stmt = select(InteractionModel)
        if filters:
            if "contact_id" in filters:
                stmt = stmt.where(
                    InteractionModel.contact_id == str(filters["contact_id"])
                )
            if "deal_id" in filters:
                stmt = stmt.where(InteractionModel.deal_id == str(filters["deal_id"]))
            if "channel" in filters:
                stmt = stmt.where(InteractionModel.channel == filters["channel"])
            if "direction" in filters:
                stmt = stmt.where(InteractionModel.direction == filters["direction"])
        stmt = stmt.order_by(InteractionModel.created_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count_interactions(self) -> int:
        """Return the total number of interactions in the CRM."""
        stmt = select(func.count(InteractionModel.id))
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar_one()

    # ── DripCampaign CRUD ────────────────────────────────────────────────

    async def create_campaign(self, **kwargs: Any) -> DripCampaignModel:
        campaign = DripCampaignModel(**kwargs)
        async with self._session_factory() as session:
            session.add(campaign)
            await session.commit()
            await session.refresh(campaign)
        return campaign

    async def get_campaign(
        self, campaign_id: str | UUID
    ) -> DripCampaignModel | None:
        async with self._session_factory() as session:
            return await session.get(DripCampaignModel, str(campaign_id))

    async def update_campaign(
        self, campaign_id: str | UUID, **kwargs: Any
    ) -> DripCampaignModel | None:
        async with self._session_factory() as session:
            campaign = await session.get(DripCampaignModel, str(campaign_id))
            if not campaign:
                return None
            for k, v in kwargs.items():
                setattr(campaign, k, v)
            await session.commit()
            await session.refresh(campaign)
        return campaign

    async def list_campaigns(
        self, filters: dict[str, Any] | None = None
    ) -> list[DripCampaignModel]:
        stmt = select(DripCampaignModel)
        if filters:
            if "status" in filters:
                stmt = stmt.where(DripCampaignModel.status == filters["status"])
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── DripStep CRUD ────────────────────────────────────────────────────

    async def create_drip_step(self, **kwargs: Any) -> DripStepModel:
        step = DripStepModel(**kwargs)
        async with self._session_factory() as session:
            session.add(step)
            await session.commit()
            await session.refresh(step)
        return step

    async def get_drip_step(self, step_id: str | UUID) -> DripStepModel | None:
        async with self._session_factory() as session:
            return await session.get(DripStepModel, str(step_id))

    async def update_drip_step(
        self, step_id: str | UUID, **kwargs: Any
    ) -> DripStepModel | None:
        async with self._session_factory() as session:
            step = await session.get(DripStepModel, str(step_id))
            if not step:
                return None
            for k, v in kwargs.items():
                setattr(step, k, v)
            await session.commit()
            await session.refresh(step)
        return step

    async def list_drip_steps(
        self, filters: dict[str, Any] | None = None
    ) -> list[DripStepModel]:
        stmt = select(DripStepModel)
        if filters:
            if "campaign_id" in filters:
                stmt = stmt.where(
                    DripStepModel.campaign_id == str(filters["campaign_id"])
                )
            if "contact_id" in filters:
                stmt = stmt.where(
                    DripStepModel.contact_id == str(filters["contact_id"])
                )
            if "sent" in filters:
                if filters["sent"]:
                    stmt = stmt.where(DripStepModel.sent_at.is_not(None))
                else:
                    stmt = stmt.where(DripStepModel.sent_at.is_(None))
        stmt = stmt.order_by(DripStepModel.step_number)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Analytics ────────────────────────────────────────────────────────

    async def get_pipeline_summary(
        self, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        stmt = select(
            DealModel.stage,
            func.count(DealModel.id).label("count"),
            func.sum(DealModel.value).label("total_value"),
        ).group_by(DealModel.stage)

        if filters:
            if "machine_model" in filters:
                stmt = stmt.where(DealModel.machine_model == filters["machine_model"])
            if "date_from" in filters:
                stmt = stmt.where(DealModel.created_at >= filters["date_from"])
            if "date_to" in filters:
                stmt = stmt.where(DealModel.created_at <= filters["date_to"])

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        stages: dict[str, Any] = {}
        total_count = 0
        total_value = Decimal(0)
        for stage, count, value in rows:
            stage_name = stage.value if isinstance(stage, DealStage) else stage
            val = value or Decimal(0)
            stages[stage_name] = {"count": count, "total_value": float(val)}
            total_count += count
            total_value += val

        return {
            "stages": stages,
            "total_count": total_count,
            "total_value": float(total_value),
        }

    async def get_stale_leads(self, days: int = 14) -> list[dict[str, Any]]:
        cutoff = datetime.utcnow() - timedelta(days=days)

        latest_interaction = (
            select(
                InteractionModel.contact_id,
                func.max(InteractionModel.created_at).label("last_interaction"),
            )
            .group_by(InteractionModel.contact_id)
            .subquery()
        )

        stmt = (
            select(ContactModel)
            .outerjoin(
                latest_interaction,
                ContactModel.id == latest_interaction.c.contact_id,
            )
            .where(
                or_(
                    latest_interaction.c.last_interaction.is_(None),
                    latest_interaction.c.last_interaction < cutoff,
                )
            )
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            contacts = result.scalars().all()

        return [c.to_dict() for c in contacts]

    async def get_deal_velocity(self) -> dict[str, Any]:
        stmt = select(
            DealModel.stage,
            DealModel.created_at,
            DealModel.updated_at,
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        stage_days: dict[str, list[float]] = {}
        for stage, created_at, updated_at in rows:
            stage_name = stage.value if isinstance(stage, DealStage) else stage
            if created_at and updated_at:
                delta = (updated_at - created_at).total_seconds() / 86400.0
                stage_days.setdefault(stage_name, []).append(delta)

        velocity: dict[str, float] = {}
        for stage_name, days_list in stage_days.items():
            velocity[stage_name] = round(sum(days_list) / len(days_list), 2) if days_list else 0.0

        return {"stage_velocity_days": velocity}

    async def search_contacts(self, query: str) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        stmt = (
            select(ContactModel)
            .options(selectinload(ContactModel.company))
            .outerjoin(CompanyModel, ContactModel.company_id == CompanyModel.id)
            .where(
                or_(
                    ContactModel.name.ilike(pattern),
                    ContactModel.email.ilike(pattern),
                    CompanyModel.name.ilike(pattern),
                )
            )
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            contacts = result.unique().scalars().all()
        return [c.to_dict() for c in contacts]

    # ── Protocol-compatible wrappers ─────────────────────────────────────
    # These return plain dicts to satisfy SalesCRMRepository and CRMRepository.

    async def get_deals_for_contact(
        self, contact_id: str
    ) -> list[dict[str, Any]]:
        deals = await self.list_deals(filters={"contact_id": contact_id})
        return [d.to_dict() for d in deals]

    async def get_interactions_for_contact(
        self, contact_id: str
    ) -> list[dict[str, Any]]:
        interactions = await self.list_interactions(
            filters={"contact_id": contact_id}
        )
        return [i.to_dict() for i in interactions]

    async def get_deals_by_filter(
        self, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        deals = await self.list_deals(filters=filters)
        return [d.to_dict() for d in deals]

    async def get_contact_dict(
        self, contact_id: str
    ) -> dict[str, Any] | None:
        contact = await self.get_contact(contact_id)
        return contact.to_dict() if contact else None
