"""Approval-gated outbound campaign drafting for governed script productization."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OutboundMessage:
    to: str
    subject: str
    body: str


class OutboundApprovalService:
    """Stores pending outbound batches and releases drafts only after approval."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._lock = asyncio.Lock()
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._storage_path.exists():
            self._storage_path.write_text("[]", encoding="utf-8")

    def _load(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self._storage_path.write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")

    async def create_batch(
        self,
        *,
        campaign_name: str,
        created_by: str,
        messages: list[OutboundMessage],
    ) -> dict[str, Any]:
        async with self._lock:
            rows = self._load()
            batch_id = uuid.uuid4().hex[:12]
            now = datetime.now(timezone.utc).isoformat()
            row = {
                "batch_id": batch_id,
                "campaign_name": campaign_name,
                "created_by": created_by,
                "created_at": now,
                "approved_at": None,
                "approved_by": None,
                "status": "pending_approval",
                "messages": [m.__dict__ for m in messages],
                "drafts": [],
            }
            rows.append(row)
            self._save(rows)
            return row

    async def approve_batch(
        self,
        *,
        batch_id: str,
        approved_by: str,
        gmail_draft_sender: Any,
    ) -> dict[str, Any]:
        async with self._lock:
            rows = self._load()
            for row in rows:
                if row.get("batch_id") != batch_id:
                    continue
                if row.get("status") == "approved":
                    return row
                drafts: list[dict[str, Any]] = []
                for msg in row.get("messages", []):
                    draft = await gmail_draft_sender.create_draft(
                        to=msg["to"],
                        subject=msg["subject"],
                        body=msg["body"],
                    )
                    drafts.append(draft)
                row["approved_at"] = datetime.now(timezone.utc).isoformat()
                row["approved_by"] = approved_by
                row["status"] = "approved"
                row["drafts"] = drafts
                self._save(rows)
                return row
            raise KeyError(f"Unknown batch_id: {batch_id}")

    async def list_batches(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._load()
            return rows[-limit:]
