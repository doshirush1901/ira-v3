from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.data.crm import CRMDatabase
from ira.data.vendors import VendorDatabase


@pytest.mark.asyncio
async def test_crm_close_is_idempotent() -> None:
    CRMDatabase._reset_instances()
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    fake_settings = SimpleNamespace(database=SimpleNamespace(url="sqlite+aiosqlite://"))

    with patch("ira.data.crm.create_async_engine", return_value=fake_engine), patch(
        "ira.data.crm.get_settings",
        return_value=fake_settings,
    ):
        db = CRMDatabase(database_url="sqlite+aiosqlite://")
        await db.close()
        await db.close()

    fake_engine.dispose.assert_awaited_once()
    CRMDatabase._reset_instances()


@pytest.mark.asyncio
async def test_vendor_close_is_idempotent() -> None:
    VendorDatabase._reset_instances()
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    fake_settings = SimpleNamespace(database=SimpleNamespace(url="sqlite+aiosqlite://"))

    with patch("ira.data.vendors.create_async_engine", return_value=fake_engine), patch(
        "ira.data.vendors.get_settings",
        return_value=fake_settings,
    ):
        db = VendorDatabase(database_url="sqlite+aiosqlite://")
        await db.close()
        await db.close()

    fake_engine.dispose.assert_awaited_once()
    VendorDatabase._reset_instances()
