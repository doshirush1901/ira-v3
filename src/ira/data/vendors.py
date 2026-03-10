"""Vendor / Accounts Payable database layer.

Completely separate from the CRM (which tracks customers, leads, prospects).
This module tracks Machinecraft's suppliers, purchase orders, and payables.

Managed by Hera (procurement agent).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
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
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from ira.config import get_settings

_str_uuid = lambda: str(uuid4())  # noqa: E731

logger = logging.getLogger(__name__)


class VendorBase(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────


class VendorStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class PayableStatus(str, PyEnum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"


class POStatus(str, PyEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ── ORM Models ──────────────────────────────────────────────────────────────


class VendorModel(VendorBase):
    __tablename__ = "vendors"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    gst_number: Mapped[str | None] = mapped_column(String(50))
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        Enum(VendorStatus, native_enum=False, create_constraint=False),
        default=VendorStatus.ACTIVE,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    payables: Mapped[list[PayableModel]] = relationship(back_populates="vendor")
    purchase_orders: Mapped[list[PurchaseOrderModel]] = relationship(back_populates="vendor")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "contact_person": self.contact_person,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "category": self.category,
            "gst_number": self.gst_number,
            "payment_terms": self.payment_terms,
            "status": self.status.value if isinstance(self.status, PyEnum) else self.status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PayableModel(VendorBase):
    __tablename__ = "vendor_payables"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    vendor_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("vendors.id"), nullable=False,
    )
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime)
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(
        Enum(PayableStatus, native_enum=False, create_constraint=False),
        default=PayableStatus.PENDING,
    )
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped[VendorModel] = relationship(back_populates="payables")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "vendor_id": str(self.vendor_id),
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "amount": float(self.amount) if self.amount else 0,
            "amount_paid": float(self.amount_paid) if self.amount_paid else 0,
            "currency": self.currency,
            "status": self.status.value if isinstance(self.status, PyEnum) else self.status,
            "description": self.description,
            "notes": self.notes,
        }


class PurchaseOrderModel(VendorBase):
    __tablename__ = "purchase_orders"

    id: Mapped[UUID] = mapped_column(String(36), primary_key=True, default=_str_uuid)
    vendor_id: Mapped[UUID] = mapped_column(
        String(36), ForeignKey("vendors.id"), nullable=False,
    )
    po_number: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(
        Enum(POStatus, native_enum=False, create_constraint=False),
        default=POStatus.DRAFT,
    )
    expected_delivery: Mapped[datetime | None] = mapped_column(DateTime)
    actual_delivery: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    vendor: Mapped[VendorModel] = relationship(back_populates="purchase_orders")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "vendor_id": str(self.vendor_id),
            "po_number": self.po_number,
            "description": self.description,
            "amount": float(self.amount) if self.amount else 0,
            "currency": self.currency,
            "status": self.status.value if isinstance(self.status, PyEnum) else self.status,
            "expected_delivery": self.expected_delivery.isoformat() if self.expected_delivery else None,
            "actual_delivery": self.actual_delivery.isoformat() if self.actual_delivery else None,
            "notes": self.notes,
        }


# ── VendorDatabase service ──────────────────────────────────────────────────


class VendorDatabase:
    """Async vendor/AP service backed by PostgreSQL."""

    _instances: dict[str, VendorDatabase] = {}

    def __new__(cls, database_url: str | None = None, **kwargs: Any) -> VendorDatabase:
        url = database_url or get_settings().database.url
        if url not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[url] = instance
        return cls._instances[url]

    def __init__(self, database_url: str | None = None) -> None:
        if self._initialized:
            return
        url = database_url or get_settings().database.url
        self._engine = create_async_engine(url, echo=False)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False,
        )
        self._closed = False
        self._initialized = True

    @classmethod
    def _reset_instances(cls) -> None:
        cls._instances.clear()

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(VendorBase.metadata.create_all)
        logger.info("Vendor tables created/verified")

    async def close(self) -> None:
        """Dispose the SQLAlchemy engine (idempotent)."""
        if self._closed:
            return
        await self._engine.dispose()
        self._closed = True

    # ── Vendor CRUD ──────────────────────────────────────────────────────

    async def create_vendor(self, **kwargs: Any) -> VendorModel:
        vendor = VendorModel(**kwargs)
        async with self._session_factory() as session:
            session.add(vendor)
            await session.commit()
            await session.refresh(vendor)
        logger.info("Created vendor: %s", vendor.name)
        return vendor

    async def get_vendor(self, vendor_id: str | UUID) -> VendorModel | None:
        async with self._session_factory() as session:
            return await session.get(VendorModel, str(vendor_id))

    async def get_vendor_by_name(self, name: str) -> VendorModel | None:
        stmt = select(VendorModel).where(VendorModel.name == name)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_vendors(self, status: str | None = None) -> list[VendorModel]:
        stmt = select(VendorModel).order_by(VendorModel.name)
        if status:
            stmt = stmt.where(VendorModel.status == status)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_vendor(self, vendor_id: str | UUID, **kwargs: Any) -> VendorModel | None:
        async with self._session_factory() as session:
            vendor = await session.get(VendorModel, str(vendor_id))
            if not vendor:
                return None
            for k, v in kwargs.items():
                setattr(vendor, k, v)
            vendor.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(vendor)
        return vendor

    # ── Payable CRUD ─────────────────────────────────────────────────────

    async def create_payable(self, **kwargs: Any) -> PayableModel:
        payable = PayableModel(**kwargs)
        async with self._session_factory() as session:
            session.add(payable)
            await session.commit()
            await session.refresh(payable)
        logger.info("Created payable for vendor %s: %s", payable.vendor_id, payable.invoice_number)
        return payable

    async def list_payables(
        self,
        vendor_id: str | None = None,
        status: str | None = None,
    ) -> list[PayableModel]:
        stmt = select(PayableModel).order_by(PayableModel.due_date)
        if vendor_id:
            stmt = stmt.where(PayableModel.vendor_id == vendor_id)
        if status:
            stmt = stmt.where(PayableModel.status == status)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_overdue_payables(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(PayableModel, VendorModel.name)
            .join(VendorModel)
            .where(PayableModel.due_date < now)
            .where(PayableModel.status.in_([PayableStatus.PENDING, PayableStatus.PARTIAL, PayableStatus.OVERDUE]))
            .order_by(PayableModel.due_date)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()
        return [
            {**p.to_dict(), "vendor_name": vname}
            for p, vname in rows
        ]

    async def update_payable(self, payable_id: str | UUID, **kwargs: Any) -> PayableModel | None:
        async with self._session_factory() as session:
            payable = await session.get(PayableModel, str(payable_id))
            if not payable:
                return None
            for k, v in kwargs.items():
                setattr(payable, k, v)
            await session.commit()
            await session.refresh(payable)
        return payable

    # ── Purchase Order CRUD ──────────────────────────────────────────────

    async def create_purchase_order(self, **kwargs: Any) -> PurchaseOrderModel:
        po = PurchaseOrderModel(**kwargs)
        async with self._session_factory() as session:
            session.add(po)
            await session.commit()
            await session.refresh(po)
        logger.info("Created PO %s for vendor %s", po.po_number, po.vendor_id)
        return po

    async def list_purchase_orders(
        self,
        vendor_id: str | None = None,
        status: str | None = None,
    ) -> list[PurchaseOrderModel]:
        stmt = select(PurchaseOrderModel).order_by(PurchaseOrderModel.created_at.desc())
        if vendor_id:
            stmt = stmt.where(PurchaseOrderModel.vendor_id == vendor_id)
        if status:
            stmt = stmt.where(PurchaseOrderModel.status == status)
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Analytics ────────────────────────────────────────────────────────

    async def get_payables_summary(self) -> dict[str, Any]:
        """Total payables by status with vendor breakdown."""
        stmt = (
            select(
                PayableModel.status,
                func.count(PayableModel.id).label("count"),
                func.sum(PayableModel.amount).label("total"),
                func.sum(PayableModel.amount_paid).label("paid"),
            )
            .group_by(PayableModel.status)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        summary: dict[str, Any] = {}
        for status, count, total, paid in rows:
            summary[status] = {
                "count": count,
                "total_amount": float(total or 0),
                "total_paid": float(paid or 0),
                "outstanding": float((total or 0) - (paid or 0)),
            }
        return summary
