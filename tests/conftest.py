"""Shared test fixtures for the Ira test suite.

Provides reusable mocks for settings, services, and common data objects
so individual test files don't need to duplicate boilerplate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ira.config import EmailMode
from ira.data.models import Channel, Contact, Direction, Email, KnowledgeState


@pytest.fixture()
def mock_settings():
    """Fully mocked IraSettings matching the .env.example structure."""
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-test"
    s.llm.anthropic_api_key.get_secret_value.return_value = ""
    s.llm.anthropic_model = "claude-test"
    s.external_apis.api_key.get_secret_value.return_value = ""
    s.google.credentials_path = "/tmp/creds.json"
    s.google.token_path = "/tmp/token.json"
    s.google.ira_email = "ira@example.com"
    s.google.training_email = "founder@example.com"
    s.google.email_mode = EmailMode.TRAINING
    s.embedding.api_key.get_secret_value.return_value = ""
    s.embedding.model = "voyage-test"
    s.qdrant.url = "http://localhost:6333"
    s.qdrant.collection = "test"
    s.qdrant.api_key.get_secret_value.return_value = ""
    s.neo4j.uri = "bolt://localhost:7687"
    s.neo4j.user = "neo4j"
    s.neo4j.password.get_secret_value.return_value = ""
    s.database.url = "sqlite+aiosqlite://"
    s.memory.api_key.get_secret_value.return_value = ""
    s.telegram.bot_token.get_secret_value.return_value = ""
    s.telegram.admin_chat_id = ""
    s.app.log_level = "WARNING"
    s.app.environment = "test"
    s.app.cors_origins = ""
    s.app.api_secret_key.get_secret_value.return_value = ""
    s.redis.url = "redis://localhost:6379/0"
    return s


@pytest.fixture()
def sample_contact():
    """A minimal Contact for testing."""
    return Contact(
        name="Test User",
        email="test@example.com",
        channel=Channel.EMAIL,
        direction=Direction.INBOUND,
        knowledge_state=KnowledgeState.UNKNOWN,
    )


@pytest.fixture()
def sample_email():
    """A minimal Email for testing."""
    return Email(
        id="msg_test_001",
        from_address="client@example.com",
        to_address="founder@example.com",
        subject="Test email",
        body="Hello, I need pricing for PF1-C.",
        received_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        thread_id="thread_test_001",
    )


@pytest.fixture()
def mock_retriever():
    """AsyncMock for UnifiedRetriever."""
    retriever = AsyncMock()
    retriever.search.return_value = []
    retriever.close = AsyncMock()
    return retriever


@pytest.fixture()
def mock_pantheon():
    """MagicMock for Pantheon with basic agent routing."""
    pantheon = MagicMock()
    pantheon.route_query = AsyncMock(return_value="Test response")
    pantheon.get_agent = MagicMock(return_value=None)
    pantheon.inject_services = MagicMock()
    return pantheon
