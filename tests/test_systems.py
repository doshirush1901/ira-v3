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

from ira.data.models import Contact, Email


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
