"""Tests for ImmuneSystem cloud recovery and health-check correctness.

Verifies that Qdrant Cloud and Neo4j Aura reconnection paths pass all
required parameters (timeout, pool size, etc.) and that _check_qdrant
correctly reports unhealthy when the expected collection is missing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_settings_mock(
    *,
    qdrant_url: str = "https://cluster.cloud.qdrant.io:6333",
    qdrant_api_key: str = "cloud-key",
    qdrant_timeout: float = 30.0,
    neo4j_uri: str = "neo4j+s://abc.databases.neo4j.io",
    neo4j_pool_size: int = 50,
) -> MagicMock:
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.qdrant.url = qdrant_url
    s.qdrant.api_key.get_secret_value.return_value = qdrant_api_key
    s.qdrant.timeout = qdrant_timeout
    s.qdrant.collection = "ira_knowledge_v3"
    s.qdrant.cloud_url = ""
    s.qdrant.cloud_api_key.get_secret_value.return_value = ""
    s.neo4j.uri = neo4j_uri
    s.neo4j.user = "neo4j"
    s.neo4j.password.get_secret_value.return_value = "aura-pass"
    s.neo4j.resolved_auth.return_value = ("neo4j", "aura-pass")
    s.database.url = "sqlite+aiosqlite://"
    s.langfuse.public_key = ""
    s.langfuse.secret_key.get_secret_value.return_value = ""
    s.langfuse.base_url = "https://cloud.langfuse.com"
    s.app.neo4j_max_pool_size = neo4j_pool_size
    return s


def _build_immune(settings_mock: MagicMock):
    mock_qdrant = MagicMock()
    mock_qdrant._client = AsyncMock()
    mock_qdrant._default_collection = "ira_knowledge_v3"
    mock_qdrant.ensure_collection = AsyncMock()

    mock_graph = AsyncMock()
    mock_graph.run_cypher = AsyncMock(return_value=[{"ok": 1}])
    mock_graph._driver = AsyncMock()

    mock_embeddings = AsyncMock()
    mock_embeddings.embed_texts = AsyncMock(return_value=[[0.1] * 8])

    with patch("ira.systems.immune.get_settings", return_value=settings_mock):
        from ira.systems.immune import ImmuneSystem
        immune = ImmuneSystem(mock_qdrant, mock_graph, mock_embeddings)

    return immune


# ── Qdrant recovery ──────────────────────────────────────────────────────


class TestQdrantRecoveryParams:
    """Qdrant recovery must recreate the client with timeout for cloud."""

    @pytest.fixture()
    def settings(self):
        return _make_settings_mock(qdrant_timeout=45.0)

    @pytest.mark.asyncio
    async def test_recovery_passes_timeout(self, settings):
        immune = _build_immune(settings)

        mock_collection = MagicMock()
        mock_collection.name = "ira_knowledge_v3"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]

        with patch("ira.systems.immune.get_settings", return_value=settings), \
             patch("ira.systems.immune.AsyncQdrantClient") as MockClient:
            new_client = AsyncMock()
            new_client.get_collections = AsyncMock(return_value=mock_collections)
            MockClient.return_value = new_client

            result = await immune.attempt_recovery("qdrant")

        assert result["success"] is True
        MockClient.assert_called_once_with(
            url=settings.qdrant.url,
            api_key="cloud-key",
            check_compatibility=False,
            timeout=45.0,
        )

    @pytest.mark.asyncio
    async def test_recovery_passes_api_key(self, settings):
        immune = _build_immune(settings)

        mock_collection = MagicMock()
        mock_collection.name = "ira_knowledge_v3"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]

        with patch("ira.systems.immune.get_settings", return_value=settings), \
             patch("ira.systems.immune.AsyncQdrantClient") as MockClient:
            new_client = AsyncMock()
            new_client.get_collections = AsyncMock(return_value=mock_collections)
            MockClient.return_value = new_client

            await immune.attempt_recovery("qdrant")

        call_kwargs = MockClient.call_args.kwargs
        assert call_kwargs["api_key"] == "cloud-key"

    @pytest.mark.asyncio
    async def test_recovery_with_empty_api_key_passes_none(self):
        settings = _make_settings_mock(qdrant_api_key="")
        immune = _build_immune(settings)

        mock_collection = MagicMock()
        mock_collection.name = "ira_knowledge_v3"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]

        with patch("ira.systems.immune.get_settings", return_value=settings), \
             patch("ira.systems.immune.AsyncQdrantClient") as MockClient:
            new_client = AsyncMock()
            new_client.get_collections = AsyncMock(return_value=mock_collections)
            MockClient.return_value = new_client

            await immune.attempt_recovery("qdrant")

        call_kwargs = MockClient.call_args.kwargs
        assert call_kwargs["api_key"] is None


# ── Neo4j recovery ───────────────────────────────────────────────────────


class TestNeo4jRecoveryParams:
    """Neo4j recovery must recreate the driver with pool config for Aura."""

    @pytest.fixture()
    def settings(self):
        return _make_settings_mock(neo4j_pool_size=30)

    @pytest.mark.asyncio
    async def test_recovery_passes_pool_size_and_acquisition_timeout(self, settings):
        immune = _build_immune(settings)

        with patch("ira.systems.immune.get_settings", return_value=settings), \
             patch("neo4j.AsyncGraphDatabase.driver") as MockDriver:
            mock_driver = AsyncMock()
            MockDriver.return_value = mock_driver

            result = await immune.attempt_recovery("neo4j")

        assert result["success"] is True
        MockDriver.assert_called_once_with(
            settings.neo4j.uri,
            auth=("neo4j", "aura-pass"),
            max_connection_pool_size=30,
            connection_acquisition_timeout=60.0,
        )

    @pytest.mark.asyncio
    async def test_recovery_uses_aura_uri(self, settings):
        immune = _build_immune(settings)

        with patch("ira.systems.immune.get_settings", return_value=settings), \
             patch("neo4j.AsyncGraphDatabase.driver") as MockDriver:
            MockDriver.return_value = AsyncMock()

            await immune.attempt_recovery("neo4j")

        call_args = MockDriver.call_args
        assert call_args[0][0] == "neo4j+s://abc.databases.neo4j.io"


# ── _check_qdrant health correctness ─────────────────────────────────────


class TestCheckQdrantCollectionHealth:
    """_check_qdrant must return unhealthy when the collection is missing."""

    @pytest.fixture()
    def immune(self):
        return _build_immune(_make_settings_mock())

    @pytest.mark.asyncio
    async def test_healthy_when_collection_exists(self, immune):
        mock_collection = MagicMock()
        mock_collection.name = "ira_knowledge_v3"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]
        immune._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        result = await immune._check_qdrant()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert result["latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_unhealthy_when_collection_missing(self, immune):
        other_collection = MagicMock()
        other_collection.name = "some_other_collection"
        mock_collections = MagicMock()
        mock_collections.collections = [other_collection]
        immune._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        result = await immune._check_qdrant()

        assert result["status"] == "unhealthy"
        assert "ira_knowledge_v3" in result["error"]
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_unhealthy_when_no_collections(self, immune):
        mock_collections = MagicMock()
        mock_collections.collections = []
        immune._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        result = await immune._check_qdrant()

        assert result["status"] == "unhealthy"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_collection_triggers_sense_lost_via_validation(self, immune):
        """Full startup validation marks qdrant as sense_lost when collection is missing."""
        other_collection = MagicMock()
        other_collection.name = "wrong_collection"
        mock_collections = MagicMock()
        mock_collections.collections = [other_collection]
        immune._qdrant._client.get_collections = AsyncMock(return_value=mock_collections)

        immune._check_postgresql = AsyncMock(
            return_value={"status": "healthy", "latency_ms": 5.0, "error": None},
        )
        immune._check_openai = AsyncMock(
            return_value={"status": "healthy", "latency_ms": 10.0, "error": None},
        )
        immune._check_voyage = AsyncMock(
            return_value={"status": "healthy", "latency_ms": 10.0, "error": None},
        )
        immune._check_langfuse = AsyncMock(
            return_value={"status": "not_configured", "latency_ms": None, "error": None},
        )

        report = await immune.run_startup_validation()

        assert report["qdrant"]["status"] == "unhealthy"
        assert immune.get_sense_lost()["qdrant"] is True
