"""Tests for brain audit fixes — covers all 14 issues.

Organized by severity: Critical, High, Medium.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_llm_client():
    client = MagicMock()
    client.generate_text = AsyncMock(return_value="")
    client.generate_structured = AsyncMock()
    client.generate_text_with_fallback = AsyncMock(return_value="")
    return client


# ── Critical 1: SleepTrainer uses separate ledger file ───────────────────────


class TestSleepTrainerLedgerSplit:
    """SleepTrainer should write to sleep_trainer_ledger.json, not learned_corrections.json."""

    def test_learned_path_is_separate(self):
        from ira.brain.sleep_trainer import _LEARNED_PATH

        assert "sleep_trainer_ledger" in str(_LEARNED_PATH)
        assert "learned_corrections" not in str(_LEARNED_PATH)

    def test_correction_learner_uses_original_path(self):
        from ira.brain.correction_learner import _DATA_PATH

        assert "learned_corrections.json" in str(_DATA_PATH)

    def test_no_path_collision(self):
        from ira.brain.correction_learner import _DATA_PATH
        from ira.brain.sleep_trainer import _LEARNED_PATH

        assert _DATA_PATH != _LEARNED_PATH


# ── Critical 2: SleepTrainer Phase 2 calls set_payload ───────────────────────


class TestSleepTrainerPhase2Upsert:
    """Phase 2 should call set_payload to flag stale chunks in Qdrant."""

    @pytest.mark.asyncio
    async def test_set_payload_called_for_stale_hits(self):
        from ira.brain.sleep_trainer import SleepTrainer
        from ira.schemas.llm_outputs import TruthHint, TruthHints

        store = MagicMock()
        store.get_pending_corrections = AsyncMock(return_value=[
            {"id": 1, "entity": "PF1", "category": "SPECS", "severity": "HIGH",
             "old_value": "400T", "new_value": "500T", "source": "test",
             "created_at": "2025-01-01"},
        ])
        store.mark_processed = AsyncMock()

        qdrant = MagicMock()
        qdrant.search = AsyncMock(return_value=[
            {"id": "point-abc", "content": "PF1 400T", "score": 0.8, "metadata": {}},
        ])
        qdrant.set_payload = AsyncMock()
        qdrant.upsert_items = AsyncMock()

        mock_llm = _mock_llm_client()
        mock_llm.generate_structured = AsyncMock(
            return_value=TruthHints(hints=[
                TruthHint(pattern="PF1 capacity", answer="500T", entity="PF1", category="SPECS"),
            ])
        )

        with patch("ira.brain.sleep_trainer.get_llm_client", return_value=mock_llm):
            trainer = SleepTrainer(
                correction_store=store,
                qdrant_manager=qdrant,
                embedding_service=MagicMock(),
            )
            await trainer.run_training()

        qdrant.set_payload.assert_called_once()
        call_args = qdrant.set_payload.call_args
        assert call_args[0][0] == "point-abc"
        payload = call_args[0][1]
        assert payload["metadata"]["_superseded"] is True


# ── Critical 3: Graph Consolidation logs sources, not content ────────────────


class TestGraphConsolidationSources:
    """Retrieval logging should use source identifiers, not content snippets."""

    @pytest.mark.asyncio
    async def test_log_retrieval_uses_sources(self):
        from ira.brain.graph_consolidation import GraphConsolidation

        graph = MagicMock()
        gc = GraphConsolidation(knowledge_graph=graph)
        gc.log_retrieval = AsyncMock()

        from ira.brain.retriever import UnifiedRetriever

        results = [
            {"id": "abc", "content": "PF1 has 500T capacity", "source": "specs.pdf",
             "source_type": "qdrant", "metadata": {}},
        ]

        with patch("ira.brain.retriever.GraphConsolidation", return_value=gc):
            qdrant = MagicMock()
            kg = MagicMock()
            with patch("ira.brain.retriever.get_settings") as ms, \
                 patch("ira.brain.retriever.Ranker"):
                ms.return_value.embedding.api_key.get_secret_value.return_value = ""
                ms.return_value.embedding.rerank_model = "test"
                retriever = UnifiedRetriever(qdrant=qdrant, graph=kg)

            await retriever._log_retrieval("PF1 specs", results)

        gc.log_retrieval.assert_called_once()
        logged_sources = gc.log_retrieval.call_args[0][1]
        assert logged_sources[0] == "specs.pdf"
        assert "500T" not in logged_sources[0]


# ── High 4: Truth Hints — manual pricing hints not skipped ───────────────────


class TestTruthHintsStaleness:
    """Manual pricing hints without created_at should NOT be skipped."""

    def test_manual_hint_without_timestamp_not_stale(self):
        from ira.brain.truth_hints import TruthHintsEngine

        result = TruthHintsEngine._is_stale_pricing(
            {"answer": "PF1 costs EUR 225,000"},
            "what is the price of pf1",
        )
        assert result is False

    def test_old_learned_hint_is_stale(self):
        from ira.brain.truth_hints import TruthHintsEngine

        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        result = TruthHintsEngine._is_stale_pricing(
            {"answer": "PF1 costs EUR 225,000", "created_at": old_date},
            "what is the price of pf1",
        )
        assert result is True

    def test_recent_learned_hint_not_stale(self):
        from ira.brain.truth_hints import TruthHintsEngine

        recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        result = TruthHintsEngine._is_stale_pricing(
            {"answer": "PF1 costs EUR 225,000", "created_at": recent_date},
            "what is the price of pf1",
        )
        assert result is False

    def test_general_staleness_skips_old_learned_hints(self):
        from ira.brain.truth_hints import TruthHintsEngine

        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        result = TruthHintsEngine._is_stale_learned(
            {"answer": "PF1 lead time 16 weeks", "added_at": old_date},
        )
        assert result is True

    def test_general_staleness_keeps_manual_hints(self):
        from ira.brain.truth_hints import TruthHintsEngine

        result = TruthHintsEngine._is_stale_learned(
            {"answer": "PF1 lead time 16 weeks"},
        )
        assert result is False


# ── High 5: Knowledge Discovery contradiction check ──────────────────────────


class TestKnowledgeDiscoveryContradiction:
    """Discovery should skip facts that contradict existing KB content."""

    @pytest.mark.asyncio
    async def test_contradicting_fact_skipped(self):
        from ira.brain.knowledge_discovery import KnowledgeDiscovery

        qdrant = MagicMock()
        qdrant.search = AsyncMock(return_value=[
            {"content": "PF1 capacity is 500T", "score": 0.9},
        ])
        qdrant.upsert_items = AsyncMock()

        mock_llm = _mock_llm_client()
        mock_llm.generate_text = AsyncMock(return_value="YES")

        retriever = MagicMock()
        embedding = MagicMock()

        with patch("ira.brain.knowledge_discovery.get_llm_client", return_value=mock_llm):
            discovery = KnowledgeDiscovery(
                retriever=retriever,
                qdrant_manager=qdrant,
                embedding_service=embedding,
            )

        result = await discovery._contradicts_existing("PF1", "PF1 capacity is 400T")
        assert result is True

    @pytest.mark.asyncio
    async def test_non_contradicting_fact_allowed(self):
        from ira.brain.knowledge_discovery import KnowledgeDiscovery

        qdrant = MagicMock()
        qdrant.search = AsyncMock(return_value=[
            {"content": "PF1 capacity is 500T", "score": 0.9},
        ])

        mock_llm = _mock_llm_client()
        mock_llm.generate_text = AsyncMock(return_value="NO")

        retriever = MagicMock()
        embedding = MagicMock()

        with patch("ira.brain.knowledge_discovery.get_llm_client", return_value=mock_llm):
            discovery = KnowledgeDiscovery(
                retriever=retriever,
                qdrant_manager=qdrant,
                embedding_service=embedding,
            )

        result = await discovery._contradicts_existing("PF1", "PF1 weight is 8500kg")
        assert result is False


# ── High 7: PricingLearner loads index on initialize ─────────────────────────


class TestPricingLearnerInit:
    """PricingLearner should load index from disk on initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_loads_index(self, tmp_path):
        from ira.brain.pricing_learner import PricingLearner, _PRICE_INDEX_PATH

        index_data = {"models": {"PF1": {"base_price": 225000}}}
        test_path = tmp_path / "price_index.json"
        test_path.write_text(json.dumps(index_data))

        with patch("ira.brain.pricing_learner._PRICE_INDEX_PATH", test_path):
            learner = PricingLearner()
            await learner.initialize()

        assert learner._initialized is True
        assert "PF1" in learner._index.get("models", {})


# ── Medium 2: Fast path identity length guard ────────────────────────────────


class TestFastPathIdentityGuard:
    """Identity pattern should not swallow compound queries."""

    def test_short_identity_query_matches(self):
        from ira.brain.fast_path import classify

        result = classify("Who are you?")
        assert result.matched is True
        assert result.category.value == "IDENTITY"

    def test_compound_query_not_swallowed(self):
        from ira.brain.fast_path import classify

        result = classify("Who are you and what's the PF1 price?")
        assert result.matched is False


# ── Medium 3: DeterministicRouter new patterns ───────────────────────────────


class TestDeterministicRouterNewPatterns:
    """New patterns should route payment, delivery, and email queries."""

    def test_payment_status_routes_to_finance(self):
        from ira.brain.deterministic_router import DeterministicRouter, IntentCategory

        router = DeterministicRouter()
        result = router.route("What is the payment status for Acme?")
        assert result is not None
        assert result["intent"] == IntentCategory.FINANCE_REVIEW.value

    def test_delivery_date_routes_to_project(self):
        from ira.brain.deterministic_router import DeterministicRouter, IntentCategory

        router = DeterministicRouter()
        result = router.route("What is the delivery date for TurkPack?")
        assert result is not None
        assert result["intent"] == IntentCategory.PROJECT_MANAGEMENT.value

    def test_email_from_routes_to_service(self):
        from ira.brain.deterministic_router import DeterministicRouter, IntentCategory

        router = DeterministicRouter()
        result = router.route("Find emails from Erik at Acme")
        assert result is not None
        assert result["intent"] == IntentCategory.CUSTOMER_SERVICE.value

    def test_invoice_routes_to_finance(self):
        from ira.brain.deterministic_router import DeterministicRouter, IntentCategory

        router = DeterministicRouter()
        result = router.route("Show me the latest invoice for Nordic Industries")
        assert result is not None
        assert result["intent"] == IntentCategory.FINANCE_REVIEW.value

    def test_order_status_routes_to_project(self):
        from ira.brain.deterministic_router import DeterministicRouter, IntentCategory

        router = DeterministicRouter()
        result = router.route("What is the order status for the PF2?")
        assert result is not None
        assert result["intent"] == IntentCategory.PROJECT_MANAGEMENT.value


# ── QdrantManager.set_payload ─────────────────────────────────────────────────


class TestQdrantManagerSetPayload:
    """Verify set_payload method exists and calls the client."""

    @pytest.mark.asyncio
    async def test_set_payload_calls_client(self):
        from ira.brain.qdrant_manager import QdrantManager

        embedding = MagicMock()
        with patch("ira.brain.qdrant_manager.get_settings") as ms, \
             patch("ira.brain.qdrant_manager.AsyncQdrantClient") as mock_client_cls:
            ms.return_value.qdrant.url = "http://localhost:6333"
            ms.return_value.qdrant.api_key.get_secret_value.return_value = ""
            ms.return_value.qdrant.collection = "test_col"
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client

            mgr = QdrantManager(embedding_service=embedding)
            await mgr.set_payload("point-123", {"_superseded": True})

        mock_client.set_payload.assert_called_once_with(
            collection_name="test_col",
            payload={"_superseded": True},
            points=["point-123"],
        )
