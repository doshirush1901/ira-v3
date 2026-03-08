"""Tests for anti-hallucination improvements.

Covers:
- Faithfulness gate in the pipeline
- Grounding score tracking in BaseAgent
- Confidence floor in the ASSESS stage
- Mnemon semantic matching
- Config field defaults
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.schemas.llm_outputs import FaithfulnessResult, KnowledgeAssessment


# ── helpers ──────────────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Return a mock Settings object with anti-hallucination config."""
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-test"
    s.llm.anthropic_api_key.get_secret_value.return_value = ""
    s.llm.anthropic_model = "claude-test"
    s.external_apis.api_key.get_secret_value.return_value = ""
    s.search.tavily_api_key.get_secret_value.return_value = ""
    s.search.serper_api_key.get_secret_value.return_value = ""
    s.search.searchapi_api_key.get_secret_value.return_value = ""
    s.app.react_max_iterations = 8
    s.app.faithfulness_threshold = overrides.get("faithfulness_threshold", 0.6)
    s.app.faithfulness_hard_threshold = overrides.get("faithfulness_hard_threshold", 0.3)
    s.app.confidence_floor = overrides.get("confidence_floor", 0.3)
    s.app.mnemon_semantic_check = overrides.get("mnemon_semantic_check", False)
    return s


def _mock_llm_client(responses: list[str]):
    client = MagicMock()
    client.generate_text = AsyncMock(side_effect=list(responses))
    client.generate_text_with_fallback = AsyncMock(side_effect=list(responses))
    client.generate_structured = AsyncMock()
    client._openai = MagicMock()
    return client


# ═══════════════════════════════════════════════════════════════════════════════
# Config defaults
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfigDefaults:
    def test_app_config_has_hallucination_fields(self):
        from ira.config import AppConfig

        cfg = AppConfig()
        assert cfg.faithfulness_threshold == 0.6
        assert cfg.faithfulness_hard_threshold == 0.3
        assert cfg.confidence_floor == 0.3
        assert cfg.mnemon_semantic_check is False


# ═══════════════════════════════════════════════════════════════════════════════
# Grounding score (BaseAgent)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGroundingScore:
    def test_empty_scratchpad_returns_zero(self):
        from ira.agents.base_agent import BaseAgent

        assert BaseAgent._compute_grounding_score([]) == 0.0

    def test_retrieval_tool_returns_one(self):
        from ira.agents.base_agent import BaseAgent

        scratchpad = [
            {
                "thought": "need to search",
                "action": 'search_knowledge({"query": "test"})',
                "observation": "found results",
            }
        ]
        assert BaseAgent._compute_grounding_score(scratchpad) == 1.0

    def test_non_retrieval_tool_returns_half(self):
        from ira.agents.base_agent import BaseAgent

        scratchpad = [
            {
                "thought": "checking entities",
                "action": 'check_known_entities({"query": "acme"})',
                "observation": "no match",
            }
        ]
        assert BaseAgent._compute_grounding_score(scratchpad) == 0.5

    def test_mixed_tools_returns_one_if_retrieval_present(self):
        from ira.agents.base_agent import BaseAgent

        scratchpad = [
            {
                "thought": "check entities",
                "action": 'check_known_entities({"query": "acme"})',
                "observation": "no match",
            },
            {
                "thought": "search knowledge",
                "action": 'recall_memory({"query": "acme history"})',
                "observation": "found memories",
            },
        ]
        assert BaseAgent._compute_grounding_score(scratchpad) == 1.0

    def test_scratchpad_without_tool_calls_returns_zero(self):
        from ira.agents.base_agent import BaseAgent

        scratchpad = [
            {"thought": "thinking", "action": "", "observation": ""},
        ]
        assert BaseAgent._compute_grounding_score(scratchpad) == 0.0

    async def test_run_sets_grounding_score(self):
        settings = _make_settings()
        mock_client = _mock_llm_client([])
        mock_client.generate_text_with_fallback = AsyncMock(
            return_value='{"thought": "I know this", "final_answer": "The answer is 42."}'
        )

        with patch("ira.config.get_settings", return_value=settings), \
             patch("ira.agents.base_agent.get_llm_client", return_value=mock_client):
            from ira.agents.clio import Clio

            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            retriever.search_by_category = AsyncMock(return_value=[])
            from ira.message_bus import MessageBus
            bus = MessageBus()

            agent = Clio(retriever=retriever, bus=bus)
            await agent.run("test query")

            assert agent._last_grounding_score == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Faithfulness gate (guardrails)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFaithfulnessCheck:
    async def test_heuristic_faithfulness_high_overlap(self):
        from ira.brain.guardrails import _heuristic_faithfulness

        response = "The PF1 machine has a cycle time of 12 seconds."
        context = ["The PF1 machine has a cycle time of 12 seconds and produces 300 cups per minute."]
        result = _heuristic_faithfulness(response, context)
        assert result["faithful"] is True
        assert result["score"] >= 0.7

    async def test_heuristic_faithfulness_low_overlap(self):
        from ira.brain.guardrails import _heuristic_faithfulness

        response = "The quantum flux capacitor operates at warp speed with dilithium crystals."
        context = ["The PF1 machine has a cycle time of 12 seconds."]
        result = _heuristic_faithfulness(response, context)
        assert result["score"] < 0.7

    async def test_check_faithfulness_empty_context(self):
        from ira.brain.guardrails import check_faithfulness

        result = await check_faithfulness("any response", [])
        assert result["faithful"] is True
        assert result["score"] == 1.0

    async def test_check_faithfulness_empty_response(self):
        from ira.brain.guardrails import check_faithfulness

        result = await check_faithfulness("", ["some context"])
        assert result["faithful"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# HHEM integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestHHEM:
    async def test_hhem_faithfulness_returns_dict_when_model_available(self):
        """If HHEM loads, _hhem_faithfulness returns a proper result dict."""
        from ira.brain.guardrails import _hhem_faithfulness

        result = await _hhem_faithfulness(
            "The PF1 machine has a cycle time of 12 seconds.",
            ["The PF1 machine has a cycle time of 12 seconds and produces 300 cups per minute."],
        )
        if result is None:
            pytest.skip("HHEM model not available in this environment")
        assert "faithful" in result
        assert "score" in result
        assert 0.0 <= result["score"] <= 1.0
        assert isinstance(result["unsupported_claims"], list)

    async def test_hhem_faithfulness_empty_sentences(self):
        """Short responses with no real sentences return faithful."""
        from ira.brain.guardrails import _hhem_faithfulness

        result = await _hhem_faithfulness("OK.", ["Some context here."])
        if result is None:
            pytest.skip("HHEM model not available in this environment")
        assert result["faithful"] is True
        assert result["score"] == 1.0

    async def test_hhem_fallback_when_model_unavailable(self):
        """check_faithfulness falls through to LLM/heuristic when HHEM is None."""
        import ira.brain.guardrails as g

        saved_model = g._hhem_model
        saved_attempted = g._hhem_load_attempted
        try:
            g._hhem_model = None
            g._hhem_load_attempted = True

            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(
                side_effect=Exception("LLM unavailable"),
            )
            with patch("ira.services.llm_client.get_llm_client", return_value=mock_llm):
                result = await g.check_faithfulness(
                    "The PF1 machine has a cycle time of 12 seconds.",
                    ["The PF1 machine has a cycle time of 12 seconds."],
                )
            assert "score" in result
            assert result["score"] >= 0.0
        finally:
            g._hhem_model = saved_model
            g._hhem_load_attempted = saved_attempted

    async def test_hhem_is_primary_scorer(self):
        """When HHEM is available, it is used instead of LLM."""
        import ira.brain.guardrails as g

        mock_hhem_result = {
            "faithful": True,
            "unsupported_claims": [],
            "score": 0.95,
        }
        with patch.object(g, "_hhem_faithfulness", new_callable=AsyncMock, return_value=mock_hhem_result):
            result = await g.check_faithfulness(
                "Some response text here.",
                ["Some context document."],
            )
        assert result["score"] == 0.95

    def test_get_hhem_caches_result(self):
        """_get_hhem only attempts loading once."""
        import ira.brain.guardrails as g

        saved_model = g._hhem_model
        saved_attempted = g._hhem_load_attempted
        try:
            g._hhem_model = "sentinel"
            g._hhem_load_attempted = True
            assert g._get_hhem() == "sentinel"
        finally:
            g._hhem_model = saved_model
            g._hhem_load_attempted = saved_attempted


# ═══════════════════════════════════════════════════════════════════════════════
# Mnemon corrections
# ═══════════════════════════════════════════════════════════════════════════════


class TestMnemonCorrections:
    async def test_string_match_correction(self):
        settings = _make_settings()
        mock_client = _mock_llm_client([])

        ledger = {
            "entities": {
                "acme corp": {
                    "current_status": "Active customer since 2024",
                    "stale_values": ["prospect", "potential lead"],
                    "corrected_at": "2026-03-01",
                    "source": "user_correction",
                },
            },
            "_metadata": {"last_updated": "2026-03-01"},
        }

        with patch("ira.config.get_settings", return_value=settings), \
             patch("ira.agents.base_agent.get_llm_client", return_value=mock_client), \
             patch("ira.agents.mnemon._load_ledger", return_value=ledger):
            from ira.agents.mnemon import Mnemon
            from ira.message_bus import MessageBus

            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            bus = MessageBus()
            agent = Mnemon(retriever=retriever, bus=bus)

            result = await agent.check_and_correct(
                "Acme Corp is a prospect we should follow up with."
            )
            assert "CORRECTION" in result
            assert "Active customer since 2024" in result

    async def test_no_correction_when_no_match(self):
        settings = _make_settings()
        mock_client = _mock_llm_client([])

        ledger = {
            "entities": {
                "acme corp": {
                    "current_status": "Active customer",
                    "stale_values": ["prospect"],
                    "corrected_at": "2026-03-01",
                    "source": "user_correction",
                },
            },
            "_metadata": {"last_updated": "2026-03-01"},
        }

        with patch("ira.config.get_settings", return_value=settings), \
             patch("ira.agents.base_agent.get_llm_client", return_value=mock_client), \
             patch("ira.agents.mnemon._load_ledger", return_value=ledger):
            from ira.agents.mnemon import Mnemon
            from ira.message_bus import MessageBus

            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            bus = MessageBus()
            agent = Mnemon(retriever=retriever, bus=bus)

            text = "Beta Industries placed a new order."
            result = await agent.check_and_correct(text)
            assert result == text

    async def test_semantic_check_skipped_when_disabled(self):
        settings = _make_settings(mnemon_semantic_check=False)
        mock_client = _mock_llm_client([])

        ledger = {
            "entities": {
                "acme corp": {
                    "current_status": "Active customer",
                    "stale_values": ["old status"],
                    "corrected_at": "2026-03-01",
                    "source": "user_correction",
                },
            },
            "_metadata": {"last_updated": "2026-03-01"},
        }

        with patch("ira.config.get_settings", return_value=settings), \
             patch("ira.agents.base_agent.get_llm_client", return_value=mock_client), \
             patch("ira.agents.mnemon._load_ledger", return_value=ledger):
            from ira.agents.mnemon import Mnemon
            from ira.message_bus import MessageBus

            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            bus = MessageBus()
            agent = Mnemon(retriever=retriever, bus=bus)

            text = "Some unrelated text that doesn't mention any entity."
            result = await agent.check_and_correct(text)
            assert result == text

    async def test_empty_text_returns_unchanged(self):
        settings = _make_settings()
        mock_client = _mock_llm_client([])

        with patch("ira.config.get_settings", return_value=settings), \
             patch("ira.agents.base_agent.get_llm_client", return_value=mock_client):
            from ira.agents.mnemon import Mnemon
            from ira.message_bus import MessageBus

            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            bus = MessageBus()
            agent = Mnemon(retriever=retriever, bus=bus)

            assert await agent.check_and_correct("") == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Cosine similarity helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestCosineSimilarity:
    def test_identical_vectors(self):
        from ira.agents.mnemon import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from ira.agents.mnemon import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector(self):
        from ira.agents.mnemon import _cosine_similarity

        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_opposite_vectors(self):
        from ira.agents.mnemon import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Confidence floor
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceFloor:
    async def test_generate_confidence_prefix_unknown(self):
        from ira.data.models import KnowledgeState
        from ira.memory.metacognition import Metacognition

        meta = Metacognition.__new__(Metacognition)
        prefix = meta.generate_confidence_prefix(KnowledgeState.UNKNOWN, 0.0)
        assert "don't have reliable" in prefix

    async def test_generate_confidence_prefix_verified(self):
        from ira.data.models import KnowledgeState
        from ira.memory.metacognition import Metacognition

        meta = Metacognition.__new__(Metacognition)
        prefix = meta.generate_confidence_prefix(KnowledgeState.KNOW_VERIFIED, 0.9)
        assert "verified documentation" in prefix

    async def test_generate_confidence_prefix_conflicting(self):
        from ira.data.models import KnowledgeState
        from ira.memory.metacognition import Metacognition

        meta = Metacognition.__new__(Metacognition)
        prefix = meta.generate_confidence_prefix(KnowledgeState.CONFLICTING, 0.5)
        assert "conflicting" in prefix.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Guardrails (competitor + confidentiality)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGuardrails:
    async def test_competitor_mentions_detected(self):
        from ira.brain.guardrails import check_competitor_mentions

        result = await check_competitor_mentions(
            "We recommend ILLIG machines for this application."
        )
        assert result["clean"] is False
        assert len(result["mentions"]) == 1
        assert result["mentions"][0]["competitor"] == "ILLIG"

    async def test_competitor_mentions_clean(self):
        from ira.brain.guardrails import check_competitor_mentions

        result = await check_competitor_mentions(
            "Our Machinecraft PF1 is the best choice."
        )
        assert result["clean"] is True

    async def test_confidentiality_internal_always_safe(self):
        from ira.brain.guardrails import check_confidentiality

        result = await check_confidentiality(
            "The margin is 45% on this deal.", direction="internal"
        )
        assert result["safe"] is True

    async def test_confidentiality_detects_margin(self):
        from ira.brain.guardrails import check_confidentiality

        mock_llm = MagicMock()
        mock_llm.generate_structured = AsyncMock(side_effect=Exception("skip LLM"))
        with patch("ira.services.llm_client.get_llm_client", return_value=mock_llm):
            result = await check_confidentiality(
                "The margin is 45% on this deal.", direction="external"
            )
        assert result["safe"] is False
        assert "internal_margin" in result["leaked_categories"]


# ═══════════════════════════════════════════════════════════════════════════════
# ReAct prompt grounding section
# ═══════════════════════════════════════════════════════════════════════════════


class TestReActPrompt:
    def test_grounding_section_present(self):
        from ira.prompt_loader import load_prompt

        prompt = load_prompt("react_system")
        assert "GROUNDING" in prompt
        assert "MUST be grounded in tool outputs" in prompt

    def test_security_section_still_present(self):
        from ira.prompt_loader import load_prompt

        prompt = load_prompt("react_system")
        assert "SECURITY" in prompt
        assert "untrusted data" in prompt
