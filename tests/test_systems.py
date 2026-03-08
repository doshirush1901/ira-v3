"""Tests for the ira.systems package.

Covers DigestiveSystem, RespiratorySystem, ImmuneSystem, EndocrineSystem,
SensorySystem, and VoiceSystem.  All external services are mocked so the
suite runs fully offline.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.data.models import Channel, Contact, Direction, Email
from ira.schemas.llm_outputs import (
    CorrectionAnalysis,
    DigestiveSummary,
    DreamCampaignInsights,
    DreamCreative,
    DreamConnection,
    DreamGaps,
    DreamInsight,
    DreamProcedure,
    DreamProcedures,
    DreamPrune,
    EmailMetadata,
    EmailSenderInfo,
    GapAnalysis,
    NutrientClassification,
    ProcedureSteps,
)


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_openai_response(content: str) -> MagicMock:
    """Build a mock httpx response that looks like an OpenAI chat completion."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    return mock_resp


def _make_settings_mock():
    """Return a mock Settings object with dummy credentials."""
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-4.1"
    s.embedding.api_key.get_secret_value.return_value = "test-voyage"
    s.embedding.model = "voyage-3"
    s.qdrant.url = "http://localhost:6333"
    s.qdrant.collection = "test_collection"
    s.neo4j.uri = "bolt://localhost:7687"
    s.neo4j.user = "neo4j"
    s.neo4j.password.get_secret_value.return_value = "test"
    s.database.url = "sqlite+aiosqlite://"
    s.telegram.bot_token.get_secret_value.return_value = "test-token"
    s.telegram.admin_chat_id = "12345"
    s.memory.api_key.get_secret_value.return_value = ""
    s.google.credentials_path = "creds.json"
    s.google.token_path = "token.json"
    s.google.ira_email = "ira@test.com"
    s.external_apis.api_key.get_secret_value.return_value = ""
    s.app.log_level = "INFO"
    s.app.environment = "test"
    return s


def _mock_llm_client():
    """Return a mock LLMClient with all generation methods stubbed."""
    client = MagicMock()
    client._openai = MagicMock()
    client.generate_structured = AsyncMock()
    client.generate_text = AsyncMock(return_value="")
    client.generate_text_with_fallback = AsyncMock(return_value="")
    client.generate_structured_with_fallback = AsyncMock()
    return client


# ═════════════════════════════════════════════════════════════════════════
# 1. DigestiveSystem
# ═════════════════════════════════════════════════════════════════════════


class TestDigestiveSystem:
    """Tests for ira.systems.digestive.DigestiveSystem."""

    @pytest.fixture()
    def digestive_system(self):
        mock_ingestor = MagicMock()
        mock_graph = AsyncMock()
        mock_graph.extract_entities_from_text = AsyncMock(return_value={
            "companies": [{"name": "Acme Corp", "region": "MENA", "industry": "Manufacturing"}],
            "people": [{"name": "Alice", "email": "alice@acme.com", "company": "Acme Corp", "role": "CEO"}],
            "machines": [{"model": "PF1-C", "category": "Packaging", "description": "Compact line"}],
            "relationships": [],
        })
        mock_graph.add_company = AsyncMock()
        mock_graph.add_person = AsyncMock()
        mock_graph.add_machine = AsyncMock()

        mock_embeddings = AsyncMock()
        mock_qdrant = AsyncMock()
        mock_qdrant.upsert_items = AsyncMock(side_effect=lambda items: len(items))

        with patch("ira.systems.digestive.get_llm_client", return_value=_mock_llm_client()):
            from ira.systems.digestive import DigestiveSystem
            ds = DigestiveSystem(mock_ingestor, mock_graph, mock_embeddings, mock_qdrant)

        ds._graph = mock_graph
        ds._qdrant = mock_qdrant
        ds._quality_filter = MagicMock()
        ds._quality_filter.filter_chunk = MagicMock(return_value={"pass": True, "quality_score": 1.0})
        return ds

    @pytest.mark.asyncio
    async def test_ingest_separates_nutrients(self, digestive_system):
        mock_nutrients = NutrientClassification(
            protein=["Revenue was $5M in Q3", "Deal closes March 15"],
            carbs=["The company is based in Dubai"],
            waste=["Best regards", "Sent from my iPhone"],
        )
        mock_summary = DigestiveSummary(statements=["Revenue was $5M in Q3", "Deal closes March 15"])

        async def mock_structured(system, user, model_cls, **kwargs):
            if model_cls is NutrientClassification:
                return mock_nutrients
            if model_cls is DigestiveSummary:
                return mock_summary
            return model_cls()

        digestive_system._llm.generate_structured = AsyncMock(side_effect=mock_structured)

        result = await digestive_system.ingest("Some email body", "test@example.com", "email")

        assert result["nutrients_extracted"]["protein"] == 2
        assert result["nutrients_extracted"]["carbs"] == 1
        assert result["nutrients_extracted"]["waste"] == 2

    @pytest.mark.asyncio
    async def test_ingest_stores_only_protein_and_carbs(self, digestive_system):
        mock_nutrients = NutrientClassification(
            protein=["Important fact"],
            carbs=["Some context"],
            waste=["Signature block"],
        )
        mock_summary_protein = DigestiveSummary(statements=["Important fact"])
        mock_summary_carbs = DigestiveSummary(statements=["Some context"])

        call_count = 0
        async def mock_structured(system, user, model_cls, **kwargs):
            nonlocal call_count
            if model_cls is NutrientClassification:
                return mock_nutrients
            if model_cls is DigestiveSummary:
                call_count += 1
                return mock_summary_protein if call_count == 1 else mock_summary_carbs
            return model_cls()

        digestive_system._llm.generate_structured = AsyncMock(side_effect=mock_structured)

        await digestive_system.ingest("Body text", "src", "cat")

        digestive_system._qdrant.upsert_items.assert_called_once()
        items = digestive_system._qdrant.upsert_items.call_args[0][0]
        contents = [item.content for item in items]
        assert any("Important fact" in c for c in contents)
        assert any("Some context" in c for c in contents)
        assert not any("Signature block" in c for c in contents)

    @pytest.mark.asyncio
    async def test_ingest_extracts_entities_from_protein(self, digestive_system):
        mock_nutrients = NutrientClassification(
            protein=["Acme Corp ordered a PF1-C"],
            carbs=[],
            waste=[],
        )
        mock_summary = DigestiveSummary(statements=["Acme Corp ordered a PF1-C"])

        async def mock_structured(system, user, model_cls, **kwargs):
            if model_cls is NutrientClassification:
                return mock_nutrients
            if model_cls is DigestiveSummary:
                return mock_summary
            return model_cls()

        digestive_system._llm.generate_structured = AsyncMock(side_effect=mock_structured)

        result = await digestive_system.ingest("Body", "src", "cat")

        digestive_system._graph.extract_entities_from_text.assert_called_once()
        digestive_system._graph.add_company.assert_called_once()
        digestive_system._graph.add_person.assert_called_once()
        digestive_system._graph.add_machine.assert_called_once()
        assert result["entities_found"]["companies"] == 1

    @pytest.mark.asyncio
    async def test_ingest_email_extracts_metadata(self, digestive_system):
        email = Email(
            id="msg-1",
            from_address="alice@acme.com",
            to_address="ira@machinecraft.org",
            subject="Quote Request",
            body="We need pricing for PF1-C machines. Budget is $500K. Deadline March 30.",
            received_at=datetime.now(timezone.utc),
        )

        mock_nutrients = NutrientClassification(
            protein=["pricing for PF1-C"], carbs=[], waste=[],
        )
        mock_summary = DigestiveSummary(statements=["pricing for PF1-C"])
        mock_meta = EmailMetadata(
            sender_info=EmailSenderInfo(name="Alice", company="Acme Corp"),
            company_mentions=["Acme Corp"],
            machine_mentions=["PF1-C"],
            pricing_mentions=["$500K"],
            dates_deadlines=["March 30"],
        )

        async def mock_structured(system, user, model_cls, **kwargs):
            if model_cls is NutrientClassification:
                return mock_nutrients
            if model_cls is DigestiveSummary:
                return mock_summary
            if model_cls is EmailMetadata:
                return mock_meta
            return model_cls()

        digestive_system._llm.generate_structured = AsyncMock(side_effect=mock_structured)

        result = await digestive_system.ingest_email(email)

        assert "email_metadata" in result
        assert result["email_id"] == "msg-1"
        assert "PF1-C" in result["email_metadata"]["machine_mentions"]


# ═════════════════════════════════════════════════════════════════════════
# 2. RespiratorySystem
# ═════════════════════════════════════════════════════════════════════════


class TestRespiratorySystem:
    """Tests for ira.systems.respiratory.RespiratorySystem."""

    @pytest.fixture()
    def respiratory_system(self):
        with patch("ira.systems.respiratory.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.respiratory import RespiratorySystem
            rs = RespiratorySystem(
                heartbeat_interval_seconds=1,
            )
        return rs

    @pytest.mark.asyncio
    async def test_start_creates_heartbeat_task(self, respiratory_system):
        await respiratory_system.start()
        try:
            assert respiratory_system._heartbeat_task is not None
            assert not respiratory_system._heartbeat_task.done()
        finally:
            await respiratory_system.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self, respiratory_system):
        await respiratory_system.start()
        task = respiratory_system._heartbeat_task
        await respiratory_system.stop()
        assert respiratory_system._heartbeat_task is None
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_breath_context_manager_measures_duration(self, respiratory_system):
        async with respiratory_system.breath():
            await asyncio.sleep(0.05)

        assert len(respiratory_system._breath_durations) == 1
        duration = respiratory_system._breath_durations[0]
        assert 30 < duration < 200  # ~50ms with tolerance


# ═════════════════════════════════════════════════════════════════════════
# 3. ImmuneSystem
# ═════════════════════════════════════════════════════════════════════════


class TestImmuneSystem:
    """Tests for ira.systems.immune.ImmuneSystem."""

    @pytest.fixture()
    def immune_system(self):
        mock_qdrant = MagicMock()
        mock_qdrant._client = AsyncMock()
        mock_qdrant._default_collection = "test_collection"

        mock_graph = AsyncMock()
        mock_graph.run_cypher = AsyncMock(return_value=[{"ok": 1}])

        mock_embeddings = AsyncMock()
        mock_embeddings.embed_texts = AsyncMock(return_value=[[0.1] * 8])

        with patch("ira.systems.immune.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.immune import ImmuneSystem
            immune = ImmuneSystem(mock_qdrant, mock_graph, mock_embeddings)

        immune._qdrant = mock_qdrant
        immune._graph = mock_graph
        immune._embeddings = mock_embeddings
        return immune

    @pytest.mark.asyncio
    async def test_startup_validation_all_healthy(self, immune_system):
        mock_collection = MagicMock()
        mock_collection.name = "test_collection"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]
        immune_system._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        immune_system._check_postgresql = AsyncMock(return_value={"status": "healthy", "latency_ms": 5.0, "error": None})

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            report = await immune_system.run_startup_validation()

        assert report["qdrant"]["status"] == "healthy"
        assert report["neo4j"]["status"] == "healthy"
        assert report["voyage"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_startup_validation_critical_failure_raises(self, immune_system):
        immune_system._qdrant._client.get_collections = AsyncMock(side_effect=ConnectionError("refused"))
        immune_system._check_postgresql = AsyncMock(return_value={"status": "healthy", "latency_ms": 5.0, "error": None})

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            from ira.systems.immune import SystemHealthError
            with pytest.raises(SystemHealthError) as exc_info:
                await immune_system.run_startup_validation()

            assert exc_info.value.health_report["qdrant"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_startup_validation_noncritical_failure_warns(self, immune_system):
        mock_collection = MagicMock()
        mock_collection.name = "test_collection"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]
        immune_system._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        immune_system._check_postgresql = AsyncMock(return_value={"status": "healthy", "latency_ms": 5.0, "error": None})

        # OpenAI fails
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=ConnectionError("timeout")):
            report = await immune_system.run_startup_validation()

        assert report["openai"]["status"] == "unhealthy"
        assert report["qdrant"]["status"] == "healthy"
        assert report["neo4j"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_log_error_triggers_alert_on_threshold(self, immune_system):
        immune_system.send_alert = AsyncMock()

        for i in range(5):
            immune_system.log_error(
                RuntimeError(f"error {i}"),
                {"service": "qdrant"},
            )

        await asyncio.sleep(0.1)  # let the created task run
        immune_system.send_alert.assert_called_once()
        call_args = immune_system.send_alert.call_args
        assert "critical" in call_args.kwargs.get("severity", call_args.args[1] if len(call_args.args) > 1 else "")


# ═════════════════════════════════════════════════════════════════════════
# 4. EndocrineSystem
# ═════════════════════════════════════════════════════════════════════════


class TestEndocrineSystem:
    """Tests for ira.systems.endocrine.EndocrineSystem."""

    @pytest.fixture()
    def endocrine(self):
        from ira.systems.endocrine import EndocrineSystem
        return EndocrineSystem()

    def test_initial_levels_at_baseline(self, endocrine):
        status = endocrine.get_status()
        assert status["confidence"] == pytest.approx(0.5)
        assert status["energy"] == pytest.approx(0.5)
        assert status["growth_signal"] == pytest.approx(0.5)
        assert status["stress"] == pytest.approx(0.5)
        assert status["caution"] == pytest.approx(0.5)

    def test_boost_increases_level(self, endocrine):
        endocrine.boost("confidence", 0.2)
        assert endocrine.get_status()["confidence"] == pytest.approx(0.7)

    def test_boost_caps_at_one(self, endocrine):
        endocrine.boost("confidence", 0.9)
        assert endocrine.get_status()["confidence"] == pytest.approx(1.0)

    def test_dampen_floors_at_zero(self, endocrine):
        endocrine.dampen("stress", 0.9)
        assert endocrine.get_status()["stress"] == pytest.approx(0.0)

    def test_signal_success_adjusts_levels(self, endocrine):
        endocrine.signal_success("clio")
        status = endocrine.get_status()
        assert status["confidence"] > 0.5
        assert status["energy"] > 0.5
        assert status["stress"] < 0.5

    def test_behavioral_modifiers_high_confidence(self, endocrine):
        endocrine.boost("confidence", 0.3)  # -> 0.8
        endocrine.dampen("stress", 0.1)
        mods = endocrine.get_behavioral_modifiers()
        assert mods["assertiveness"] == "high"

    def test_behavioral_modifiers_low_confidence_high_stress(self, endocrine):
        endocrine.dampen("confidence", 0.3)  # -> 0.2
        endocrine.boost("stress", 0.3)       # -> 0.8
        mods = endocrine.get_behavioral_modifiers()
        assert mods["assertiveness"] == "low"

    def test_boost_unknown_hormone_is_noop(self, endocrine):
        endocrine.boost("invalid_name", 0.1)
        assert "invalid_name" not in endocrine.get_status()


# ═════════════════════════════════════════════════════════════════════════
# 5. SensorySystem
# ═════════════════════════════════════════════════════════════════════════


class TestSensorySystem:
    """Tests for ira.systems.sensory.SensorySystem."""

    @pytest.fixture()
    async def sensory_system(self):
        mock_graph = AsyncMock()
        mock_graph.add_person = AsyncMock()

        with patch("ira.systems.sensory.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.sensory import SensorySystem
            ss = SensorySystem(
                mock_graph,
                database_url="sqlite+aiosqlite://",
            )

        await ss.create_tables()
        yield ss
        await ss.close()

    @pytest.mark.asyncio
    async def test_resolve_identity_email_creates_contact(self, sensory_system):
        contact = await sensory_system.resolve_identity("EMAIL", "alice@example.com", "Alice")
        assert contact.email == "alice@example.com"
        assert contact.name == "Alice"

        # Idempotent
        contact2 = await sensory_system.resolve_identity("EMAIL", "alice@example.com", "Alice")
        assert contact2.email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_resolve_identity_telegram_creates_placeholder(self, sensory_system):
        contact = await sensory_system.resolve_identity("TELEGRAM", "12345", "Bob")
        assert "12345" in contact.email
        assert contact.name == "Bob"

    @pytest.mark.asyncio
    async def test_link_identity_merges_channels(self, sensory_system):
        await sensory_system.resolve_identity("TELEGRAM", "12345", "Bob")
        await sensory_system.link_identity("TELEGRAM", "12345", "bob@example.com")

        # Clear cache to force DB lookup
        sensory_system._identity_cache.clear()
        contact = await sensory_system.resolve_identity("TELEGRAM", "12345", "Bob")
        assert contact.email == "bob@example.com"


# ═════════════════════════════════════════════════════════════════════════
# 6. VoiceSystem
# ═════════════════════════════════════════════════════════════════════════


class TestVoiceSystem:
    """Tests for ira.systems.voice.VoiceSystem."""

    @pytest.fixture()
    def voice_system(self):
        with patch("ira.systems.voice.get_llm_client", return_value=_mock_llm_client()):
            from ira.systems.voice import VoiceSystem
            vs = VoiceSystem()
        return vs

    @pytest.fixture()
    def sample_contact(self):
        return Contact(
            name="Alice",
            email="alice@example.com",
            company="Acme",
            source="test",
        )

    @pytest.mark.asyncio
    async def test_shape_response_api_returns_raw(self, voice_system):
        result = await voice_system.shape_response("raw text", "API", None, {})
        assert result == "raw text"

    @pytest.mark.asyncio
    async def test_shape_response_telegram_enforces_length(self, voice_system):
        long_response = "A" * 5000

        voice_system._llm.generate_text = AsyncMock(return_value=long_response)
        result = await voice_system.shape_response(long_response, "TELEGRAM", None, {})

        assert len(result) <= 2003  # 2000 + "..."

    @pytest.mark.asyncio
    async def test_shape_response_applies_behavioral_modifiers(self, voice_system):
        modifiers = {"prompt_addendum": "Be cautious.", "verbosity": "detailed"}

        voice_system._llm.generate_text = AsyncMock(return_value="shaped")
        await voice_system.shape_response(
            "Some long response that needs reshaping " * 20,
            "TELEGRAM", None, modifiers,
        )

        system_prompt_arg = voice_system._llm.generate_text.call_args[0][0]
        assert "Be cautious." in system_prompt_arg

    def test_detect_preferred_style_defaults(self, voice_system, sample_contact):
        style = voice_system.detect_preferred_style(sample_contact, [])
        assert "formality" in style
        assert "detail_level" in style
        assert "technical_level" in style

    def test_format_for_email_includes_greeting(self, voice_system):
        result = voice_system.format_for_email("Hello content", "Alice", "Test Subject")
        assert result.startswith("Dear Alice,")
        assert "Machinecraft AI Assistant" in result


# ═════════════════════════════════════════════════════════════════════════
# 7. LearningHub
# ═════════════════════════════════════════════════════════════════════════


class TestLearningHub:
    """Tests for ira.systems.learning_hub.LearningHub."""

    @pytest.fixture()
    def mock_crm(self):
        crm = AsyncMock()
        interaction = MagicMock()
        interaction.id = str(uuid4())
        interaction.subject = "What is the PF1-C lead time?"
        interaction.content = "The lead time is 6 weeks."
        interaction.channel = Channel.CLI
        interaction.direction = Direction.INBOUND
        crm.get_interaction = AsyncMock(return_value=interaction)
        crm.create_interaction = AsyncMock(return_value=interaction)
        return crm

    @pytest.fixture()
    def mock_procedural(self):
        proc = AsyncMock()
        proc.record_failure = AsyncMock()
        proc.learn_procedure = AsyncMock(return_value=MagicMock(
            id=1,
            trigger_pattern="lead time for {machine}",
            steps=["Step 1: Look up machine", "Step 2: Check inventory"],
            success_rate=1.0,
            times_used=1,
        ))
        return proc

    @pytest.fixture()
    def learning_hub(self, mock_crm, mock_procedural):
        with (
            patch("ira.systems.learning_hub.get_settings", return_value=_make_settings_mock()),
            patch("ira.systems.learning_hub.get_llm_client", return_value=_mock_llm_client()),
        ):
            from ira.systems.learning_hub import LearningHub
            hub = LearningHub(crm=mock_crm, procedural_memory=mock_procedural)
        hub._recent_feedback = []
        return hub

    @pytest.mark.asyncio
    async def test_process_feedback_good_score(self, learning_hub, mock_crm):
        record = await learning_hub.process_feedback("int-1", feedback_score=8)
        assert record.feedback_score == 8
        assert record.gap_analysis == {}
        assert record.interaction_id == "int-1"

    @pytest.mark.asyncio
    async def test_process_feedback_poor_score_triggers_gap_analysis(
        self, learning_hub, mock_procedural,
    ):
        mock_gap = GapAnalysis(
            gap_type="KNOWLEDGE_GAP",
            description="Missing lead-time data",
            suggested_skill_name="",
            suggested_skill_description="",
            suggested_knowledge_source="production database",
        )
        learning_hub._llm.generate_structured = AsyncMock(return_value=mock_gap)

        record = await learning_hub.process_feedback("int-2", feedback_score=2)

        assert record.gap_analysis.get("gap_type") == "KNOWLEDGE_GAP"
        mock_procedural.record_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_feedback_with_correction(self, learning_hub, mock_crm):
        mock_correction = CorrectionAnalysis(
            error_category="FACTUAL",
            what_was_wrong="Wrong lead time",
            correct_behaviour="Should say 8 weeks not 6",
        )
        mock_gap = GapAnalysis(
            gap_type="QUALITY_ISSUE",
            description="Incorrect fact",
        )

        async def mock_structured(system, user, model_cls, **kwargs):
            if model_cls is CorrectionAnalysis:
                return mock_correction
            if model_cls is GapAnalysis:
                return mock_gap
            return model_cls()

        learning_hub._llm.generate_structured = AsyncMock(side_effect=mock_structured)

        record = await learning_hub.process_feedback(
            "int-3", feedback_score=2, correction="The lead time is 8 weeks.",
        )

        assert record.correction == "The lead time is 8 weeks."
        assert record.correction_analysis.get("error_category") == "FACTUAL"

    @pytest.mark.asyncio
    async def test_suggest_procedure_from_interaction(self, learning_hub, mock_procedural):
        mock_steps = ProcedureSteps(
            steps=["Step 1: Look up machine", "Step 2: Check inventory"],
        )
        learning_hub._llm.generate_structured = AsyncMock(return_value=mock_steps)

        procedure = await learning_hub.suggest_procedure("int-1")

        assert procedure is not None
        assert procedure.trigger_pattern == "lead time for {machine}"
        mock_procedural.learn_procedure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suggest_procedure_missing_interaction(self, learning_hub, mock_crm):
        mock_crm.get_interaction.return_value = None
        result = await learning_hub.suggest_procedure("missing-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_weak_areas_returns_poor_feedback(self, learning_hub):
        mock_gap = GapAnalysis(gap_type="MISSING_SKILL", description="test")
        learning_hub._llm.generate_structured = AsyncMock(return_value=mock_gap)

        await learning_hub.process_feedback("int-a", feedback_score=1)
        await learning_hub.process_feedback("int-b", feedback_score=8)
        await learning_hub.process_feedback("int-c", feedback_score=2)

        weak = learning_hub.get_weak_areas(limit=5)
        assert len(weak) == 2
        assert weak[0]["score"] == 1
        assert weak[1]["score"] == 2

    @pytest.mark.asyncio
    async def test_get_weak_areas_empty_when_no_poor_feedback(self, learning_hub):
        await learning_hub.process_feedback("int-ok", feedback_score=9)

        assert learning_hub.get_weak_areas() == []

    @pytest.mark.asyncio
    async def test_identify_skill_gap_existing_skill(self, learning_hub):
        mock_gap = GapAnalysis(
            gap_type="MISSING_SKILL",
            description="Cannot summarise docs",
            suggested_skill_name="summarize_document",
            suggested_skill_description="Summarise long docs",
        )
        learning_hub._llm.generate_structured = AsyncMock(return_value=mock_gap)

        gap = await learning_hub.identify_skill_gap("int-1")

        assert gap["skill_already_exists"] is True
        assert "existing_description" in gap

    @pytest.mark.asyncio
    async def test_identify_skill_gap_missing_interaction(self, learning_hub, mock_crm):
        mock_crm.get_interaction.return_value = None
        result = await learning_hub.identify_skill_gap("missing")
        assert "error" in result


# ═════════════════════════════════════════════════════════════════════════
# 8. Nemesis training cycle
# ═════════════════════════════════════════════════════════════════════════


class TestNemesisTraining:
    """Tests for the Nemesis agent's training cycle with mocked dependencies."""

    @pytest.fixture()
    def mock_settings_ctx(self):
        with patch("ira.config.get_settings", return_value=_make_settings_mock()) as m:
            yield m

    @pytest.fixture()
    def nemesis(self, mock_settings_ctx):
        with patch("ira.agents.base_agent.get_llm_client", return_value=_mock_llm_client()):
            from ira.agents.nemesis import Nemesis
            retriever = AsyncMock()
            retriever.search = AsyncMock(return_value=[])
            retriever.search_by_category = AsyncMock(return_value=[])
            bus = MagicMock()
            return Nemesis(retriever=retriever, bus=bus)

    @pytest.fixture()
    def mock_target_agent(self):
        agent = AsyncMock()
        agent.name = "prometheus"
        agent.handle = AsyncMock(return_value="Pipeline has 5 deals worth $2M total.")
        return agent

    @pytest.fixture()
    def mock_learning_hub(self):
        hub = MagicMock()
        hub.get_weak_areas = MagicMock(return_value=[])
        hub._crm = AsyncMock()
        interaction = MagicMock()
        interaction.id = str(uuid4())
        hub._crm.create_interaction = AsyncMock(return_value=interaction)
        hub.process_feedback = AsyncMock()
        return hub

    @pytest.mark.asyncio
    async def test_handle_unconfigured_falls_back_to_llm(self, nemesis):
        from ira.schemas.llm_outputs import ReActDecision

        nemesis._llm.generate_structured = AsyncMock(
            return_value=ReActDecision(
                thought="No training infrastructure configured.",
                final_answer="Training analysis...",
            ),
        )
        result = await nemesis.handle("Run training")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_handle_configured_runs_training_cycle(
        self, nemesis, mock_learning_hub, mock_target_agent,
    ):
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={"prometheus": mock_target_agent},
        )

        scores_json = json.dumps({
            "accuracy": 7, "completeness": 6, "clarity": 8, "actionability": 5,
            "overall": 7,
            "strengths": ["Good data"],
            "weaknesses": ["Missing next steps"],
            "improvement_suggestion": "Add action items",
        })

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=scores_json)
        result = await nemesis.handle("Run training", {"num_scenarios": 1})

        assert "Training Cycle Report" in result
        mock_target_agent.handle.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_training_scenario_scores_agent(
        self, nemesis, mock_learning_hub, mock_target_agent,
    ):
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={"prometheus": mock_target_agent},
        )

        scores_json = json.dumps({
            "accuracy": 8, "completeness": 7, "clarity": 9, "actionability": 6,
            "overall": 8,
            "strengths": ["Accurate"], "weaknesses": ["Verbose"],
            "improvement_suggestion": "Be concise",
        })

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=scores_json)
        result = await nemesis.create_training_scenario({
            "test_query": "Show me the sales pipeline",
            "domain": "sales",
            "difficulty": "medium",
        })

        assert result.target_agent == "prometheus"
        assert result.overall_score == 8
        assert result.agent_response == "Pipeline has 5 deals worth $2M total."
        assert len(result.ideal_response) > 0
        mock_learning_hub._crm.create_interaction.assert_awaited_once()
        mock_learning_hub.process_feedback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_training_scenario_logs_correction_for_low_score(
        self, nemesis, mock_learning_hub, mock_target_agent,
    ):
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={"prometheus": mock_target_agent},
        )

        scores_json = json.dumps({
            "accuracy": 2, "completeness": 3, "clarity": 4, "actionability": 1,
            "overall": 3,
            "strengths": [], "weaknesses": ["Everything"],
            "improvement_suggestion": "Start over",
        })

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=scores_json)
        result = await nemesis.create_training_scenario({
            "test_query": "Complex pricing question",
            "domain": "sales",
        })

        assert result.overall_score == 3
        feedback_call = mock_learning_hub.process_feedback.call_args
        assert feedback_call.kwargs["feedback_score"] == 3
        assert feedback_call.kwargs["correction"] is not None

    @pytest.mark.asyncio
    async def test_create_training_scenario_no_correction_for_high_score(
        self, nemesis, mock_learning_hub, mock_target_agent,
    ):
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={"prometheus": mock_target_agent},
        )

        scores_json = json.dumps({
            "accuracy": 9, "completeness": 8, "clarity": 9, "actionability": 8,
            "overall": 9,
            "strengths": ["Excellent"], "weaknesses": [],
            "improvement_suggestion": "None needed",
        })

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=scores_json)
        await nemesis.create_training_scenario({
            "test_query": "Simple question",
            "domain": "sales",
        })

        feedback_call = mock_learning_hub.process_feedback.call_args
        assert feedback_call.kwargs["correction"] is None

    @pytest.mark.asyncio
    async def test_scenario_with_missing_agent_returns_zero_score(
        self, nemesis, mock_learning_hub,
    ):
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={},
        )

        result = await nemesis.create_training_scenario({
            "test_query": "Test",
            "domain": "sales",
        })

        assert result.overall_score == 0
        assert "not available" in result.agent_response

    @pytest.mark.asyncio
    async def test_generate_scenarios_uses_weak_areas(
        self, nemesis, mock_learning_hub,
    ):
        mock_learning_hub.get_weak_areas.return_value = [
            {
                "interaction_id": "int-1",
                "score": 2,
                "gap_analysis": {"gap_type": "KNOWLEDGE_GAP", "description": "Missing specs"},
                "correction_analysis": {},
            },
        ]

        scenario_json = json.dumps({
            "test_query": "What are the PF1-C specs?",
            "domain": "production",
            "difficulty": "hard",
            "rationale": "Tests machine spec knowledge",
        })

        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={"hephaestus": AsyncMock()},
        )

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=scenario_json)
        scenarios = await nemesis._generate_scenarios(1)

        assert len(scenarios) == 1
        assert scenarios[0]["domain"] == "production"
        mock_learning_hub.get_weak_areas.assert_called_once_with(limit=1)

    @pytest.mark.asyncio
    async def test_generate_scenarios_fallback_when_no_weak_areas(
        self, nemesis, mock_learning_hub,
    ):
        mock_learning_hub.get_weak_areas.return_value = []
        nemesis.configure(
            learning_hub=mock_learning_hub,
            peer_agents={},
        )

        fallback_json = json.dumps([
            {"test_query": "Q1", "domain": "sales", "difficulty": "medium", "rationale": "r1"},
            {"test_query": "Q2", "domain": "pricing", "difficulty": "hard", "rationale": "r2"},
        ])

        nemesis._llm.generate_text_with_fallback = AsyncMock(return_value=fallback_json)
        scenarios = await nemesis._generate_scenarios(2)

        assert len(scenarios) == 2
        assert scenarios[0]["test_query"] == "Q1"

    def test_format_training_report_empty(self, nemesis, mock_settings_ctx):
        assert nemesis._format_training_report([]) == "No training scenarios were executed."

    def test_format_training_report_pass_warn_fail(self, nemesis, mock_settings_ctx):
        from ira.agents.nemesis import TrainingResult

        results = [
            TrainingResult(domain="sales", target_agent="prometheus", test_query="Q1", overall_score=8, scores={"strengths": [], "weaknesses": []}),
            TrainingResult(domain="pricing", target_agent="plutus", test_query="Q2", overall_score=5, scores={"strengths": [], "weaknesses": []}),
            TrainingResult(domain="hr", target_agent="themis", test_query="Q3", overall_score=2, scores={"strengths": [], "weaknesses": []}),
        ]
        report = nemesis._format_training_report(results)
        assert "[PASS]" in report
        assert "[WARN]" in report
        assert "[FAIL]" in report
        assert "5.0/10" in report


# ═════════════════════════════════════════════════════════════════════════
# 9. DreamMode — 5-stage cycle
# ═════════════════════════════════════════════════════════════════════════


class TestDreamModeFiveStages:
    """Tests for the 5-stage DreamMode cycle with CRM and ProceduralMemory."""

    @pytest.fixture()
    async def dream(self, tmp_path):
        from ira.memory.dream_mode import DreamMode

        db = str(tmp_path / "dream_test.db")
        log_path = tmp_path / "dream_log.json"

        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=[])

        mock_conv = AsyncMock()
        mock_conv._db = None
        mock_conv.get_history = AsyncMock(return_value=[])

        mock_episodic = AsyncMock()
        mock_episodic.consolidate_episode = AsyncMock(return_value={
            "id": 1,
            "user_id": "contact-1",
            "narrative": "Customer asked about PF1-C pricing.",
            "key_topics": ["PF1-C", "pricing"],
            "decisions_made": [],
            "commitments": [],
            "emotional_tone": "neutral",
            "relationship_impact": "maintained",
        })

        mock_crm = AsyncMock()
        mock_procedural = AsyncMock()
        mock_procedural.learn_procedure = AsyncMock(return_value=MagicMock(
            id=1, trigger_pattern="pricing inquiry", steps=["look up price"], success_rate=1.0,
        ))

        with (
            patch("ira.memory.dream_mode.get_settings", return_value=_make_settings_mock()),
            patch("ira.memory.dream_mode.get_llm_client", return_value=_mock_llm_client()),
        ):
            dm = DreamMode(
                long_term=mock_ltm,
                episodic=mock_episodic,
                conversation=mock_conv,
                crm=mock_crm,
                procedural_memory=mock_procedural,
                db_path=db,
                dream_log_path=log_path,
            )
        await dm.initialize()
        yield dm, mock_crm, mock_procedural, mock_episodic, log_path
        await dm.close()

    @pytest.mark.asyncio
    async def test_stage1_pulls_crm_interactions(self, dream):
        dm, mock_crm, _, _, _ = dream

        now = datetime.now(timezone.utc)
        mock_crm.list_interactions = AsyncMock(return_value=[
            MagicMock(to_dict=lambda: {
                "contact_id": "c1", "direction": "OUTBOUND",
                "subject": "Intro email", "content": "Hello!",
                "created_at": now.isoformat(),
            }),
        ])

        stage_log: dict = {"stages": {}}
        interactions = await dm._stage1_memory_ingestion(stage_log)

        assert len(interactions) == 1
        assert stage_log["stages"]["1_memory_ingestion"]["status"] == "ok"
        mock_crm.list_interactions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stage1_skips_when_no_crm(self, tmp_path):
        from ira.memory.dream_mode import DreamMode

        db = str(tmp_path / "no_crm.db")
        with (
            patch("ira.memory.dream_mode.get_settings", return_value=_make_settings_mock()),
            patch("ira.memory.dream_mode.get_llm_client", return_value=_mock_llm_client()),
        ):
            dm = DreamMode(
                long_term=AsyncMock(),
                episodic=AsyncMock(),
                conversation=AsyncMock(),
                crm=None,
                db_path=db,
            )
        await dm.initialize()

        stage_log: dict = {"stages": {}}
        interactions = await dm._stage1_memory_ingestion(stage_log)

        assert interactions == []
        assert stage_log["stages"]["1_memory_ingestion"]["interactions_found"] == 0
        await dm.close()

    @pytest.mark.asyncio
    async def test_stage2_consolidates_crm_interactions(self, dream):
        dm, _, _, mock_episodic, _ = dream

        interactions = [
            {"contact_id": "c1", "direction": "OUTBOUND", "subject": "Hi", "content": "Hello"},
            {"contact_id": "c1", "direction": "INBOUND", "subject": "Re: Hi", "content": "Thanks"},
            {"contact_id": "c2", "direction": "OUTBOUND", "subject": "Intro", "content": "Hey"},
        ]

        stage_log: dict = {"stages": {}}
        episodes, consolidated = await dm._stage2_episodic_consolidation(interactions, stage_log)

        assert consolidated >= 2  # one episode per contact group
        assert mock_episodic.consolidate_episode.await_count >= 2
        assert stage_log["stages"]["2_episodic_consolidation"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_stage3_generates_insights(self, dream):
        dm, _, _, _, _ = dream

        episodes = [
            {"user_id": "c1", "narrative": "Customer asked about PF1-C pricing."},
            {"user_id": "c2", "narrative": "Customer complained about delivery delays."},
        ]

        mock_insight = DreamInsight(
            patterns=["Pricing inquiries increasing"],
            contradictions=[],
            insights=["Market shift toward PF1-C"],
            recommendations=["Create PF1-C pricing FAQ"],
        )
        dm._llm.generate_structured = AsyncMock(return_value=mock_insight)

        stage_log: dict = {"stages": {}}
        insights, gaps, connections, campaign_insights = await dm._stage3_insight_generation(
            episodes, stage_log
        )

        assert len(insights.get("patterns", [])) == 1
        assert len(insights.get("recommendations", [])) == 1
        assert stage_log["stages"]["3a_cross_episode_insights"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_stage4_creates_procedures_from_insights(self, dream):
        dm, _, mock_procedural, _, _ = dream

        insights = {
            "recommendations": [
                {"action": "Auto-reply to pricing inquiries", "priority": "HIGH", "rationale": "Save time"},
            ],
        }
        episodes = [{"user_id": "c1", "narrative": "Pricing inquiry handled well."}]

        mock_procedures = DreamProcedures(procedures=[
            DreamProcedure(
                trigger="pricing inquiry received",
                steps=["look up price", "draft reply"],
                expected_outcome="fast response",
                confidence="HIGH",
            ),
        ])
        dm._llm.generate_structured = AsyncMock(return_value=mock_procedures)

        stage_log: dict = {"stages": {}}
        await dm._stage4_procedural_learning(insights, episodes, stage_log)

        mock_procedural.learn_procedure.assert_awaited_once()
        assert stage_log["stages"]["4_procedural_learning"]["procedures_created"] == 1

    @pytest.mark.asyncio
    async def test_stage4_skips_without_procedural_memory(self, tmp_path):
        from ira.memory.dream_mode import DreamMode

        db = str(tmp_path / "no_proc.db")
        with (
            patch("ira.memory.dream_mode.get_settings", return_value=_make_settings_mock()),
            patch("ira.memory.dream_mode.get_llm_client", return_value=_mock_llm_client()),
        ):
            dm = DreamMode(
                long_term=AsyncMock(),
                episodic=AsyncMock(),
                conversation=AsyncMock(),
                procedural_memory=None,
                db_path=db,
            )
        await dm.initialize()

        stage_log: dict = {"stages": {}}
        await dm._stage4_procedural_learning({}, [], stage_log)

        assert stage_log["stages"]["4_procedural_learning"]["status"] == "skipped"
        await dm.close()

    @pytest.mark.asyncio
    async def test_stage5_prunes_old_episodes(self, dream):
        dm, _, _, _, _ = dream

        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        assert dm._db is not None
        await dm._db.execute(
            """CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, narrative TEXT, key_topics TEXT,
                decisions TEXT, commitments TEXT, emotional_tone TEXT,
                relationship_impact TEXT, created_at TEXT
            )"""
        )
        for i in range(5):
            await dm._db.execute(
                "INSERT INTO episodes (user_id, narrative, key_topics, decisions, commitments, emotional_tone, relationship_impact, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"u{i}", f"Old episode {i}", "[]", "[]", "[]", "neutral", "maintained", old_date),
            )
        await dm._db.commit()

        from ira.schemas.llm_outputs import DreamPruneSummary

        mock_prune = DreamPrune(
            keep=["1"],
            summarise=[DreamPruneSummary(ids=["2", "3"], summary="Merged episodes 2 and 3")],
            archive=["4", "5"],
        )
        dm._llm.generate_structured = AsyncMock(return_value=mock_prune)

        stage_log: dict = {"stages": {}}
        await dm._stage5_memory_pruning(stage_log)

        assert stage_log["stages"]["5_memory_pruning"]["archived"] == 2
        assert stage_log["stages"]["5_memory_pruning"]["summarised"] == 2

        cursor = await dm._db.execute("SELECT count(*) FROM episodes")
        row = await cursor.fetchone()
        assert row[0] == 3  # 5 - 2 archived = 3 remaining

    @pytest.mark.asyncio
    async def test_full_cycle_produces_report_and_log(self, dream):
        dm, mock_crm, mock_procedural, _, log_path = dream

        now = datetime.now(timezone.utc)
        mock_crm.list_interactions = AsyncMock(return_value=[
            MagicMock(to_dict=lambda: {
                "contact_id": "c1", "direction": "OUTBOUND",
                "subject": "Hello", "content": "Hi there",
                "created_at": now.isoformat(),
            }),
        ])

        _model_responses = {
            DreamInsight: DreamInsight(),
            DreamGaps: DreamGaps(),
            DreamCreative: DreamCreative(),
            DreamCampaignInsights: DreamCampaignInsights(),
            DreamProcedures: DreamProcedures(),
            DreamPrune: DreamPrune(),
        }

        async def mock_generate_structured(system, user, model_cls, **kwargs):
            return _model_responses.get(model_cls, model_cls())

        dm._llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)

        report = await dm.run_dream_cycle()

        assert report.memories_consolidated >= 1
        assert isinstance(report.gaps_identified, list)
        assert isinstance(report.creative_connections, list)
        assert isinstance(report.campaign_insights, list)

        assert log_path.exists()
        log_data = json.loads(log_path.read_text())
        assert isinstance(log_data, list)
        assert len(log_data) == 1
        assert "stages" in log_data[0]

    @pytest.mark.asyncio
    async def test_cycle_resilient_to_stage_failures(self, dream):
        dm, mock_crm, _, mock_episodic, _ = dream

        mock_crm.list_interactions = AsyncMock(side_effect=RuntimeError("CRM down"))
        mock_episodic.consolidate_episode = AsyncMock(side_effect=RuntimeError("boom"))

        _model_responses = {
            DreamInsight: DreamInsight(),
            DreamGaps: DreamGaps(),
            DreamCreative: DreamCreative(),
            DreamCampaignInsights: DreamCampaignInsights(),
            DreamProcedures: DreamProcedures(),
            DreamPrune: DreamPrune(),
        }

        async def mock_generate_structured(system, user, model_cls, **kwargs):
            return _model_responses.get(model_cls, model_cls())

        dm._llm.generate_structured = AsyncMock(side_effect=mock_generate_structured)

        report = await dm.run_dream_cycle()

        assert report is not None
        assert report.memories_consolidated == 0
