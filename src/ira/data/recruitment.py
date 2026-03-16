"""Recruitment database for Anu — candidates, stages, and pipeline events.

Uses the same PostgreSQL database as CRM. Tables: recruitment_candidates,
recruitment_stage_events. Provides RecruitmentStore for CRUD and stage tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ira.config import get_settings

logger = logging.getLogger(__name__)


def _str_uuid() -> str:
    return str(uuid4())


# Use same Base as CRM so migrations and engine are shared
from ira.data.crm import Base  # noqa: E402


# ── ORM models ─────────────────────────────────────────────────────────────


class RecruitmentCandidateModel(Base):
    """One row per candidate (keyed by email)."""

    __tablename__ = "recruitment_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    role_applied: Mapped[str | None] = mapped_column(String(255))
    profile_json: Mapped[dict | None] = mapped_column(JSON)
    cv_parsed_json: Mapped[dict | None] = mapped_column(JSON)
    score_json: Mapped[dict | None] = mapped_column(JSON)
    ctc_current: Mapped[str | None] = mapped_column(String(100))
    source_type: Mapped[str | None] = mapped_column(String(100))
    source_id: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    stage_events: Mapped[list["RecruitmentStageEventModel"]] = relationship(
        "RecruitmentStageEventModel",
        back_populates="candidate",
        order_by="RecruitmentStageEventModel.event_at",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "phone": self.phone,
            "role_applied": self.role_applied,
            "profile": self.profile_json or {},
            "cv_parsed": self.cv_parsed_json,
            "score": self.score_json or {},
            "ctc_current": self.ctc_current,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RecruitmentStageEventModel(Base):
    """Stage progression and email/call events per candidate."""

    __tablename__ = "recruitment_stage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recruitment_candidates.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    candidate: Mapped[RecruitmentCandidateModel] = relationship(
        "RecruitmentCandidateModel", back_populates="stage_events"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "stage": self.stage,
            "event_at": self.event_at.isoformat() if self.event_at else None,
            "metadata": self.metadata_json or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── RecruitmentStore ─────────────────────────────────────────────────────────


class RecruitmentStore:
    """Async store for recruitment candidates and stage events (PostgreSQL)."""

    _instances: dict[str, RecruitmentStore] = {}

    def __new__(cls, database_url: str | None = None, **kwargs: Any) -> RecruitmentStore:
        url = database_url or get_settings().database.url
        if url not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[url] = instance
        return cls._instances[url]

    def __init__(self, database_url: str | None = None, **kwargs: Any) -> None:
        if getattr(self, "_initialized", False):
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
        self._initialized = True

    @classmethod
    def _reset_instances(cls) -> None:
        """Reset singleton instances (for testing only)."""
        cls._instances.clear()

    async def upsert_candidate(
        self,
        email: str,
        *,
        name: str | None = None,
        phone: str | None = None,
        role_applied: str | None = None,
        profile: dict[str, Any] | None = None,
        cv_parsed: dict[str, Any] | None = None,
        score: dict[str, Any] | None = None,
        ctc_current: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        notes: str | None = None,
    ) -> RecruitmentCandidateModel:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("Invalid email")
        async with self._session_factory() as session:
            result = await session.execute(
                select(RecruitmentCandidateModel).where(
                    RecruitmentCandidateModel.email == email
                )
            )
            row = result.scalar_one_or_none()
            if row:
                if name is not None:
                    row.name = name
                if phone is not None:
                    row.phone = phone
                if role_applied is not None:
                    row.role_applied = role_applied
                if profile is not None:
                    row.profile_json = profile
                if cv_parsed is not None:
                    row.cv_parsed_json = cv_parsed
                if score is not None:
                    row.score_json = score
                if ctc_current is not None:
                    row.ctc_current = ctc_current
                if source_type is not None:
                    row.source_type = source_type
                if source_id is not None:
                    row.source_id = source_id
                if notes is not None:
                    row.notes = notes
                await session.commit()
                await session.refresh(row)
                return row
            candidate = RecruitmentCandidateModel(
                email=email,
                name=name,
                phone=phone,
                role_applied=role_applied,
                profile_json=profile,
                cv_parsed_json=cv_parsed,
                score_json=score,
                ctc_current=ctc_current,
                source_type=source_type,
                source_id=source_id,
                notes=notes,
            )
            session.add(candidate)
            await session.commit()
            await session.refresh(candidate)
            return candidate

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        email = (email or "").strip().lower()
        async with self._session_factory() as session:
            result = await session.execute(
                select(RecruitmentCandidateModel)
                .where(RecruitmentCandidateModel.email == email)
                .options(
                    *[]  # can add selectinload(RecruitmentCandidateModel.stage_events)
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            d = row.to_dict()
            result_events = await session.execute(
                select(RecruitmentStageEventModel)
                .where(RecruitmentStageEventModel.candidate_id == row.id)
                .order_by(RecruitmentStageEventModel.event_at.desc())
            )
            d["stage_events"] = [e.to_dict() for e in result_events.scalars().all()]
            return d

    async def update_cv_parsed(self, email: str, cv_profile: dict[str, Any]) -> None:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("Invalid email")
        async with self._session_factory() as session:
            result = await session.execute(
                select(RecruitmentCandidateModel).where(
                    RecruitmentCandidateModel.email == email
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.cv_parsed_json = cv_profile
                await session.commit()
            else:
                candidate = RecruitmentCandidateModel(
                    email=email, cv_parsed_json=cv_profile
                )
                session.add(candidate)
                await session.commit()

    async def add_stage_event(
        self,
        email: str,
        stage: str,
        *,
        event_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RecruitmentStageEventModel | None:
        email = (email or "").strip().lower()
        async with self._session_factory() as session:
            result = await session.execute(
                select(RecruitmentCandidateModel).where(
                    RecruitmentCandidateModel.email == email
                )
            )
            candidate = result.scalar_one_or_none()
            if not candidate:
                logger.warning("RecruitmentStore.add_stage_event: no candidate for %s", email)
                return None
            event = RecruitmentStageEventModel(
                candidate_id=candidate.id,
                stage=stage,
                event_at=event_at or datetime.now(timezone.utc),
                metadata_json=metadata or {},
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    async def list_candidates(
        self,
        limit: int = 200,
        offset: int = 0,
        role_applied: str | None = None,
        stage: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(RecruitmentCandidateModel).order_by(
            RecruitmentCandidateModel.updated_at.desc()
        )
        if role_applied:
            stmt = stmt.where(RecruitmentCandidateModel.role_applied == role_applied)
        if stage:
            subq = (
                select(RecruitmentStageEventModel.candidate_id)
                .where(RecruitmentStageEventModel.stage == stage)
                .distinct()
            )
            stmt = stmt.where(RecruitmentCandidateModel.id.in_(subq))
        stmt = stmt.limit(limit).offset(offset)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [row.to_dict() for row in rows]

    async def count(self) -> int:
        from sqlalchemy import func
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(RecruitmentCandidateModel.id))
            )
            return int(result.scalar() or 0)
