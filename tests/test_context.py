"""Tests for the UnifiedContextManager — cross-channel context preservation."""

from __future__ import annotations

from ira.context import UnifiedContextManager, UserContext


class TestUserContextDefaults:
    def test_new_context_has_empty_history(self):
        ctx = UserContext(user_id="alice")
        assert ctx.history == []
        assert ctx.active_goals == []
        assert ctx.last_channel == ""

    def test_user_id_is_stored(self):
        ctx = UserContext(user_id="bob@example.com")
        assert ctx.user_id == "bob@example.com"


class TestUnifiedContextManagerBasics:
    def test_get_creates_new_context(self):
        mgr = UnifiedContextManager()
        ctx = mgr.get("user-1")
        assert ctx.user_id == "user-1"
        assert ctx.history == []

    def test_get_returns_same_context_on_second_call(self):
        mgr = UnifiedContextManager()
        ctx1 = mgr.get("user-1")
        ctx2 = mgr.get("user-1")
        assert ctx1 is ctx2

    def test_different_users_get_different_contexts(self):
        mgr = UnifiedContextManager()
        a = mgr.get("alice")
        b = mgr.get("bob")
        assert a is not b
        assert a.user_id == "alice"
        assert b.user_id == "bob"

    def test_save_persists_changes(self):
        mgr = UnifiedContextManager()
        ctx = mgr.get("user-1")
        ctx.metadata["key"] = "value"
        mgr.save(ctx)
        assert mgr.get("user-1").metadata["key"] == "value"

    def test_all_users_lists_known_ids(self):
        mgr = UnifiedContextManager()
        mgr.get("alice")
        mgr.get("bob")
        assert sorted(mgr.all_users()) == ["alice", "bob"]


class TestRecordTurn:
    def test_records_user_and_assistant_messages(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("u1", "cli", "hello", "hi there")
        history = mgr.get("u1").history
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"
        assert history[0]["channel"] == "cli"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "hi there"

    def test_updates_last_channel(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("u1", "email", "msg", "reply")
        assert mgr.get("u1").last_channel == "email"
        mgr.record_turn("u1", "cli", "msg2", "reply2")
        assert mgr.get("u1").last_channel == "cli"

    def test_updates_last_interaction_at(self):
        mgr = UnifiedContextManager()
        ctx_before = mgr.get("u1")
        ts_before = ctx_before.last_interaction_at
        mgr.record_turn("u1", "cli", "q", "a")
        assert mgr.get("u1").last_interaction_at >= ts_before

    def test_trims_history_at_max(self):
        mgr = UnifiedContextManager()
        for i in range(30):
            mgr.record_turn("u1", "cli", f"q{i}", f"a{i}")
        assert len(mgr.get("u1").history) <= 50

    def test_returns_updated_context(self):
        mgr = UnifiedContextManager()
        ctx = mgr.record_turn("u1", "api", "q", "a")
        assert ctx.user_id == "u1"
        assert len(ctx.history) == 2


class TestCrossChannelPreservation:
    """The core requirement: context persists across different channels."""

    def test_cli_then_email_sees_full_history(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("alice", "cli", "What is PF1-C?", "It's a machine.")
        mgr.record_turn("alice", "email", "Send me a quote", "Sure, here it is.")

        history = mgr.recent_history("alice", limit=10)
        assert len(history) == 4
        channels = [m["channel"] for m in history]
        assert "cli" in channels
        assert "email" in channels

    def test_cli_then_api_then_web(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("bob", "cli", "q1", "a1")
        mgr.record_turn("bob", "api", "q2", "a2")
        mgr.record_turn("bob", "web", "q3", "a3")

        history = mgr.recent_history("bob")
        assert len(history) == 6
        assert history[0]["channel"] == "cli"
        assert history[2]["channel"] == "api"
        assert history[4]["channel"] == "web"

    def test_channel_filter_returns_only_matching(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("alice", "cli", "cli msg", "cli reply")
        mgr.record_turn("alice", "email", "email msg", "email reply")
        mgr.record_turn("alice", "cli", "cli msg 2", "cli reply 2")

        cli_only = mgr.recent_history("alice", channel="cli")
        assert len(cli_only) == 4
        assert all(m["channel"] == "cli" for m in cli_only)

        email_only = mgr.recent_history("alice", channel="email")
        assert len(email_only) == 2
        assert all(m["channel"] == "email" for m in email_only)

    def test_unfiltered_returns_all_channels(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("alice", "cli", "a", "b")
        mgr.record_turn("alice", "email", "c", "d")

        all_msgs = mgr.recent_history("alice")
        assert len(all_msgs) == 4

    def test_separate_users_do_not_leak(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("alice", "cli", "alice q", "alice a")
        mgr.record_turn("bob", "email", "bob q", "bob a")

        alice_h = mgr.recent_history("alice")
        bob_h = mgr.recent_history("bob")
        assert len(alice_h) == 2
        assert len(bob_h) == 2
        assert alice_h[0]["content"] == "alice q"
        assert bob_h[0]["content"] == "bob q"

    def test_last_channel_tracks_most_recent(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("alice", "cli", "a", "b")
        assert mgr.get("alice").last_channel == "cli"
        mgr.record_turn("alice", "email", "c", "d")
        assert mgr.get("alice").last_channel == "email"
        mgr.record_turn("alice", "cli", "e", "f")
        assert mgr.get("alice").last_channel == "cli"


class TestGoalManagement:
    def test_set_and_retrieve_goal(self):
        mgr = UnifiedContextManager()
        mgr.set_active_goal("u1", {"id": "g1", "type": "quote_request"})
        goals = mgr.get("u1").active_goals
        assert len(goals) == 1
        assert goals[0]["id"] == "g1"

    def test_set_replaces_goal_with_same_id(self):
        mgr = UnifiedContextManager()
        mgr.set_active_goal("u1", {"id": "g1", "type": "quote"})
        mgr.set_active_goal("u1", {"id": "g1", "type": "updated_quote"})
        goals = mgr.get("u1").active_goals
        assert len(goals) == 1
        assert goals[0]["type"] == "updated_quote"

    def test_clear_goal_removes_by_id(self):
        mgr = UnifiedContextManager()
        mgr.set_active_goal("u1", {"id": "g1", "type": "quote"})
        mgr.set_active_goal("u1", {"id": "g2", "type": "support"})
        mgr.clear_goal("u1", "g1")
        goals = mgr.get("u1").active_goals
        assert len(goals) == 1
        assert goals[0]["id"] == "g2"

    def test_clear_nonexistent_goal_is_noop(self):
        mgr = UnifiedContextManager()
        mgr.set_active_goal("u1", {"id": "g1", "type": "quote"})
        mgr.clear_goal("u1", "g999")
        assert len(mgr.get("u1").active_goals) == 1


class TestRecentHistoryLimit:
    def test_limit_truncates_results(self):
        mgr = UnifiedContextManager()
        for i in range(10):
            mgr.record_turn("u1", "cli", f"q{i}", f"a{i}")

        limited = mgr.recent_history("u1", limit=4)
        assert len(limited) == 4
        assert limited[-1]["content"] == "a9"

    def test_limit_larger_than_history_returns_all(self):
        mgr = UnifiedContextManager()
        mgr.record_turn("u1", "cli", "q", "a")
        result = mgr.recent_history("u1", limit=100)
        assert len(result) == 2
