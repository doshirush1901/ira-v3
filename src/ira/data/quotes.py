"""Quote lifecycle management for Machinecraft.

Defines the :class:`QuoteModel` ORM table and a :class:`QuoteManager` service
that handles the full quote lifecycle — from inquiry extraction through
pricing, follow-ups, deal linking, and analytics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ira.config import get_settings
from ira.data.crm import Base
from ira.data.models import Contact

_str_uuid = lambda: str(uuid4())  # noqa: E731

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────────────


class QuoteStatus(str, PyEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    FOLLOW_UP_1 = "FOLLOW_UP_1"
    FOLLOW_UP_2 = "FOLLOW_UP_2"
    FOLLOW_UP_3 = "FOLLOW_UP_3"
    WON = "WON"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


# ── ORM Model ───────────────────────────────────────────────────────────────


class QuoteModel(Base):
    __tablename__ = "quotes"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    contact_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("contacts.id"), nullable=False
    )
    deal_id: Mapped[UUID | None] = mapped_column(
        String(36), ForeignKey("deals.id"), nullable=True
    )
    company_name: Mapped[str | None] = mapped_column(String(255))
    machine_model: Mapped[str | None] = mapped_column(String(255))
    configuration: Mapped[dict | None] = mapped_column(JSON)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    status: Mapped[str] = mapped_column(
        Enum(QuoteStatus, native_enum=False, create_constraint=False),
        default=QuoteStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "contact_id": str(self.contact_id),
            "deal_id": str(self.deal_id) if self.deal_id else None,
            "company_name": self.company_name,
            "machine_model": self.machine_model,
            "configuration": self.configuration,
            "estimated_value": float(self.estimated_value) if self.estimated_value else None,
            "currency": self.currency,
            "status": (
                self.status.value if isinstance(self.status, QuoteStatus) else self.status
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "last_follow_up_at": (
                self.last_follow_up_at.isoformat() if self.last_follow_up_at else None
            ),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "notes": self.notes,
        }


# ── LLM prompt for inquiry extraction ───────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = """\
You are a sales analyst for Machinecraft, an industrial machinery manufacturer.
Extract the machine model and configuration from the customer inquiry.

Return ONLY valid JSON (no markdown fences):
{"machine_model": "model name", "configuration": {"key": "value"}}

If you cannot determine the machine model, use "UNKNOWN".
"""


# ── QuoteManager service ────────────────────────────────────────────────────


class QuoteManager:
    """Manages the full quote lifecycle from inquiry to close."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def create_quote(self, **kwargs: Any) -> QuoteModel:
        quote = QuoteModel(**kwargs)
        async with self._session_factory() as session:
            session.add(quote)
            await session.commit()
            await session.refresh(quote)
        return quote

    async def get_quote(self, quote_id: str | UUID) -> QuoteModel | None:
        async with self._session_factory() as session:
            return await session.get(QuoteModel, str(quote_id))

    async def update_quote(
        self, quote_id: str | UUID, **kwargs: Any
    ) -> QuoteModel | None:
        async with self._session_factory() as session:
            quote = await session.get(QuoteModel, str(quote_id))
            if not quote:
                return None
            for k, v in kwargs.items():
                setattr(quote, k, v)
            await session.commit()
            await session.refresh(quote)
        return quote

    async def list_quotes(
        self, filters: dict[str, Any] | None = None
    ) -> list[QuoteModel]:
        stmt = select(QuoteModel)
        if filters:
            if "contact_id" in filters:
                stmt = stmt.where(QuoteModel.contact_id == str(filters["contact_id"]))
            if "status" in filters:
                stmt = stmt.where(QuoteModel.status == filters["status"])
            if "machine_model" in filters:
                stmt = stmt.where(QuoteModel.machine_model == filters["machine_model"])
            if "date_from" in filters:
                stmt = stmt.where(QuoteModel.created_at >= filters["date_from"])
            if "date_to" in filters:
                stmt = stmt.where(QuoteModel.created_at <= filters["date_to"])
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Lifecycle methods ────────────────────────────────────────────────

    async def create_quote_from_inquiry(
        self,
        contact: Contact,
        inquiry_text: str,
        pricing_engine: Any,
    ) -> QuoteModel:
        machine_info = await self._extract_machine_info(inquiry_text)
        machine_model = machine_info.get("machine_model", "UNKNOWN")
        configuration = machine_info.get("configuration", {})

        estimate = await pricing_engine.estimate_price(machine_model, configuration)
        estimated_price = estimate.get("estimated_price", {})
        mid_value = estimated_price.get("mid", 0)

        return await self.create_quote(
            contact_id=str(contact.id),
            company_name=contact.company,
            machine_model=machine_model,
            configuration=configuration,
            estimated_value=Decimal(str(mid_value)),
            currency=estimated_price.get("currency", "USD"),
            status=QuoteStatus.DRAFT,
        )

    async def advance_quote(
        self,
        quote_id: str | UUID,
        new_status: str | QuoteStatus,
        notes: str | None = None,
    ) -> QuoteModel | None:
        async with self._session_factory() as session:
            quote = await session.get(QuoteModel, str(quote_id))
            if not quote:
                return None

            if isinstance(new_status, str):
                new_status = QuoteStatus(new_status)

            quote.status = new_status
            now = datetime.now(timezone.utc)

            if new_status == QuoteStatus.SENT:
                quote.sent_at = now
            elif new_status in (
                QuoteStatus.FOLLOW_UP_1,
                QuoteStatus.FOLLOW_UP_2,
                QuoteStatus.FOLLOW_UP_3,
            ):
                quote.last_follow_up_at = now
            elif new_status in (QuoteStatus.WON, QuoteStatus.LOST, QuoteStatus.EXPIRED):
                quote.closed_at = now

            if notes:
                existing = quote.notes or ""
                quote.notes = f"{existing}\n[{now.isoformat()}] {notes}".strip()

            await session.commit()
            await session.refresh(quote)
        return quote

    async def get_quotes_due_for_followup(
        self, days_since_last: int = 7
    ) -> list[QuoteModel]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_since_last)
        followup_statuses = [
            QuoteStatus.SENT,
            QuoteStatus.FOLLOW_UP_1,
            QuoteStatus.FOLLOW_UP_2,
            QuoteStatus.FOLLOW_UP_3,
        ]

        stmt = (
            select(QuoteModel)
            .where(QuoteModel.status.in_(followup_statuses))
            .where(
                func.coalesce(QuoteModel.last_follow_up_at, QuoteModel.sent_at) < cutoff
            )
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def link_quote_to_deal(
        self, quote_id: str | UUID, deal_id: str | UUID
    ) -> QuoteModel | None:
        return await self.update_quote(quote_id, deal_id=str(deal_id))

    async def get_quote_analytics(
        self, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        all_quotes = await self.list_quotes(filters)
        if not all_quotes:
            return {
                "total_quotes": 0,
                "conversion_rate": 0.0,
                "average_deal_size": 0.0,
                "average_time_to_close_days": 0.0,
                "status_breakdown": {},
            }

        status_counts: dict[str, int] = {}
        won_values: list[float] = []
        close_times: list[float] = []

        for q in all_quotes:
            status_name = q.status.value if isinstance(q.status, QuoteStatus) else q.status
            status_counts[status_name] = status_counts.get(status_name, 0) + 1

            if status_name == QuoteStatus.WON.value:
                if q.estimated_value:
                    won_values.append(float(q.estimated_value))
                if q.closed_at and q.created_at:
                    delta = (q.closed_at - q.created_at).total_seconds() / 86400
                    close_times.append(delta)

        decided = sum(
            status_counts.get(s.value, 0)
            for s in (QuoteStatus.WON, QuoteStatus.LOST, QuoteStatus.EXPIRED)
        )
        won_count = status_counts.get(QuoteStatus.WON.value, 0)

        return {
            "total_quotes": len(all_quotes),
            "conversion_rate": won_count / decided if decided else 0.0,
            "average_deal_size": sum(won_values) / len(won_values) if won_values else 0.0,
            "average_time_to_close_days": (
                sum(close_times) / len(close_times) if close_times else 0.0
            ),
            "status_breakdown": status_counts,
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _extract_machine_info(self, inquiry_text: str) -> dict[str, Any]:
        settings = get_settings()
        api_key = settings.llm.openai_api_key.get_secret_value()
        if not api_key:
            logger.warning("No OpenAI key; returning UNKNOWN machine info")
            return {"machine_model": "UNKNOWN", "configuration": {}}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm.openai_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": inquiry_text[:8_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                return json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError):
            logger.exception("Machine info extraction failed")
            return {"machine_model": "UNKNOWN", "configuration": {}}
