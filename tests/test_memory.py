"""Tests for the ira.memory package.

Covers ConversationMemory, LongTermMemory, EpisodicMemory,
Metacognition, EmotionalIntelligence, InnerVoice, RelationshipMemory,
DreamMode, and GoalManager.

External services (OpenAI, Mem0) are mocked so the suite runs fully offline.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.data.models import (
    Channel,
    Direction,
    EmotionalState,
    Interaction,
    KnowledgeState,
    WarmthLevel,
)
from ira.schemas.llm_outputs import (
    ConversationEntities,
    DreamCreative,
    DreamGaps,
    EmotionDetection,
    EpisodeConsolidation,
    InnerReflection,
    KnowledgeAssessment,
    MemorableMoments,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _mock_settings():
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-openai-key"
    s.llm.openai_model = "gpt-4.1"
    s.memory.api_key.get_secret_value.return_value = "test-mem0-key"
    return s


def _mock_llm_client():
    client = MagicMock()
    client.generate_structured = AsyncMock()
    client.generate_text = AsyncMock(return_value="")
    client.generate_text_with_fallback = AsyncMock(return_value="")
    client.generate_structured_with_fallback = AsyncMock()
    return client


def _make_interaction(**overrides) -> Interaction:
    defaults = dict(
        contact_id=uuid4(),
        channel=Channel.EMAIL,
        direction=Direction.INBOUND,
        summary="Test interaction",
        content=None,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Interaction(**defaults)


# ═════════════════════════════════════════════════════════════════════════════
# 1. ConversationMemory
# ═════════════════════════════════════════════════════════════════════════════


class TestConversationMemory:

    @pytest.fixture()
    async def memory(self, tmp_path):
        from ira.memory.conversation import ConversationMemory

        db = str(tmp_path / "test.db")
        with patch("ira.memory.conversation.get_llm_client", return_value=_mock_llm_client()):
            mem = ConversationMemory(db_path=db)
        await mem.initialize()
        yield mem
        await mem.close()

    @pytest.mark.asyncio
    async def test_add_message_and_get_history(self, memory):
        await memory.add_message("user1", "cli", "user", "Hello")
        await memory.add_message("user1", "cli", "assistant", "Hi there")
        await memory.add_message("user1", "cli", "user", "How are you?")

        history = await memory.get_history("user1", "cli", limit=20)

        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"
        assert history[2]["content"] == "How are you?"

    @pytest.mark.asyncio
    async def test_new_conversation_after_timeout(self, memory):
        await memory.add_message("user1", "cli", "user", "First message")

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
        await memory._db.execute(
            "UPDATE conversations SET last_message_at = ? WHERE user_id = ?",
            (old_time, "user1"),
        )
        await memory._db.commit()

        result = await memory.should_start_new_conversation("user1", "cli")
        assert result is True

    @pytest.mark.asyncio
    async def test_same_conversation_within_timeout(self, memory):
        await memory.add_message("user1", "cli", "user", "Msg 1")
        await memory.add_message("user1", "cli", "user", "Msg 2")

        cursor = await memory._db.execute(
            "SELECT DISTINCT conversation_id FROM messages"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_extract_entities_mocks_llm(self, memory):
        memory._llm.generate_structured = AsyncMock(
            return_value=ConversationEntities(
                people=["John"],
                companies=["Acme"],
                machines=["PF1-C"],
            )
        )

        result = await memory.extract_entities(
            "Send a quote to John at Acme for the PF1-C"
        )

        assert "John" in result["people"]
        assert "Acme" in result["companies"]
        assert "PF1-C" in result["machines"]


# ═════════════════════════════════════════════════════════════════════════════
# 2. LongTermMemory
# ═════════════════════════════════════════════════════════════════════════════


class TestLongTermMemory:

    @pytest.fixture()
    def ltm(self):
        from ira.memory.long_term import LongTermMemory

        with patch("ira.memory.long_term.get_settings", return_value=_mock_settings()):
            return LongTermMemory()

    @pytest.mark.asyncio
    async def test_store_calls_mem0_api(self, ltm):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "mem_1", "event": "ADD", "data": {"memory": "test"}}]
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            result = await ltm.store("test fact", user_id="user1")

        assert len(result) >= 1
        mock_post.assert_awaited_once()
        call_kwargs = mock_post.call_args
        assert "/v1/memories/" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_search_returns_normalized_results(self, ltm):
        now = datetime.now(timezone.utc).isoformat()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"id": "m1", "memory": "fact one", "score": 0.9, "metadata": {}, "created_at": now},
                {"id": "m2", "memory": "fact two", "score": 0.7, "metadata": {}, "created_at": now},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            results = await ltm.search("test query")

        assert len(results) == 2
        assert all("memory" in r for r in results)
        assert all("score" in r for r in results)

    @pytest.mark.asyncio
    async def test_store_without_api_key(self):
        from ira.memory.long_term import LongTermMemory

        mock_s = _mock_settings()
        mock_s.memory.api_key.get_secret_value.return_value = ""
        with patch("ira.memory.long_term.get_settings", return_value=mock_s):
            ltm = LongTermMemory()

        result = await ltm.store("test")
        assert result == []

    def test_apply_decay_values(self, ltm):
        fresh = ltm.apply_decay(days_old=0)
        assert fresh == pytest.approx(1.0, abs=0.01)

        old = ltm.apply_decay(days_old=30)
        assert old < 0.5

        old_accessed = ltm.apply_decay(days_old=30, access_count=10)
        old_not_accessed = ltm.apply_decay(days_old=30, access_count=0)
        assert old_accessed > old_not_accessed


# ═════════════════════════════════════════════════════════════════════════════
# 3. EpisodicMemory
# ═════════════════════════════════════════════════════════════════════════════


class TestEpisodicMemory:

    @pytest.fixture()
    async def episodic(self, tmp_path):
        from ira.memory.episodic import EpisodicMemory

        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=[])
        mock_ltm.search = AsyncMock(return_value=[])

        db = str(tmp_path / "test.db")
        with patch("ira.memory.episodic.get_llm_client", return_value=_mock_llm_client()):
            ep = EpisodicMemory(long_term=mock_ltm, db_path=db)
        await ep.initialize()
        yield ep
        await ep.close()

    @pytest.mark.asyncio
    async def test_consolidate_episode(self, episodic):
        conversation = [
            {"role": "user", "content": "I need a quote for PF1-C", "timestamp": "2026-03-06T10:00:00"},
            {"role": "assistant", "content": "Sure, let me prepare that.", "timestamp": "2026-03-06T10:01:00"},
        ]
        episodic._llm.generate_structured = AsyncMock(
            return_value=EpisodeConsolidation(
                narrative="Customer requested a PF1-C quote.",
                key_topics=["PF1-C", "quote"],
                decisions_made=["prepare quote"],
                commitments=["send quote by EOD"],
                emotional_tone="positive",
                relationship_impact="strengthened",
            )
        )

        result = await episodic.consolidate_episode(conversation, "user1")

        assert "narrative" in result
        assert result["narrative"] == "Customer requested a PF1-C quote."
        assert "key_topics" in result
        assert "id" in result
        episodic._long_term.store.assert_awaited()

    @pytest.mark.asyncio
    async def test_consolidate_episode_handles_bad_llm(self, episodic):
        conversation = [
            {"role": "user", "content": "Hello", "timestamp": "2026-03-06T10:00:00"},
            {"role": "assistant", "content": "Hi", "timestamp": "2026-03-06T10:01:00"},
        ]

        episodic._llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM call failed"))
        result = await episodic.consolidate_episode(conversation, "user1")

        assert "failed" in result["narrative"].lower() or "consolidation" in result["narrative"].lower()

    @pytest.mark.asyncio
    async def test_weave_episodes(self, episodic):
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            await episodic._db.execute(
                """INSERT INTO episodes
                (user_id, narrative, key_topics, decisions, commitments, emotional_tone, relationship_impact, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("user1", f"Episode {i}", "[]", "[]", "[]", "neutral", "maintained", now),
            )
        await episodic._db.commit()

        episodic._llm.generate_text = AsyncMock(
            return_value="The relationship started with Episode 0 and progressed.",
        )
        result = await episodic.weave_episodes("user1")

        assert "Episode" in result or "relationship" in result.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 4. Metacognition
# ═════════════════════════════════════════════════════════════════════════════


class TestMetacognition:

    @pytest.fixture()
    async def meta(self, tmp_path):
        from ira.memory.metacognition import Metacognition

        db = str(tmp_path / "test.db")
        with patch("ira.memory.metacognition.get_llm_client", return_value=_mock_llm_client()):
            m = Metacognition(db_path=db)
        await m.initialize()
        yield m
        await m.close()

    @pytest.mark.asyncio
    async def test_assess_high_confidence(self, meta):
        context = [
            {"content": "PF1-C specs: ...", "score": 0.9, "source": "manual.pdf", "source_type": "qdrant", "metadata": {}},
            {"content": "PF1-C lead time: 16-20 weeks", "score": 0.85, "source": "specs.pdf", "source_type": "qdrant", "metadata": {}},
        ]
        meta._llm.generate_structured = AsyncMock(
            return_value=KnowledgeAssessment(
                state="KNOW_VERIFIED",
                confidence=0.9,
                conflicts=[],
                gaps=[],
            )
        )

        result = await meta.assess_knowledge("PF1-C specs?", context)

        assert result["state"] == KnowledgeState.KNOW_VERIFIED
        assert result["confidence"] >= 0.8

    @pytest.mark.asyncio
    async def test_assess_no_results_returns_unknown(self, meta):
        meta._llm.generate_structured = AsyncMock()
        result = await meta.assess_knowledge("unknown topic", [])

        assert result["state"] == KnowledgeState.UNKNOWN
        assert result["confidence"] == 0.0
        meta._llm.generate_structured.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_assess_conflicting(self, meta):
        context = [
            {"content": "Price is $100k", "score": 0.8, "source": "a.pdf", "source_type": "qdrant", "metadata": {}},
            {"content": "Price is $200k", "score": 0.75, "source": "b.pdf", "source_type": "qdrant", "metadata": {}},
        ]
        meta._llm.generate_structured = AsyncMock(
            return_value=KnowledgeAssessment(
                state="CONFLICTING",
                confidence=0.5,
                conflicts=["Source A says $100k, Source B says $200k"],
                gaps=[],
            )
        )

        result = await meta.assess_knowledge("PF1-C price?", context)

        assert result["state"] == KnowledgeState.CONFLICTING
        assert len(result["conflicts"]) >= 1

    def test_generate_confidence_prefix(self, meta):
        for state in KnowledgeState:
            prefix = meta.generate_confidence_prefix(state, 0.9)
            assert isinstance(prefix, str)
            assert len(prefix) > 0

        unknown_prefix = meta.generate_confidence_prefix(KnowledgeState.UNKNOWN, 0.0)
        assert "don't have reliable" in unknown_prefix

        verified_prefix = meta.generate_confidence_prefix(KnowledgeState.KNOW_VERIFIED, 0.9)
        assert "verified" in verified_prefix.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 5. EmotionalIntelligence
# ═════════════════════════════════════════════════════════════════════════════


class TestEmotionalIntelligence:

    @pytest.fixture()
    async def ei(self, tmp_path):
        from ira.memory.emotional_intelligence import EmotionalIntelligence

        db = str(tmp_path / "test.db")
        with patch("ira.memory.emotional_intelligence.get_llm_client", return_value=_mock_llm_client()):
            e = EmotionalIntelligence(db_path=db)
        await e.initialize()
        yield e
        await e.close()

    @pytest.mark.asyncio
    async def test_detect_urgent(self, ei):
        result = await ei.detect_emotion("This is URGENT! We need this ASAP immediately!")
        assert result["state"] == EmotionalState.URGENT

    @pytest.mark.asyncio
    async def test_detect_frustrated(self, ei):
        result = await ei.detect_emotion(
            "This is ridiculous, still not working after three attempts!"
        )
        assert result["state"] == EmotionalState.FRUSTRATED

    @pytest.mark.asyncio
    async def test_detect_grateful(self, ei):
        result = await ei.detect_emotion(
            "Thank you so much, really appreciate your help!"
        )
        assert result["state"] == EmotionalState.GRATEFUL

    @pytest.mark.asyncio
    async def test_detect_neutral_falls_through_to_llm(self, ei):
        ei._llm.generate_structured = AsyncMock(
            return_value=EmotionDetection(
                state="NEUTRAL",
                intensity="MILD",
                indicators=[],
            )
        )

        result = await ei.detect_emotion("Please send me the catalog.")

        ei._llm.generate_structured.assert_awaited_once()
        assert result["state"] == EmotionalState.NEUTRAL

    def test_get_response_adjustment(self, ei):
        adj = ei.get_response_adjustment(EmotionalState.FRUSTRATED, "STRONG")
        assert adj["tone"] == "empathetic"
        assert adj["priority_boost"] is True

        adj_neutral = ei.get_response_adjustment(EmotionalState.NEUTRAL, "MILD")
        assert adj_neutral["priority_boost"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 6. InnerVoice
# ═════════════════════════════════════════════════════════════════════════════


class TestInnerVoice:

    @pytest.fixture()
    async def voice(self, tmp_path):
        from ira.memory.inner_voice import InnerVoice

        db = str(tmp_path / "test.db")
        with patch("ira.memory.inner_voice.get_llm_client", return_value=_mock_llm_client()):
            v = InnerVoice(db_path=db, surface_probability=0.0)
        await v.initialize()
        yield v
        await v.close()

    @pytest.mark.asyncio
    async def test_initialize_seeds_default_traits(self, voice):
        traits = voice.get_all_traits()
        assert len(traits) == 6
        assert traits["warmth"].value == pytest.approx(0.7)
        assert traits["curiosity"].value == pytest.approx(0.8)
        assert traits["humor"].value == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_reflect_returns_structure(self, voice):
        voice._llm.generate_structured = AsyncMock(
            return_value=InnerReflection(
                reflection_type="OBSERVATION",
                content="Interesting request pattern.",
                should_surface=False,
            )
        )

        result = await voice.reflect("customer asked about PF1-C", "new inquiry")

        assert "reflection_type" in result
        assert "content" in result
        assert "should_surface" in result

    @pytest.mark.asyncio
    async def test_update_trait_clamps(self, voice):
        await voice.update_trait("warmth", +0.5, "test increase")
        assert voice.get_trait("warmth").value == pytest.approx(1.0)

        await voice.update_trait("warmth", -2.0, "test decrease")
        assert voice.get_trait("warmth").value == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_get_personality_summary(self, voice):
        summary = voice.get_personality_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "curiosity" in summary.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 7. RelationshipMemory
# ═════════════════════════════════════════════════════════════════════════════


class TestRelationshipMemory:

    @pytest.fixture()
    async def rel_mem(self, tmp_path):
        from ira.memory.relationship import RelationshipMemory

        db = str(tmp_path / "test.db")
        with patch("ira.memory.relationship.get_llm_client", return_value=_mock_llm_client()):
            rm = RelationshipMemory(db_path=db)
        await rm.initialize()
        yield rm
        await rm.close()

    @pytest.mark.asyncio
    async def test_new_contact_is_stranger(self, rel_mem):
        rel = await rel_mem.get_relationship("new_contact")
        assert rel.warmth_level == WarmthLevel.STRANGER
        assert rel.interaction_count == 0

    @pytest.mark.asyncio
    async def test_warmth_progression_stranger_to_acquaintance(self, rel_mem):
        rel_mem._llm.generate_structured = AsyncMock(
            return_value=MemorableMoments(moments=[])
        )
        for _ in range(3):
            interaction = _make_interaction()
            rel = await rel_mem.update_relationship("contact1", interaction)

        assert rel.warmth_level == WarmthLevel.ACQUAINTANCE
        assert rel.interaction_count == 3

    @pytest.mark.asyncio
    async def test_warmth_does_not_skip_levels(self, rel_mem):
        rel_mem._llm.generate_structured = AsyncMock(
            return_value=MemorableMoments(moments=[])
        )
        for _ in range(3):
            interaction = _make_interaction()
            rel = await rel_mem.update_relationship("contact2", interaction)

        assert rel.warmth_level == WarmthLevel.ACQUAINTANCE
        assert rel.warmth_level != WarmthLevel.FAMILIAR

    @pytest.mark.asyncio
    async def test_get_greeting_style(self, rel_mem):
        from ira.memory.relationship import Relationship

        stranger = Relationship(contact_id="s")
        trusted = Relationship(contact_id="t", warmth_level=WarmthLevel.TRUSTED)

        greeting_s = rel_mem.get_greeting_style(stranger)
        greeting_t = rel_mem.get_greeting_style(trusted)

        assert greeting_s != greeting_t
        assert "Machinecraft" in greeting_s


# ═════════════════════════════════════════════════════════════════════════════
# 8. DreamMode
# ═════════════════════════════════════════════════════════════════════════════


class TestDreamMode:

    @pytest.fixture()
    async def dream(self, tmp_path):
        from ira.memory.dream_mode import DreamMode

        db = str(tmp_path / "test.db")

        mock_ltm = AsyncMock()
        mock_ltm.store = AsyncMock(return_value=[])

        mock_conv = AsyncMock()
        mock_conv._db_path = db
        mock_conv._db = None
        mock_conv.get_history = AsyncMock(return_value=[
            {"role": "user", "content": "Hello", "timestamp": "2026-03-06T10:00:00"},
            {"role": "assistant", "content": "Hi there", "timestamp": "2026-03-06T10:01:00"},
        ])

        mock_episodic = AsyncMock()
        mock_episodic.consolidate_episode = AsyncMock(return_value={
            "id": 1,
            "narrative": "Test episode",
            "key_topics": [],
        })

        with patch("ira.memory.dream_mode.get_llm_client", return_value=_mock_llm_client()):
            dm = DreamMode(
                long_term=mock_ltm,
                episodic=mock_episodic,
                conversation=mock_conv,
                musculoskeletal=None,
                retriever=None,
                db_path=db,
            )
        await dm.initialize()

        import aiosqlite
        dm._conversation._db = await aiosqlite.connect(db)
        await dm._conversation._db.execute("PRAGMA journal_mode=WAL")
        await dm._conversation._db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL
            )
        """)
        await dm._conversation._db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                state TEXT NOT NULL,
                gaps TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        now = datetime.now(timezone.utc).isoformat()
        await dm._conversation._db.execute(
            "INSERT INTO conversations (user_id, channel, started_at, last_message_at) VALUES (?, ?, ?, ?)",
            ("user1", "cli", now, now),
        )
        await dm._conversation._db.execute(
            "INSERT INTO knowledge_gaps (query, state, gaps, created_at) VALUES (?, ?, ?, ?)",
            ("What is PF3?", "UNKNOWN", "[]", now),
        )
        await dm._conversation._db.commit()

        yield dm

        await dm._conversation._db.close()
        await dm.close()

    @pytest.mark.asyncio
    async def test_run_dream_cycle_produces_report(self, dream):
        from ira.schemas.llm_outputs import DreamGap, DreamConnection, DreamInsight as DreamInsightModel

        async def _mock_structured(system, user, model_cls, **kwargs):
            if model_cls is DreamGaps:
                return DreamGaps(gaps=[DreamGap(topic="PF3", description="No info on PF3", priority="HIGH")])
            if model_cls is DreamCreative:
                return DreamCreative(connections=[
                    DreamConnection(insight="PF3 interest may indicate market trend", supporting_evidence=[], confidence="MEDIUM")
                ])
            return model_cls()

        dream._llm.generate_structured = AsyncMock(side_effect=_mock_structured)

        report = await dream.run_dream_cycle()

        assert report.memories_consolidated >= 0
        assert isinstance(report.gaps_identified, list)
        assert isinstance(report.creative_connections, list)

    @pytest.mark.asyncio
    async def test_dream_cycle_skips_stage4_without_musculoskeletal(self, dream):
        async def _mock_structured(system, user, model_cls, **kwargs):
            return model_cls()

        dream._llm.generate_structured = AsyncMock(side_effect=_mock_structured)

        report = await dream.run_dream_cycle()

        assert report.campaign_insights == []

    @pytest.mark.asyncio
    async def test_dream_cycle_handles_stage_failure(self, dream):
        dream._episodic.consolidate_episode = AsyncMock(side_effect=RuntimeError("boom"))

        async def _mock_structured(system, user, model_cls, **kwargs):
            return model_cls()

        dream._llm.generate_structured = AsyncMock(side_effect=_mock_structured)

        report = await dream.run_dream_cycle()

        assert report is not None
        assert report.memories_consolidated == 0


# ═════════════════════════════════════════════════════════════════════════════
# GoalManager — sweep_stalled_goals
# ═════════════════════════════════════════════════════════════════════════════


class TestGoalManagerSweep:

    @pytest.fixture()
    async def goal_manager(self, tmp_path):
        from ira.memory.goal_manager import GoalManager

        db_path = str(tmp_path / "goals_test.db")
        with patch("ira.memory.goal_manager.get_llm_client", return_value=MagicMock()):
            gm = GoalManager(db_path=db_path)
        await gm.initialize()
        yield gm
        await gm.close()

    @pytest.mark.asyncio
    async def test_sweep_returns_empty_when_no_stalled(self, goal_manager):
        stalled = await goal_manager.sweep_stalled_goals(stale_hours=48)
        assert stalled == []

    @pytest.mark.asyncio
    async def test_sweep_finds_old_active_goals(self, goal_manager):
        from uuid import uuid4

        from ira.memory.goal_manager import GoalStatus, GoalType

        old_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        assert goal_manager._db is not None
        await goal_manager._db.execute(
            "INSERT INTO goals (id, goal_type, contact_id, status, required_slots, progress, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), GoalType.LEAD_QUALIFICATION.value, "contact-1",
             GoalStatus.ACTIVE.value, json.dumps({"company": None}), 0.0, old_time),
        )
        await goal_manager._db.commit()

        stalled = await goal_manager.sweep_stalled_goals(stale_hours=48)
        assert len(stalled) == 1
        assert stalled[0].contact_id == "contact-1"

    @pytest.mark.asyncio
    async def test_sweep_ignores_completed_goals(self, goal_manager):
        from uuid import uuid4

        from ira.memory.goal_manager import GoalStatus, GoalType

        old_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        assert goal_manager._db is not None
        await goal_manager._db.execute(
            "INSERT INTO goals (id, goal_type, contact_id, status, required_slots, progress, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), GoalType.MEETING_BOOKING.value, "contact-2",
             GoalStatus.COMPLETED.value, json.dumps({}), 1.0, old_time),
        )
        await goal_manager._db.commit()

        stalled = await goal_manager.sweep_stalled_goals(stale_hours=48)
        assert len(stalled) == 0

    @pytest.mark.asyncio
    async def test_sweep_ignores_recent_goals(self, goal_manager):
        from uuid import uuid4

        from ira.memory.goal_manager import GoalStatus, GoalType

        recent_time = datetime.now(timezone.utc).isoformat()
        assert goal_manager._db is not None
        await goal_manager._db.execute(
            "INSERT INTO goals (id, goal_type, contact_id, status, required_slots, progress, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), GoalType.QUOTE_PREPARATION.value, "contact-3",
             GoalStatus.ACTIVE.value, json.dumps({}), 0.5, recent_time),
        )
        await goal_manager._db.commit()

        stalled = await goal_manager.sweep_stalled_goals(stale_hours=48)
        assert len(stalled) == 0


# ── WP2: Cross-Agent Memory Consistency Tests ─────────────────────────────────


class TestSleepTrainerEventEmission:
    """Verify SleepTrainer emits KNOWLEDGE_CORRECTED events."""

    @pytest.mark.asyncio
    async def test_emits_events_after_training(self):
        from ira.brain.sleep_trainer import SleepTrainer
        from ira.schemas.llm_outputs import TruthHint, TruthHints

        store = MagicMock()
        store.get_pending_corrections = AsyncMock(return_value=[
            {"id": 1, "entity": "PF1", "category": "SPECS", "severity": "HIGH",
             "old_value": "400T", "new_value": "500T", "source": "test", "created_at": "2025-01-01"},
        ])
        store.mark_processed = AsyncMock()

        qdrant = MagicMock()
        qdrant.search = AsyncMock(return_value=[])
        qdrant.upsert_items = AsyncMock()

        embedding = MagicMock()
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()

        mock_llm = _mock_llm_client()
        mock_llm.generate_structured = AsyncMock(
            return_value=TruthHints(hints=[TruthHint(pattern="PF1 capacity", answer="500T", entity="PF1", category="SPECS")])
        )

        with patch("ira.brain.sleep_trainer.get_llm_client", return_value=mock_llm):
            trainer = SleepTrainer(
                correction_store=store,
                qdrant_manager=qdrant,
                embedding_service=embedding,
                data_event_bus=event_bus,
            )
            stats = await trainer.run_training()

        assert stats["status"] == "completed"
        event_bus.emit.assert_called()
        emitted_event = event_bus.emit.call_args[0][0]
        assert emitted_event.event_type.value == "knowledge_corrected"

    @pytest.mark.asyncio
    async def test_no_event_without_bus(self):
        from ira.brain.sleep_trainer import SleepTrainer

        store = MagicMock()
        store.get_pending_corrections = AsyncMock(return_value=[])

        qdrant = MagicMock()
        embedding = MagicMock()

        with patch("ira.brain.sleep_trainer.get_llm_client", return_value=_mock_llm_client()):
            trainer = SleepTrainer(
                correction_store=store,
                qdrant_manager=qdrant,
                embedding_service=embedding,
                data_event_bus=None,
            )
            stats = await trainer.run_training()

        assert stats["status"] == "no_corrections"


class TestFeedbackHandlerEventEmission:
    """Verify FeedbackHandler emits KNOWLEDGE_CORRECTED on negative feedback."""

    @pytest.mark.asyncio
    async def test_emits_event_on_correction(self):
        from ira.brain.feedback_handler import FeedbackHandler

        store = MagicMock()
        store.add_correction = AsyncMock(return_value=42)
        event_bus = MagicMock()
        event_bus.emit = AsyncMock()

        mock_llm = _mock_llm_client()
        with patch("ira.brain.feedback_handler.get_llm_client", return_value=mock_llm):
            handler = FeedbackHandler(
                correction_store=store,
                data_event_bus=event_bus,
            )

        result = await handler.process_feedback(
            message="That's wrong, it's 500T not 400T",
            previous_query="PF1 capacity",
            previous_response="The PF1 has 400T capacity",
            agents_used=["clio"],
        )

        assert result["polarity"] == "negative"
        event_bus.emit.assert_called()


class TestCorrectionLearnerReload:
    """Verify CorrectionLearner reloads on KNOWLEDGE_CORRECTED event."""

    @pytest.mark.asyncio
    async def test_on_knowledge_corrected_reloads(self, tmp_path):
        from ira.brain.correction_learner import CorrectionLearner

        data_path = tmp_path / "learned.json"
        data_path.write_text(json.dumps({
            "competitors": ["CompX"],
            "customers": [],
            "prospects": [],
            "entity_corrections": {},
            "price_corrections": [],
        }))

        learner = CorrectionLearner(data_path=data_path)
        learner._state = await learner._load()
        assert learner.is_competitor("CompX")

        data_path.write_text(json.dumps({
            "competitors": ["CompX", "CompY"],
            "customers": [],
            "prospects": [],
            "entity_corrections": {},
            "price_corrections": [],
        }))

        event = MagicMock()
        await learner.on_knowledge_corrected(event)
        assert learner.is_competitor("CompY")


# ── WP3: Hierarchical Memory Tests ───────────────────────────────────────────


class TestConversationSummarizedHistory:
    """Verify get_summarized_history returns recent + summary."""

    @pytest.mark.asyncio
    async def test_returns_recent_and_summary(self, tmp_path):
        from ira.memory.conversation import ConversationMemory

        db_path = str(tmp_path / "conv_test.db")
        mock_llm = _mock_llm_client()
        mock_llm.generate_text = AsyncMock(return_value="User discussed PF1 pricing and delivery.")

        with patch("ira.memory.conversation.get_llm_client", return_value=mock_llm):
            conv = ConversationMemory(db_path=db_path)
            await conv.initialize()

        for i in range(10):
            await conv.add_message("user@test.com", "CLI", "user", f"Message {i}")
            await conv.add_message("user@test.com", "CLI", "assistant", f"Response {i}")

        with patch("ira.memory.conversation.get_llm_client", return_value=mock_llm):
            conv._llm = mock_llm
            recent, summary = await conv.get_summarized_history(
                "user@test.com", "CLI", recent_limit=3, full_limit=20,
            )

        assert len(recent) == 3
        assert summary != ""
        assert "PF1" in summary

        await conv.close()

    @pytest.mark.asyncio
    async def test_short_history_returns_empty_summary(self, tmp_path):
        from ira.memory.conversation import ConversationMemory

        db_path = str(tmp_path / "conv_test2.db")
        mock_llm = _mock_llm_client()

        with patch("ira.memory.conversation.get_llm_client", return_value=mock_llm):
            conv = ConversationMemory(db_path=db_path)
            await conv.initialize()

        await conv.add_message("user@test.com", "CLI", "user", "Hello")
        await conv.add_message("user@test.com", "CLI", "assistant", "Hi there")

        recent, summary = await conv.get_summarized_history(
            "user@test.com", "CLI", recent_limit=5,
        )

        assert len(recent) == 2
        assert summary == ""

        await conv.close()
