"""Tests for previously-untested brain modules.

Covers: truth_hints, quality_filter, power_levels, adaptive_style,
knowledge_graph, feedback_handler, knowledge_health, correction_store,
correction_learner, graph_consolidation.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest


# ── TruthHintsEngine ─────────────────────────────────────────────────────


class TestTruthHints:
    @pytest.fixture()
    def hints_dir(self, tmp_path: Path) -> Path:
        manual = {
            "hints": [
                {
                    "patterns": [r"what\s+is\s+machinecraft"],
                    "keywords": ["machinecraft", "company"],
                    "answer": "Machinecraft builds thermoforming machines.",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ]
        }
        (tmp_path / "truth_hints.json").write_text(json.dumps(manual))
        (tmp_path / "learned_truth_hints.json").write_text(json.dumps({"hints": []}))
        return tmp_path

    async def _make_engine(self, hints_dir: Path):
        from ira.brain.truth_hints import TruthHintsEngine
        engine = TruthHintsEngine(data_dir=hints_dir)
        await engine._load()
        return engine

    @pytest.mark.asyncio
    async def test_match_returns_hit(self, hints_dir: Path):
        engine = await self._make_engine(hints_dir)
        result = engine.match("What is Machinecraft?")
        assert result is not None
        assert "thermoforming" in result["answer"]

    @pytest.mark.asyncio
    async def test_match_returns_none_for_unknown(self, hints_dir: Path):
        engine = await self._make_engine(hints_dir)
        assert engine.match("Tell me about quantum physics") is None

    @pytest.mark.asyncio
    async def test_is_complex_query(self, hints_dir: Path):
        engine = await self._make_engine(hints_dir)
        assert engine.is_complex_query("Compare X vs Y") is True
        assert engine.is_complex_query("What is X?") is False

    @pytest.mark.asyncio
    async def test_add_learned_hint(self, hints_dir: Path):
        engine = await self._make_engine(hints_dir)
        await engine.add_learned_hint(
            patterns=[r"who\s+founded"],
            keywords=["founded", "founder"],
            answer="John Smith founded Machinecraft.",
        )
        assert engine.get_stats()["learned"] == 1
        result = engine.match("Who founded Machinecraft?")
        assert result is not None

    @pytest.mark.asyncio
    async def test_stale_pricing_hints_skipped(self, tmp_path: Path):
        """Stale pricing hints (>90 days old) are skipped when query has pricing keywords."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=95)).isoformat()
        manual = {
            "hints": [
                {
                    "patterns": [r"pf1\s+price", r"price\s+of\s+pf1"],
                    "keywords": ["pf1", "price", "cost"],
                    "answer": "The PF1 costs $200,000.",
                    "created_at": old_date,
                },
            ]
        }
        (tmp_path / "truth_hints.json").write_text(json.dumps(manual))
        (tmp_path / "learned_truth_hints.json").write_text(json.dumps({"hints": []}))

        from ira.brain.truth_hints import TruthHintsEngine
        engine = TruthHintsEngine(data_dir=tmp_path)
        await engine._load()

        result = engine.match("What is the PF1 price?")
        assert result is None


# ── QualityFilter ────────────────────────────────────────────────────────


class TestQualityFilter:
    def _make_filter(self):
        from ira.brain.quality_filter import QualityFilter
        return QualityFilter()

    def test_filter_chunk_accepts_good_text(self):
        qf = self._make_filter()
        text = (
            "The PF1 thermoforming machine is designed for heavy gauge applications. "
            "It features servo-driven forming stations with precision temperature control "
            "and can handle materials up to 12mm thick at production speeds."
        )
        result = qf.filter_chunk(text)
        assert result["pass"] is True

    def test_filter_chunk_rejects_short_text(self):
        qf = self._make_filter()
        result = qf.filter_chunk("Too short.")
        assert result["pass"] is False
        assert "too short" in result["reason"]

    def test_filter_chunk_rejects_empty(self):
        qf = self._make_filter()
        result = qf.filter_chunk("")
        assert result["pass"] is False

    def test_filter_chunk_rejects_high_numeric_ratio(self):
        """Content with >70% numeric characters is rejected."""
        qf = self._make_filter()
        # 50 digits + 20 letters = 70 chars, ratio 50/70 ≈ 0.71 > 0.7
        text = (
            "a b c d e f g h i j k l m n o p q r s t "
            "12345678901234567890123456789012345678901234567890"
        )
        result = qf.filter_chunk(text)
        assert result["pass"] is False
        assert "numeric" in result["reason"]

    def test_detect_boilerplate(self):
        qf = self._make_filter()
        # Requires 2+ pattern matches; "Page X of Y" + "confidential" = 2 hits
        assert qf.detect_boilerplate("Page 3 of 10. Confidential document.") is True
        assert qf.detect_boilerplate("The machine operates at high speed") is False


# ── PowerLevelTracker ────────────────────────────────────────────────────


class TestPowerLevels:
    def _make_tracker(self, tmp_path: Path):
        from ira.brain.power_levels import PowerLevelTracker
        return PowerLevelTracker(data_path=tmp_path / "power_levels.json")

    @pytest.mark.asyncio
    async def test_record_success(self, tmp_path: Path):
        tracker = self._make_tracker(tmp_path)
        await tracker.record_success("clio", boost=10)
        level = tracker.get_level("clio")
        assert level["score"] == 10
        assert level["tier"] == "MORTAL"

    @pytest.mark.asyncio
    async def test_record_failure_decreases_score(self, tmp_path: Path):
        """record_failure() decreases score when above floor."""
        tracker = self._make_tracker(tmp_path)
        await tracker.record_success("clio", boost=100)
        await tracker.record_failure("clio", penalty=30)
        assert tracker.get_level("clio")["score"] == 70

    @pytest.mark.asyncio
    async def test_record_failure_floors_at_zero(self, tmp_path: Path):
        tracker = self._make_tracker(tmp_path)
        await tracker.record_failure("clio", penalty=100)
        assert tracker.get_level("clio")["score"] == 0

    @pytest.mark.asyncio
    async def test_get_tier_returns_correct_tier(self, tmp_path: Path):
        tracker = self._make_tracker(tmp_path)
        await tracker.record_success("clio", boost=50)
        level = tracker.get_level("clio")
        assert level["tier"] == "MORTAL"
        await tracker.record_success("athena", boost=350)  # 350 >= 301 = HERO
        assert tracker.get_level("athena")["tier"] == "HERO"

    @pytest.mark.asyncio
    async def test_leaderboard_sorted(self, tmp_path: Path):
        tracker = self._make_tracker(tmp_path)
        await tracker.record_success("clio", boost=50)
        await tracker.record_success("athena", boost=200)
        await tracker.record_success("vera", boost=100)
        board = tracker.get_leaderboard()
        assert board[0]["agent"] == "athena"
        assert board[1]["agent"] == "vera"

    def test_tier_thresholds(self):
        from ira.brain.power_levels import PowerLevelTracker
        assert PowerLevelTracker.get_tier(0) == "MORTAL"
        assert PowerLevelTracker.get_tier(101) == "WARRIOR"
        assert PowerLevelTracker.get_tier(301) == "HERO"
        assert PowerLevelTracker.get_tier(601) == "LEGEND"


# ── AdaptiveStyleTracker ─────────────────────────────────────────────────


class TestAdaptiveStyle:
    @pytest.fixture(autouse=True)
    def _patch_path(self, tmp_path: Path):
        with patch("ira.brain.adaptive_style._PROFILES_PATH", tmp_path / "profiles.json"):
            yield

    def test_analyze_message_formal(self):
        from ira.brain.adaptive_style import AdaptiveStyleTracker
        tracker = AdaptiveStyleTracker()
        deltas = tracker.analyze_message("Dear Sir, kindly find the attached proposal.")
        assert deltas.get("formality", 0) > 0

    @pytest.mark.asyncio
    async def test_update_and_get_profile(self):
        from ira.brain.adaptive_style import AdaptiveStyleTracker
        tracker = AdaptiveStyleTracker()
        await tracker.update_profile("test@example.com", "Hey, cool stuff! Thanks!")
        profile = tracker.get_profile("test@example.com")
        assert profile is not None
        assert profile["interactions"] == 1

    @pytest.mark.asyncio
    async def test_get_style_prompt(self):
        from ira.brain.adaptive_style import AdaptiveStyleTracker
        tracker = AdaptiveStyleTracker()
        formal_msg = "Dear Sir, kindly find herewith the pursuant regards sincerely."
        for _ in range(15):
            await tracker.update_profile("test@example.com", formal_msg)
        prompt = tracker.get_style_prompt("test@example.com")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ── KnowledgeGraph ───────────────────────────────────────────────────────


class TestKnowledgeGraph:
    @pytest.fixture()
    def mock_settings(self):
        s = MagicMock()
        s.neo4j.uri = "bolt://localhost:7687"
        s.neo4j.user = "neo4j"
        s.neo4j.password.get_secret_value.return_value = "test"
        s.llm.openai_api_key.get_secret_value.return_value = "test-key"
        s.llm.openai_model = "gpt-test"
        return s

    @pytest.fixture()
    def graph(self, mock_settings):
        with patch("ira.brain.knowledge_graph.get_settings", return_value=mock_settings), \
             patch("ira.brain.knowledge_graph.AsyncGraphDatabase") as mock_driver_cls:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.single.return_value = None
            mock_session.run = AsyncMock(return_value=mock_result)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_driver = MagicMock()
            mock_driver.session.return_value = mock_session
            mock_driver.close = AsyncMock()
            mock_driver_cls.driver.return_value = mock_driver
            from ira.brain.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph()
            kg._driver = mock_driver
            yield kg, mock_session

    @pytest.mark.asyncio
    async def test_add_company(self, graph):
        kg, session = graph
        await kg.add_company("TestCorp", region="US", industry="Manufacturing")
        session.execute_write.assert_awaited()

    @pytest.mark.asyncio
    async def test_find_company_contacts(self, graph):
        kg, session = graph
        mock_result = AsyncMock()
        mock_result.data = MagicMock(return_value=[{"name": "John", "email": "j@test.com"}])
        session.run = AsyncMock(return_value=mock_result)
        result = await kg.find_company_contacts("TestCorp")
        session.run.assert_awaited()

    @pytest.mark.asyncio
    async def test_graph_stats(self, graph):
        kg, session = graph
        mock_result = AsyncMock()
        mock_result.single.return_value = {"count": 5}
        session.run = AsyncMock(return_value=mock_result)
        stats = await kg.graph_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_extract_entities(self, graph):
        kg, _ = graph
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"entities": []}'}}]
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await kg.extract_entities_from_text("TestCorp builds machines.")
            assert isinstance(result, dict)


# ── FeedbackHandler ──────────────────────────────────────────────────────


class TestFeedbackHandler:
    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path):
        with patch("ira.brain.feedback_handler._SCORES_PATH", tmp_path / "scores.json"):
            yield

    def _make_handler(self):
        from ira.brain.feedback_handler import FeedbackHandler
        return FeedbackHandler()

    @pytest.mark.asyncio
    async def test_detect_positive_feedback(self):
        handler = self._make_handler()
        result = await handler.detect_feedback(
            "Thanks, that's perfect!",
            "What is the PF1 price?",
            "The PF1 costs $200,000.",
        )
        assert result["polarity"] == "positive"

    @pytest.mark.asyncio
    async def test_detect_negative_feedback(self):
        handler = self._make_handler()
        result = await handler.detect_feedback(
            "That's not right, the price is $150,000.",
            "What is the PF1 price?",
            "The PF1 costs $200,000.",
        )
        assert result["polarity"] == "negative"
        assert result["extracted_correction"] is not None

    @pytest.mark.asyncio
    async def test_detect_neutral(self):
        handler = self._make_handler()
        result = await handler.detect_feedback(
            "Can you also check the delivery schedule?",
            "What is the PF1 price?",
            "The PF1 costs $200,000.",
        )
        assert result["polarity"] == "neutral"


# ── KnowledgeHealthMonitor ───────────────────────────────────────────────


class TestKnowledgeHealth:
    def _make_monitor(self, tmp_path: Path):
        mk_data = {
            "machine_catalog": {"PF1": {"category": "heavy_gauge"}},
            "truth_hints": {"pf1 price range": "$180,000-$220,000"},
        }
        mk_path = tmp_path / "machine_knowledge.json"
        mk_path.write_text(json.dumps(mk_data))

        from ira.brain.knowledge_health import KnowledgeHealthMonitor
        qdrant = AsyncMock()
        qdrant.search = AsyncMock(return_value=[])
        return KnowledgeHealthMonitor(
            qdrant_manager=qdrant,
            machine_knowledge_path=str(mk_path),
        )

    def test_validate_business_rules_clean(self, tmp_path: Path):
        monitor = self._make_monitor(tmp_path)
        violations = monitor.validate_business_rules("The PF1 handles heavy gauge materials.")
        assert violations == []

    @pytest.mark.asyncio
    async def test_detect_hallucinations_superlative(self, tmp_path: Path):
        monitor = self._make_monitor(tmp_path)
        flags = await monitor.detect_hallucinations("We are the world's leading manufacturer.")
        assert any("world's leading" in f for f in flags)

    @pytest.mark.asyncio
    async def test_verify_price_within_tolerance(self, tmp_path: Path):
        monitor = self._make_monitor(tmp_path)
        result = await monitor.verify_price("PF1", 200_000)
        assert result["verified"] is True


# ── GraphConsolidation ───────────────────────────────────────────────────


class TestGraphConsolidation:
    def _make_consolidation(self, tmp_path: Path):
        from ira.brain.graph_consolidation import GraphConsolidation
        mock_graph = AsyncMock()
        log_path = tmp_path / "retrieval_log.jsonl"
        return GraphConsolidation(
            knowledge_graph=mock_graph,
            retrieval_log_path=log_path,
        ), log_path

    async def test_log_retrieval_writes_jsonl(self, tmp_path: Path):
        gc, log_path = self._make_consolidation(tmp_path)
        await gc.log_retrieval(
            query="PF1 specs",
            chunks_retrieved=["chunk_a", "chunk_b"],
            source_types=["qdrant"],
        )
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["query"] == "PF1 specs"
        assert entry["chunks"] == ["chunk_a", "chunk_b"]
        assert "timestamp" in entry

    async def test_log_retrieval_appends_multiple(self, tmp_path: Path):
        gc, log_path = self._make_consolidation(tmp_path)
        await gc.log_retrieval("q1", ["a"], ["qdrant"])
        await gc.log_retrieval("q2", ["b", "c"], ["neo4j"])

        lines = [l for l in log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2

    async def test_build_co_access_matrix_counts_pairs(self, tmp_path: Path):
        gc, log_path = self._make_consolidation(tmp_path)

        await gc.log_retrieval("q1", ["alpha", "beta", "gamma"], ["qdrant"])
        await gc.log_retrieval("q2", ["alpha", "beta"], ["qdrant"])
        await gc.log_retrieval("q3", ["alpha", "gamma"], ["neo4j"])

        matrix = await gc.build_co_access_matrix()

        ab_key = "|||".join(sorted(["alpha", "beta"]))
        ag_key = "|||".join(sorted(["alpha", "gamma"]))
        bg_key = "|||".join(sorted(["beta", "gamma"]))

        assert matrix[ab_key] == 2
        assert matrix[ag_key] == 2
        assert matrix[bg_key] == 1

    async def test_build_co_access_matrix_empty_log(self, tmp_path: Path):
        gc, _ = self._make_consolidation(tmp_path)
        matrix = await gc.build_co_access_matrix()
        assert matrix == {}

    async def test_build_co_access_matrix_single_chunk_no_pairs(self, tmp_path: Path):
        gc, _ = self._make_consolidation(tmp_path)
        await gc.log_retrieval("q1", ["only_one"], ["qdrant"])
        matrix = await gc.build_co_access_matrix()
        assert matrix == {}


# ── CorrectionStore ──────────────────────────────────────────────────────


class TestCorrectionStore:
    async def _make_store(self, tmp_path: Path):
        from ira.brain.correction_store import CorrectionStore
        store = CorrectionStore(db_path=tmp_path / "corrections.db")
        await store.initialize()
        return store

    @pytest.mark.asyncio
    async def test_initialize_creates_table(self, tmp_path: Path):
        """initialize() creates the corrections table."""
        from ira.brain.correction_store import CorrectionStore

        db_path = tmp_path / "corrections.db"
        store = CorrectionStore(db_path=db_path)
        await store.initialize()
        try:
            async with aiosqlite.connect(str(db_path)) as conn:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='corrections'"
                )
                row = await cursor.fetchone()
                await cursor.close()
            assert row is not None
            assert row[0] == "corrections"
        finally:
            await store.close()

    @pytest.mark.asyncio
    async def test_add_and_get_pending(self, tmp_path: Path):
        store = await self._make_store(tmp_path)
        try:
            row_id = await store.add_correction(
                entity="PF1",
                new_value="Price is $190,000",
                old_value="Price is $200,000",
                source="api",
            )
            assert row_id > 0

            pending = await store.get_pending_corrections()
            assert len(pending) == 1
            assert pending[0]["entity"] == "PF1"
            assert pending[0]["new_value"] == "Price is $190,000"
            assert pending[0]["status"] == "pending"
        finally:
            await store.close()

    async def test_mark_processed_removes_from_pending(self, tmp_path: Path):
        store = await self._make_store(tmp_path)
        try:
            row_id = await store.add_correction(entity="PF1", new_value="updated")
            await store.mark_processed(row_id)

            pending = await store.get_pending_corrections()
            assert len(pending) == 0
        finally:
            await store.close()

    async def test_get_corrections_by_entity(self, tmp_path: Path):
        store = await self._make_store(tmp_path)
        try:
            await store.add_correction(entity="PF1", new_value="v1")
            await store.add_correction(entity="AM200", new_value="v2")
            await store.add_correction(entity="PF1", new_value="v3")

            pf1_corrections = await store.get_corrections_by_entity("PF1")
            assert len(pf1_corrections) == 2
            assert all(c["entity"] == "PF1" for c in pf1_corrections)
        finally:
            await store.close()

    async def test_category_and_severity_stored(self, tmp_path: Path):
        from ira.brain.correction_store import CorrectionCategory, CorrectionSeverity

        store = await self._make_store(tmp_path)
        try:
            await store.add_correction(
                entity="PF1",
                new_value="new price",
                category=CorrectionCategory.PRICING,
                severity=CorrectionSeverity.CRITICAL,
            )
            pending = await store.get_pending_corrections()
            assert pending[0]["category"] == "PRICING"
            assert pending[0]["severity"] == "CRITICAL"
        finally:
            await store.close()

    async def test_get_stats(self, tmp_path: Path):
        store = await self._make_store(tmp_path)
        try:
            id1 = await store.add_correction(entity="A", new_value="x")
            await store.add_correction(entity="B", new_value="y")
            await store.mark_processed(id1)

            stats = await store.get_stats()
            assert stats["total"] == 2
            assert stats["by_status"]["pending"] == 1
            assert stats["by_status"]["processed"] == 1
        finally:
            await store.close()

    async def test_context_manager(self, tmp_path: Path):
        from ira.brain.correction_store import CorrectionStore

        async with CorrectionStore(db_path=tmp_path / "ctx.db") as store:
            row_id = await store.add_correction(entity="X", new_value="val")
            assert row_id > 0

    async def test_pending_limit(self, tmp_path: Path):
        store = await self._make_store(tmp_path)
        try:
            for i in range(5):
                await store.add_correction(entity=f"E{i}", new_value=f"v{i}")

            limited = await store.get_pending_corrections(limit=2)
            assert len(limited) == 2
        finally:
            await store.close()


# ── CorrectionLearner ────────────────────────────────────────────────────


class TestCorrectionLearner:
    def _make_learner(self, tmp_path: Path):
        from ira.brain.correction_learner import CorrectionLearner
        return CorrectionLearner(data_path=tmp_path / "learned_corrections.json")

    @pytest.mark.asyncio
    async def test_learn_from_correction_entity_role(self, tmp_path: Path):
        """learn_from_correction() parses entity role corrections (competitor, customer)."""
        learner = self._make_learner(tmp_path)
        learned = await learner.learn_from_correction("Acme Corp is a competitor")
        assert "Acme Corp" in learned["competitors_added"]
        assert learner.is_competitor("Acme Corp") is True
        assert learner.is_customer("Acme Corp") is False

    @pytest.mark.asyncio
    async def test_learn_from_correction_customer(self, tmp_path: Path):
        learner = self._make_learner(tmp_path)
        await learner.learn_from_correction("Beta Industries are customers")
        assert learner.is_customer("Beta Industries") is True
        assert learner.is_competitor("Beta Industries") is False

    def test_is_competitor_and_is_customer(self, tmp_path: Path):
        """is_competitor() and is_customer() return correct values after learning."""
        learner = self._make_learner(tmp_path)
        learner._state["competitors"] = ["Acme Corp", "Rival Inc"]
        learner._state["customers"] = ["Happy Client Ltd"]
        assert learner.is_competitor("Acme Corp") is True
        assert learner.is_competitor("acme corp") is True
        assert learner.is_competitor("Unknown Co") is False
        assert learner.is_customer("Happy Client Ltd") is True
        assert learner.is_customer("happy client ltd") is True
        assert learner.is_customer("Acme Corp") is False

    @pytest.mark.asyncio
    async def test_get_entity_correction(self, tmp_path: Path):
        """get_entity_correction() returns rename mapping from learned corrections."""
        learner = self._make_learner(tmp_path)
        await learner.learn_from_correction(
            "PF1 is not PF2, it's PF1-X"
        )
        assert learner.get_entity_correction("PF2") == "PF1-X"
        assert learner.get_entity_correction("pf2") == "PF1-X"
        assert learner.get_entity_correction("unknown") is None


# ── DataEventBus ─────────────────────────────────────────────────────────


class TestDataEventBus:
    def _make_event(self, event_type=None, entity_id="test-1"):
        from ira.systems.data_event_bus import (
            DataEvent,
            EventType,
            SourceStore,
        )
        return DataEvent(
            event_type=event_type or EventType.CONTACT_CREATED,
            entity_type="contact",
            entity_id=entity_id,
            payload={"name": "Test Contact"},
            source_store=SourceStore.CRM,
        )

    async def test_subscribe_and_emit(self):
        from ira.systems.data_event_bus import DataEventBus, EventType

        bus = DataEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.CONTACT_CREATED, handler)
        await bus.start()
        try:
            await bus.emit(self._make_event())
            await asyncio.sleep(0.05)
        finally:
            await bus.stop()

        assert len(received) == 1
        assert received[0].entity_id == "test-1"

    async def test_handler_only_receives_subscribed_type(self):
        from ira.systems.data_event_bus import DataEventBus, EventType

        bus = DataEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.DEAL_CREATED, handler)
        await bus.start()
        try:
            await bus.emit(self._make_event(EventType.CONTACT_CREATED))
            await asyncio.sleep(0.05)
        finally:
            await bus.stop()

        assert len(received) == 0

    async def test_subscribe_all_receives_everything(self):
        from ira.systems.data_event_bus import DataEventBus, EventType

        bus = DataEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_all(handler)
        await bus.start()
        try:
            await bus.emit(self._make_event(EventType.CONTACT_CREATED, "c1"))
            await bus.emit(self._make_event(EventType.DEAL_CREATED, "d1"))
            await asyncio.sleep(0.05)
        finally:
            await bus.stop()

        assert len(received) == 2

    async def test_start_stop_idempotent(self):
        from ira.systems.data_event_bus import DataEventBus

        bus = DataEventBus()
        await bus.start()
        await bus.start()
        assert bus._running is True

        await bus.stop()
        assert bus._running is False
        assert bus._task is None

        await bus.stop()

    async def test_handler_error_does_not_crash_bus(self):
        from ira.systems.data_event_bus import DataEventBus, EventType

        bus = DataEventBus()
        ok_received = []

        async def bad_handler(event):
            raise ValueError("handler boom")

        async def good_handler(event):
            ok_received.append(event)

        bus.subscribe(EventType.CONTACT_CREATED, bad_handler)
        bus.subscribe(EventType.CONTACT_CREATED, good_handler)
        await bus.start()
        try:
            await bus.emit(self._make_event())
            await asyncio.sleep(0.05)
        finally:
            await bus.stop()

        assert len(ok_received) == 1

    async def test_pending_count(self):
        from ira.systems.data_event_bus import DataEventBus

        bus = DataEventBus()
        assert bus.pending_count == 0
        await bus.emit(self._make_event())
        assert bus.pending_count == 1

    async def test_queue_full_drops_event(self):
        from ira.systems.data_event_bus import DataEventBus

        bus = DataEventBus(maxsize=1)
        await bus.emit(self._make_event(entity_id="first"))
        await bus.emit(self._make_event(entity_id="dropped"))
        assert bus.pending_count == 1
