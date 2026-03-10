"""Tests for the ira.skills subsystem — SKILL_MATRIX, handlers, and use_skill dispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.skills import SKILL_MATRIX
from ira.skills.handlers import (
    _HANDLERS,
    get_skill_stats,
    reset_skill_stats,
    use_skill,
)


# ═════════════════════════════════════════════════════════════════════════
# SKILL_MATRIX integrity
# ═════════════════════════════════════════════════════════════════════════


class TestSkillMatrix:
    def test_matrix_has_33_skills(self):
        assert len(SKILL_MATRIX) == 33

    def test_all_keys_are_snake_case(self):
        for name in SKILL_MATRIX:
            assert name == name.lower(), f"{name} is not lowercase"
            assert " " not in name, f"{name} contains spaces"
            assert name.replace("_", "").isalpha(), f"{name} has non-alpha chars"

    def test_all_values_are_nonempty_strings(self):
        for name, desc in SKILL_MATRIX.items():
            assert isinstance(desc, str), f"{name} description is not a string"
            assert len(desc) > 10, f"{name} description is too short"

    def test_handler_exists_for_every_skill(self):
        missing = [name for name in SKILL_MATRIX if name not in _HANDLERS]
        assert missing == [], f"Missing handlers: {missing}"


# ═════════════════════════════════════════════════════════════════════════
# use_skill dispatcher
# ═════════════════════════════════════════════════════════════════════════


class TestUseSkill:
    @pytest.fixture(autouse=True)
    def _reset_stats(self):
        reset_skill_stats()
        yield
        reset_skill_stats()

    async def test_unknown_skill_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            await use_skill("nonexistent_skill")

    async def test_unknown_skill_lists_available(self):
        with pytest.raises(ValueError, match="summarize_document"):
            await use_skill("bad_name")

    async def test_dispatches_to_handler(self):
        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            return_value="Summary of the document",
        ):
            result = await use_skill("summarize_document", text="hello world")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_passes_kwargs_through(self):
        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            return_value="Dear Acme, friendly outreach...",
        ):
            result = await use_skill(
                "draft_outreach_email", lead="Acme", tone="friendly",
            )
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_stats_record_success_and_latency(self):
        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            return_value="Summary of the document",
        ):
            await use_skill("summarize_document", text="hello world")

        stats = get_skill_stats()["summarize_document"]
        assert stats["calls"] == 1
        assert stats["success"] == 1
        assert stats["failure"] == 0
        assert stats["avg_ms"] >= 0

    async def test_stats_record_failures(self):
        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm boom"),
        ):
            with pytest.raises(RuntimeError, match="llm boom"):
                await use_skill("summarize_document", text="hello world")

        stats = get_skill_stats()["summarize_document"]
        assert stats["calls"] == 1
        assert stats["failure"] == 1
        assert "boom" in stats["last_error"]


# ═════════════════════════════════════════════════════════════════════════
# Individual handler smoke tests (with mocked LLM)
# ═════════════════════════════════════════════════════════════════════════


class TestHandlers:
    @pytest.fixture(autouse=True)
    def mock_llm(self):
        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            return_value="Mocked LLM response for skill test",
        ) as m:
            yield m

    async def test_all_handlers_return_strings(self):
        for name, handler in _HANDLERS.items():
            result = await handler()
            assert isinstance(result, str), f"{name} did not return a string"

    async def test_summarize_document_calls_llm(self, mock_llm):
        from ira.skills.handlers import summarize_document
        result = await summarize_document(text="long doc")
        assert isinstance(result, str)

    async def test_draft_outreach_email(self, mock_llm):
        from ira.skills.handlers import draft_outreach_email
        result = await draft_outreach_email(lead="John", company="Acme")
        assert isinstance(result, str)

    async def test_polish_text(self, mock_llm):
        from ira.skills.handlers import polish_text
        result = await polish_text(text="rough draft")
        assert isinstance(result, str)

    async def test_handler_return_type_is_string(self):
        for name in SKILL_MATRIX:
            handler = _HANDLERS[name]
            result = await handler()
            assert isinstance(result, str), f"{name} handler did not return str"


# ═════════════════════════════════════════════════════════════════════════
# Agent-handler contract: Prometheus, Hermes, Plutus kwargs match handlers
# ═════════════════════════════════════════════════════════════════════════


class TestAgentSkillContractAlignment:
    """Assert prioritized agents' use_skill kwargs satisfy handler contracts."""

    async def test_update_crm_record_accepts_prometheus_kwargs(self):
        from ira.skills.handlers import update_crm_record

        crm = AsyncMock()
        crm.update_deal = AsyncMock(return_value=True)
        with patch("ira.skills.handlers._svc", side_effect=lambda k: crm if k == "crm" else None):
            # Prometheus passes: type=record_type, id=record_id, updates=updates
            result = await update_crm_record(
                type="deal",
                id="deal-123",
                updates={"stage": "WON"},
            )
        assert "Error:" not in result
        assert "Updated" in result or "success" in result.lower()

    async def test_schedule_campaign_accepts_hermes_kwargs(self):
        from ira.skills.handlers import schedule_campaign

        crm = AsyncMock()
        crm.create_campaign = AsyncMock(return_value=MagicMock(id="camp-1"))
        with patch("ira.skills.handlers._svc", side_effect=lambda k: crm if k == "crm" else None):
            # Hermes passes: name, segment (dict), start_date
            result = await schedule_campaign(
                name="Q1 Campaign",
                segment={"description": "EMEA leads"},
                start_date="2025-04-01",
            )
        assert "Error:" not in result
        assert "scheduled" in result.lower() or "planned" in result.lower()

    async def test_generate_invoice_accepts_plutus_kwargs(self):
        from ira.skills.handlers import generate_invoice

        retriever = AsyncMock()
        retriever.search = AsyncMock(return_value=[])

        def _svc(key):
            return retriever if key == "retriever" else None

        with patch(
            "ira.skills.handlers._llm_call",
            new_callable=AsyncMock,
            return_value="# Invoice\nAcme Corp",
        ), patch("ira.skills.handlers._svc", side_effect=_svc):
            # Plutus passes: customer, quote_id, items (list)
            result = await generate_invoice(
                customer="Acme Corp",
                quote_id="",
                items=[],
            )
        assert "Error:" not in result
        assert isinstance(result, str) and len(result) > 0
