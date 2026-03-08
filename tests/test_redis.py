"""Tests for the Redis integration — RedisCache, pipeline dedup, LLM caching, and MessageBus persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.redis_cache import RedisCache


# ═════════════════════════════════════════════════════════════════════════
# RedisCache — offline mode (no connection)
# ═════════════════════════════════════════════════════════════════════════


class TestRedisCacheOffline:
    """When Redis is unavailable, every operation degrades gracefully."""

    def _make_cache(self) -> RedisCache:
        cache = RedisCache.__new__(RedisCache)
        cache._url = ""
        cache._client = None
        return cache

    def test_available_is_false(self):
        cache = self._make_cache()
        assert cache.available is False

    async def test_get_returns_none(self):
        cache = self._make_cache()
        assert await cache.get("any_key") is None

    async def test_set_returns_false(self):
        cache = self._make_cache()
        assert await cache.set("k", "v") is False

    async def test_delete_returns_false(self):
        cache = self._make_cache()
        assert await cache.delete("k") is False

    async def test_get_json_returns_none(self):
        cache = self._make_cache()
        assert await cache.get_json("k") is None

    async def test_set_json_returns_false(self):
        cache = self._make_cache()
        assert await cache.set_json("k", {"a": 1}) is False

    async def test_dedup_check_returns_none(self):
        cache = self._make_cache()
        assert await cache.dedup_check("fp") is None

    async def test_llm_cache_returns_none(self):
        cache = self._make_cache()
        assert await cache.get_llm_cache("key") is None

    async def test_publish_returns_zero(self):
        cache = self._make_cache()
        assert await cache.publish("ch", "msg") == 0

    async def test_subscriber_returns_none(self):
        cache = self._make_cache()
        assert cache.subscriber() is None

    async def test_rate_limit_allows_when_offline(self):
        cache = self._make_cache()
        assert await cache.rate_limit_check("api", 10) is True

    async def test_health_check_disconnected(self):
        cache = self._make_cache()
        health = await cache.health_check()
        assert health["status"] == "disconnected"
        assert health["available"] is False


# ═════════════════════════════════════════════════════════════════════════
# RedisCache — with mocked Redis client
# ═════════════════════════════════════════════════════════════════════════


class TestRedisCacheOnline:
    """Tests with a mocked redis.asyncio client."""

    def _make_cache(self) -> tuple[RedisCache, AsyncMock]:
        cache = RedisCache.__new__(RedisCache)
        cache._url = "redis://mock:6379"
        mock_client = AsyncMock()
        cache._client = mock_client
        return cache, mock_client

    async def test_get_delegates_to_client(self):
        cache, client = self._make_cache()
        client.get.return_value = "hello"
        result = await cache.get("test_key")
        assert result == "hello"
        client.get.assert_called_once_with("ira:test_key")

    async def test_set_delegates_to_client(self):
        cache, client = self._make_cache()
        result = await cache.set("k", "v", ttl_seconds=60)
        assert result is True
        client.set.assert_called_once_with("ira:k", "v", ex=60)

    async def test_delete_delegates_to_client(self):
        cache, client = self._make_cache()
        result = await cache.delete("k")
        assert result is True
        client.delete.assert_called_once_with("ira:k")

    async def test_get_json_parses(self):
        cache, client = self._make_cache()
        client.get.return_value = '{"x": 42}'
        result = await cache.get_json("j")
        assert result == {"x": 42}

    async def test_get_json_returns_none_on_bad_json(self):
        cache, client = self._make_cache()
        client.get.return_value = "not-json"
        result = await cache.get_json("j")
        assert result is None

    async def test_set_json_serializes(self):
        cache, client = self._make_cache()
        await cache.set_json("j", {"a": 1}, ttl_seconds=120)
        client.set.assert_called_once()
        call_args = client.set.call_args
        assert '"a": 1' in call_args[0][1]

    async def test_dedup_roundtrip(self):
        cache, client = self._make_cache()
        client.get.return_value = None
        assert await cache.dedup_check("fp123") is None

        await cache.dedup_store("fp123", "response text", ttl_seconds=300)
        client.set.assert_called_once()

    async def test_llm_cache_roundtrip(self):
        cache, client = self._make_cache()
        client.get.return_value = None
        assert await cache.get_llm_cache("hash123") is None

        await cache.set_llm_cache("hash123", "LLM response", ttl_seconds=3600)
        client.set.assert_called_once()

    async def test_publish_delegates(self):
        cache, client = self._make_cache()
        client.publish.return_value = 2
        result = await cache.publish("events", "payload")
        assert result == 2
        client.publish.assert_called_once_with("ira:ch:events", "payload")

    async def test_health_check_connected(self):
        cache, client = self._make_cache()
        client.info.return_value = {"redis_version": "8.2.1", "uptime_in_days": 7}
        health = await cache.health_check()
        assert health["status"] == "connected"
        assert health["available"] is True
        assert health["redis_version"] == "8.2.1"

    async def test_close_calls_aclose(self):
        cache, client = self._make_cache()
        await cache.close()
        client.aclose.assert_called_once()
        assert cache._client is None


# ═════════════════════════════════════════════════════════════════════════
# ServiceKey registration
# ═════════════════════════════════════════════════════════════════════════


class TestServiceKeyRegistration:
    def test_redis_in_service_keys(self):
        from ira.service_keys import ALL_SERVICE_KEYS, ServiceKey
        assert ServiceKey.REDIS == "redis"
        assert "redis" in ALL_SERVICE_KEYS


# ═════════════════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════════════════


class TestRedisConfig:
    def test_redis_config_exists(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from ira.config import RedisConfig
        cfg = RedisConfig(_env_file=None)
        assert cfg.url == ""

    def test_settings_has_redis(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from ira.config import RedisConfig
        cfg = RedisConfig(_env_file=None)
        assert hasattr(cfg, "url")
        assert cfg.url == ""


# ═════════════════════════════════════════════════════════════════════════
# MessageBus Redis persistence
# ═════════════════════════════════════════════════════════════════════════


class TestMessageBusRedis:
    async def test_set_redis_enables_persistence(self):
        from ira.message_bus import MessageBus
        bus = MessageBus()
        assert bus._redis is None

        mock_redis = MagicMock()
        bus.set_redis(mock_redis)
        assert bus._redis is mock_redis

    async def test_publish_persists_to_redis_stream(self):
        from ira.data.models import AgentMessage
        from ira.message_bus import MessageBus

        bus = MessageBus()
        mock_redis = MagicMock()
        mock_redis.available = True
        mock_redis._client = AsyncMock()
        bus.set_redis(mock_redis)

        msg = AgentMessage(
            from_agent="clio",
            to_agent="prometheus",
            query="test query",
            context={},
        )
        await bus.publish(msg)

        mock_redis._client.xadd.assert_called_once()

    async def test_publish_works_without_redis(self):
        from ira.data.models import AgentMessage
        from ira.message_bus import MessageBus

        bus = MessageBus()
        msg = AgentMessage(
            from_agent="clio",
            to_agent="prometheus",
            query="test",
            context={},
        )
        await bus.publish(msg)
        assert bus.pending_count == 1


# ═════════════════════════════════════════════════════════════════════════
# BaseAgent LLM caching
# ═════════════════════════════════════════════════════════════════════════


class TestBaseAgentLLMCache:
    def test_llm_cache_key_deterministic(self):
        from ira.agents.base_agent import BaseAgent

        class DummyAgent(BaseAgent):
            name = "test"
            async def handle(self, query, context=None):
                return ""

        mock_retriever = MagicMock()
        mock_bus = MagicMock()

        with patch("ira.agents.base_agent.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(
                    openai_api_key=MagicMock(get_secret_value=lambda: ""),
                    openai_model="gpt-4",
                    anthropic_api_key=MagicMock(get_secret_value=lambda: ""),
                    anthropic_model="claude-3",
                ),
            )
            agent = DummyAgent(retriever=mock_retriever, bus=mock_bus)

        key1 = agent._llm_cache_key("sys", "user", 0.3)
        key2 = agent._llm_cache_key("sys", "user", 0.3)
        key3 = agent._llm_cache_key("sys", "different", 0.3)

        assert key1 == key2
        assert key1 != key3
        assert len(key1) == 24
