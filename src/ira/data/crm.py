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
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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
)

from ira.config import get_settings
from ira.data.models import Channel, ContactType, DealStage, Direction, WarmthLevel

_str_uuid = lambda: str(uuid4())  # noqa: E731

logger = logging.getLogger(__name__)


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
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "source": self.source,
            "contact_type": self.contact_type.value if self.contact_type else None,
            "lead_score": self.lead_score,
            "warmth_level": self.warmth_level.value if self.warmth_level else None,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DealModel(Base):
    __tablename__ = "deals"

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

    def __init__(self, database_url: str | None = None, event_bus: Any | None = None) -> None:
        url = database_url or get_settings().database.url
        self._engine = create_async_engine(url, echo=False)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._event_bus = event_bus

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
        except Exception:
            logger.debug("CRM event emission failed for %s", event_type, exc_info=True)

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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
        await self._emit("contact_created", "contact", str(contact.id), contact.to_dict())
        return contact

    async def get_contact(self, contact_id: str | UUID) -> ContactModel | None:
        async with self._session_factory() as session:
            return await session.get(ContactModel, str(contact_id))

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
            contact = await session.get(ContactModel, str(contact_id))
            if not contact:
                return None
            for k, v in kwargs.items():
                setattr(contact, k, v)
            await session.commit()
            await session.refresh(contact)
        await self._emit("contact_updated", "contact", str(contact.id), contact.to_dict())
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
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

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

    async def update_deal(
        self, deal_id: str | UUID, **kwargs: Any
    ) -> DealModel | None:
        async with self._session_factory() as session:
            deal = await session.get(DealModel, str(deal_id))
            if not deal:
                return None
            for k, v in kwargs.items():
                setattr(deal, k, v)
            if "updated_at" not in kwargs:
                deal.updated_at = datetime.now(timezone.utc)
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
        self, filters: dict[str, Any] | None = None
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
        stmt = stmt.order_by(InteractionModel.created_at.desc())
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
            contacts = result.scalars().all()
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
