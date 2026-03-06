"""Tests for the ira.systems package.

Covers DigestiveSystem, RespiratorySystem, ImmuneSystem, EndocrineSystem,
SensorySystem, and VoiceSystem.  All external services are mocked so the
suite runs fully offline.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.data.models import Channel, Contact, Direction, Email


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

        with patch("ira.systems.digestive.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.digestive import DigestiveSystem
            ds = DigestiveSystem(mock_ingestor, mock_graph, mock_embeddings, mock_qdrant)

        ds._graph = mock_graph
        ds._qdrant = mock_qdrant
        return ds

    @pytest.mark.asyncio
    async def test_ingest_separates_nutrients(self, digestive_system):
        nutrients_json = json.dumps({
            "protein": ["Revenue was $5M in Q3", "Deal closes March 15"],
            "carbs": ["The company is based in Dubai"],
            "waste": ["Best regards", "Sent from my iPhone"],
        })

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(nutrients_json)):
            result = await digestive_system.ingest("Some email body", "test@example.com", "email")

        assert result["nutrients_extracted"]["protein"] == 2
        assert result["nutrients_extracted"]["carbs"] == 1
        assert result["nutrients_extracted"]["waste"] == 2

    @pytest.mark.asyncio
    async def test_ingest_stores_only_protein_and_carbs(self, digestive_system):
        nutrients_json = json.dumps({
            "protein": ["Important fact"],
            "carbs": ["Some context"],
            "waste": ["Signature block"],
        })

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(nutrients_json)):
            await digestive_system.ingest("Body text", "src", "cat")

        digestive_system._qdrant.upsert_items.assert_called_once()
        items = digestive_system._qdrant.upsert_items.call_args[0][0]
        contents = [item.content for item in items]
        assert any("Important fact" in c for c in contents)
        assert any("Some context" in c for c in contents)
        assert not any("Signature block" in c for c in contents)

    @pytest.mark.asyncio
    async def test_ingest_extracts_entities_from_protein(self, digestive_system):
        nutrients_json = json.dumps({
            "protein": ["Acme Corp ordered a PF1-C"],
            "carbs": [],
            "waste": [],
        })

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(nutrients_json)):
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

        nutrients_json = json.dumps({"protein": ["pricing for PF1-C"], "carbs": [], "waste": []})
        meta_json = json.dumps({
            "sender_info": {"name": "Alice", "company": "Acme Corp"},
            "company_mentions": ["Acme Corp"],
            "machine_mentions": ["PF1-C"],
            "pricing_mentions": ["$500K"],
            "dates_deadlines": ["March 30"],
        })

        call_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_openai_response(nutrients_json)
            return _mock_openai_response(meta_json)

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
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
        mock_digestive = MagicMock()
        mock_ingestor = MagicMock()
        mock_ingestor.ingest_all = AsyncMock(return_value={"total_files": 0, "total_chunks": 0})

        with patch("ira.systems.respiratory.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.respiratory import RespiratorySystem
            rs = RespiratorySystem(
                mock_digestive,
                mock_ingestor,
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
        levels = endocrine.get_levels()
        assert levels["confidence"] == pytest.approx(0.5)
        assert levels["energy"] == pytest.approx(0.7)
        assert levels["growth_signal"] == pytest.approx(0.3)
        assert levels["stress"] == pytest.approx(0.2)

    def test_boost_increases_level(self, endocrine):
        endocrine.boost("confidence", 0.2)
        assert endocrine.get_levels()["confidence"] == pytest.approx(0.7)

    def test_boost_caps_at_one(self, endocrine):
        endocrine.boost("confidence", 0.9)
        assert endocrine.get_levels()["confidence"] == pytest.approx(1.0)

    def test_reduce_floors_at_zero(self, endocrine):
        endocrine.reduce("stress", 0.5)
        assert endocrine.get_levels()["stress"] == pytest.approx(0.0)

    def test_decay_moves_toward_baseline(self, endocrine):
        endocrine.boost("confidence", 0.5)  # -> 1.0
        assert endocrine.get_levels()["confidence"] == pytest.approx(1.0)

        endocrine.decay_all(factor=0.5)
        # Moves 50% toward baseline (0.5): 1.0 + (0.5 - 1.0) * 0.5 = 0.75
        assert endocrine.get_levels()["confidence"] == pytest.approx(0.75)

        endocrine.decay_all(factor=0.5)
        # 0.75 + (0.5 - 0.75) * 0.5 = 0.625
        assert endocrine.get_levels()["confidence"] == pytest.approx(0.625)

    def test_behavioral_modifiers_high_confidence(self, endocrine):
        endocrine.boost("confidence", 0.3)  # -> 0.8
        endocrine.reduce("stress", 0.1)     # -> 0.1
        mods = endocrine.get_behavioral_modifiers()
        assert mods["response_style"] == "assertive"
        assert mods["verbosity"] == "concise"

    def test_behavioral_modifiers_low_confidence_high_stress(self, endocrine):
        endocrine.reduce("confidence", 0.3)  # -> 0.2
        endocrine.boost("stress", 0.6)       # -> 0.8
        mods = endocrine.get_behavioral_modifiers()
        assert mods["response_style"] == "cautious"
        assert mods["verbosity"] == "detailed"

    def test_boost_invalid_hormone_raises(self, endocrine):
        with pytest.raises(ValueError, match="Unknown hormone"):
            endocrine.boost("invalid_name", 0.1)


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
        with patch("ira.systems.voice.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(long_response)):
            result = await voice_system.shape_response(long_response, "TELEGRAM", None, {})

        assert len(result) <= 2003  # 2000 + "..."

    @pytest.mark.asyncio
    async def test_shape_response_applies_behavioral_modifiers(self, voice_system):
        modifiers = {"prompt_addendum": "Be cautious.", "verbosity": "detailed"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response("shaped")) as mock_post:
            await voice_system.shape_response(
                "Some long response that needs reshaping " * 20,
                "TELEGRAM", None, modifiers,
            )

        call_payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        system_msg = call_payload["messages"][0]["content"]
        assert "Be cautious." in system_msg

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
        with patch("ira.systems.learning_hub.get_settings") as mock_settings:
            mock_settings.return_value = _make_settings_mock()
            from ira.systems.learning_hub import LearningHub
            return LearningHub(crm=mock_crm, procedural_memory=mock_procedural)

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
        gap_json = json.dumps({
            "gap_type": "KNOWLEDGE_GAP",
            "description": "Missing lead-time data",
            "suggested_skill_name": None,
            "suggested_skill_description": None,
            "suggested_knowledge_source": "production database",
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(gap_json)):
            record = await learning_hub.process_feedback("int-2", feedback_score=2)

        assert record.gap_analysis.get("gap_type") == "KNOWLEDGE_GAP"
        mock_procedural.record_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_feedback_with_correction(self, learning_hub, mock_crm):
        correction_json = json.dumps({
            "error_category": "FACTUAL",
            "what_was_wrong": "Wrong lead time",
            "correct_behaviour": "Should say 8 weeks not 6",
        })
        gap_json = json.dumps({
            "gap_type": "QUALITY_ISSUE",
            "description": "Incorrect fact",
            "suggested_skill_name": None,
            "suggested_skill_description": None,
            "suggested_knowledge_source": None,
        })

        call_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_openai_response(correction_json)
            return _mock_openai_response(gap_json)

        with patch("httpx.AsyncClient.post", side_effect=mock_post):
            record = await learning_hub.process_feedback(
                "int-3", feedback_score=2, correction="The lead time is 8 weeks.",
            )

        assert record.correction == "The lead time is 8 weeks."
        assert record.correction_analysis.get("error_category") == "FACTUAL"

    @pytest.mark.asyncio
    async def test_suggest_procedure_from_interaction(self, learning_hub, mock_procedural):
        steps_json = json.dumps(["Step 1: Look up machine", "Step 2: Check inventory"])

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(steps_json)):
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
        gap_json = json.dumps({"gap_type": "MISSING_SKILL", "description": "test"})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(gap_json)):
            await learning_hub.process_feedback("int-a", feedback_score=1)
            await learning_hub.process_feedback("int-b", feedback_score=8)
            await learning_hub.process_feedback("int-c", feedback_score=2)

        weak = learning_hub.get_weak_areas(limit=5)
        assert len(weak) == 2
        assert weak[0]["score"] == 1
        assert weak[1]["score"] == 2

    @pytest.mark.asyncio
    async def test_get_weak_areas_empty_when_no_poor_feedback(self, learning_hub):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response("{}")):
            await learning_hub.process_feedback("int-ok", feedback_score=9)

        assert learning_hub.get_weak_areas() == []

    @pytest.mark.asyncio
    async def test_identify_skill_gap_existing_skill(self, learning_hub):
        gap_json = json.dumps({
            "gap_type": "MISSING_SKILL",
            "description": "Cannot summarise docs",
            "suggested_skill_name": "summarize_document",
            "suggested_skill_description": "Summarise long docs",
            "suggested_knowledge_source": None,
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(gap_json)):
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
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response("Training analysis...")):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(scores_json)):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(scores_json)):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(scores_json)):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(scores_json)):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(scenario_json)):
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

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=_mock_openai_response(fallback_json)):
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
