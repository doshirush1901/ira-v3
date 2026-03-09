from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ira.services.resilience import RetryPolicy, run_with_retry
from ira.services.structured_logging import StructuredJsonFormatter
from ira.systems.legacy_guard import scan_runtime_for_legacy_imports
from ira.systems.outbound_approvals import OutboundApprovalService, OutboundMessage


def test_legacy_guard_detects_legacy_import(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("from core_modules.api_rate_limiter import APIRateLimiter\n", encoding="utf-8")

    violations = scan_runtime_for_legacy_imports(root=tmp_path)
    assert len(violations) == 1
    assert violations[0].import_name == "core_modules.api_rate_limiter"


@pytest.mark.asyncio
async def test_resilience_retry_succeeds_after_transient_error() -> None:
    attempts = {"count": 0}

    async def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    result = await run_with_retry(
        operation,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
        is_retryable=lambda exc: "temporary" in str(exc),
    )
    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_outbound_approval_service_requires_approval_before_drafts(tmp_path: Path) -> None:
    class FakeGmail:
        async def create_draft(self, *, to: str, subject: str, body: str) -> dict[str, str]:
            return {"id": f"draft-{to}", "to": to, "subject": subject, "body": body}

    service = OutboundApprovalService(storage_path=tmp_path / "approvals.json")
    batch = await service.create_batch(
        campaign_name="test-campaign",
        created_by="ops-user",
        messages=[
            OutboundMessage(to="a@example.com", subject="Hi A", body="Body A"),
            OutboundMessage(to="b@example.com", subject="Hi B", body="Body B"),
        ],
    )
    assert batch["status"] == "pending_approval"
    assert batch["drafts"] == []

    approved = await service.approve_batch(
        batch_id=batch["batch_id"],
        approved_by="manager-1",
        gmail_draft_sender=FakeGmail(),
    )
    assert approved["status"] == "approved"
    assert len(approved["drafts"]) == 2


def test_structured_json_formatter_emits_expected_keys() -> None:
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="ira.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["logger"] == "ira.test"
    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
