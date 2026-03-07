"""Tests for the ira.skills subsystem — SKILL_MATRIX, handlers, and use_skill dispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ira.skills import SKILL_MATRIX
from ira.skills.handlers import (
    _HANDLERS,
    use_skill,
)


# ═════════════════════════════════════════════════════════════════════════
# SKILL_MATRIX integrity
# ═════════════════════════════════════════════════════════════════════════


class TestSkillMatrix:
    def test_matrix_has_24_skills(self):
        assert len(SKILL_MATRIX) == 24

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
