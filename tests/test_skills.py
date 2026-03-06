"""Tests for the ira.skills subsystem — SKILL_MATRIX, handlers, and use_skill dispatcher."""

from __future__ import annotations

import pytest

from ira.skills import SKILL_MATRIX
from ira.skills.handlers import (
    _HANDLERS,
    calculate_quote,
    draft_outreach_email,
    lookup_machine_spec,
    polish_text,
    summarize_document,
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
    async def test_dispatches_to_correct_handler(self):
        result = await use_skill("summarize_document", text="hello")
        assert "summarize_document" in result
        assert "hello" in result

    async def test_passes_kwargs_through(self):
        result = await use_skill(
            "draft_outreach_email", lead="Acme", tone="friendly",
        )
        assert "Acme" in result
        assert "friendly" in result

    async def test_unknown_skill_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown skill"):
            await use_skill("nonexistent_skill")

    async def test_unknown_skill_lists_available(self):
        with pytest.raises(ValueError, match="summarize_document"):
            await use_skill("bad_name")

    async def test_all_24_skills_callable(self):
        for name in SKILL_MATRIX:
            result = await use_skill(name)
            assert f"Executed skill: {name}" in result


# ═════════════════════════════════════════════════════════════════════════
# Individual handler functions
# ═════════════════════════════════════════════════════════════════════════


class TestHandlers:
    async def test_summarize_document(self):
        result = await summarize_document(text="long doc", max_length=500)
        assert "summarize_document" in result
        assert "'text': 'long doc'" in result
        assert "'max_length': 500" in result

    async def test_draft_outreach_email(self):
        result = await draft_outreach_email(
            lead="John Doe", company="Acme Corp", tone="professional",
        )
        assert "draft_outreach_email" in result
        assert "John Doe" in result
        assert "Acme Corp" in result

    async def test_calculate_quote(self):
        result = await calculate_quote(
            product="PF1-C", quantity=5, region="MENA",
        )
        assert "calculate_quote" in result
        assert "PF1-C" in result

    async def test_polish_text(self):
        result = await polish_text(text="rough draft", style="formal")
        assert "polish_text" in result
        assert "rough draft" in result

    async def test_lookup_machine_spec(self):
        result = await lookup_machine_spec(model="PF1500", field="max_thickness")
        assert "lookup_machine_spec" in result
        assert "PF1500" in result

    async def test_handler_with_no_kwargs(self):
        result = await summarize_document()
        assert "summarize_document" in result
        assert "{}" in result

    async def test_handler_return_type_is_string(self):
        for name in SKILL_MATRIX:
            handler = _HANDLERS[name]
            result = await handler(x=1)
            assert isinstance(result, str)
