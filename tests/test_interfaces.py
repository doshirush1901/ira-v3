"""Comprehensive tests for interfaces, server endpoints, and the request pipeline.

Covers:
- EmailProcessor TRAINING / OPERATIONAL modes
- CLI commands (ask, agents, email draft)
- FastAPI server endpoints (query, health, agents)
- RequestPipeline 11-step end-to-end with mocked services
"""

from __future__ import annotations

import base64
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ira.config import EmailMode
from ira.data.models import Channel, Contact, Direction, Email, KnowledgeState


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_settings(email_mode: EmailMode = EmailMode.TRAINING) -> MagicMock:
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-key"
    s.llm.openai_model = "gpt-test"
    s.llm.anthropic_api_key.get_secret_value.return_value = ""
    s.llm.anthropic_model = "claude-test"
    s.external_apis.api_key.get_secret_value.return_value = ""
    s.google.credentials_path = "/tmp/creds.json"
    s.google.token_path = "/tmp/token.json"
    s.google.ira_email = "ira@machinecraft.org"
    s.google.training_email = "rushabh@machinecraft.org"
    s.google.email_mode = email_mode
    s.embedding.api_key.get_secret_value.return_value = ""
    s.embedding.model = "voyage-test"
    s.qdrant.url = "http://localhost:6333"
    s.qdrant.collection = "test"
    s.neo4j.uri = "bolt://localhost:7687"
    s.neo4j.user = "neo4j"
    s.neo4j.password.get_secret_value.return_value = ""
    s.database.url = "sqlite+aiosqlite://"
    s.memory.api_key.get_secret_value.return_value = ""
    s.telegram.bot_token.get_secret_value.return_value = ""
    s.telegram.admin_chat_id = ""
    s.app.log_level = "WARNING"
    s.app.environment = "test"
    return s


def _make_email(
    from_addr: str = "client@example.com",
    to_addr: str = "rushabh@machinecraft.org",
    subject: str = "Test email",
    body: str = "Hello, I need pricing for PF1-C.",
    msg_id: str = "msg_001",
    thread_id: str = "thread_001",
) -> Email:
    return Email(
        id=msg_id,
        from_address=from_addr,
        to_address=to_addr,
        subject=subject,
        body=body,
        received_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        thread_id=thread_id,
        labels=["INBOX"],
    )


def _make_gmail_raw_message(
    msg_id: str = "msg_001",
    from_addr: str = "client@example.com",
    to_addr: str = "rushabh@machinecraft.org",
    subject: str = "Test email",
    body: str = "Hello, I need pricing for PF1-C.",
    thread_id: str = "thread_001",
) -> dict:
    encoded_body = base64.urlsafe_b64encode(body.encode()).decode()
    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Sun, 01 Jun 2025 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded_body},
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Module importability (preserved from original)
# ═══════════════════════════════════════════════════════════════════════════════


class TestInterfaceModulesExist:
    @pytest.mark.parametrize("module_name", [
        "ira.interfaces",
        "ira.interfaces.cli",
        "ira.interfaces.server",
        "ira.interfaces.email_processor",
        "ira.interfaces.telegram_bot",
    ])
    def test_module_importable(self, module_name: str):
        mod = importlib.import_module(module_name)
        assert mod is not None


class TestInterfacesPackage:
    def test_package_has_init(self):
        import ira.interfaces
        assert ira.interfaces.__name__ == "ira.interfaces"


# ═══════════════════════════════════════════════════════════════════════════════
# EmailProcessor — TRAINING mode
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmailProcessorTraining:
    """EmailProcessor in TRAINING mode: observe-only, no sending/drafting."""

    @pytest.fixture()
    def training_processor(self):
        settings = _make_settings(EmailMode.TRAINING)
        delphi = AsyncMock()
        delphi.handle = AsyncMock(return_value='{"intent":"QUOTE_REQUEST","urgency":"HIGH","suggested_agent":"plutus","summary":"Pricing inquiry"}')
        digestive = AsyncMock()
        digestive.ingest_email = AsyncMock(return_value={"chunks_created": 2, "entities_found": {"companies": 1}})
        sensory = AsyncMock()
        sensory.resolve_identity = AsyncMock(return_value=Contact(
            name="Test Client", email="client@example.com", source="test",
        ))
        crm = AsyncMock()
        crm.create_interaction = AsyncMock()

        from ira.interfaces.email_processor import EmailProcessor
        proc = EmailProcessor(delphi, digestive, sensory, crm, settings=settings)
        proc._delphi = delphi
        proc._digestive = digestive
        proc._sensory = sensory
        proc._crm = crm
        return proc

    def test_training_mode_initialises(self, training_processor):
        assert training_processor._mode is EmailMode.TRAINING
        assert training_processor._training_email == "rushabh@machinecraft.org"

    def test_no_public_send_method_exists(self, training_processor):
        assert not hasattr(training_processor, "send_email")

    def test_parse_message_extracts_fields(self, training_processor):
        raw = _make_gmail_raw_message()
        email = training_processor._parse_message(raw)
        assert email.id == "msg_001"
        assert email.from_address == "client@example.com"
        assert email.subject == "Test email"
        assert "pricing" in email.body.lower()

    def test_parse_message_multipart(self, training_processor):
        encoded = base64.urlsafe_b64encode(b"Multipart body").decode()
        raw = {
            "id": "msg_mp",
            "threadId": "t1",
            "labelIds": [],
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "To", "value": "c@d.com"},
                    {"name": "Subject", "value": "MP"},
                    {"name": "Date", "value": ""},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded}},
                    {"mimeType": "text/html", "body": {"data": encoded}},
                ],
            },
        }
        email = training_processor._parse_message(raw)
        assert email.body == "Multipart body"

    def test_infer_direction_inbound(self, training_processor):
        email = _make_email(from_addr="client@example.com")
        assert training_processor._infer_direction(email) is Direction.INBOUND

    def test_infer_direction_outbound(self, training_processor):
        email = _make_email(from_addr="rushabh@machinecraft.org", to_addr="client@example.com")
        assert training_processor._infer_direction(email) is Direction.OUTBOUND

    async def test_analyze_email_runs_full_pipeline(self, training_processor):
        email = _make_email()
        result = await training_processor._analyze_email(email)

        training_processor._delphi.handle.assert_awaited_once()
        training_processor._digestive.ingest_email.assert_awaited_once_with(email)
        training_processor._sensory.resolve_identity.assert_awaited_once()
        training_processor._crm.create_interaction.assert_awaited_once()

        assert result["email_id"] == "msg_001"
        assert result["direction"] == "INBOUND"
        assert result["classification"]["intent"] == "QUOTE_REQUEST"

    async def test_analyze_email_logs_crm_interaction(self, training_processor):
        email = _make_email()
        await training_processor._analyze_email(email)

        call_kwargs = training_processor._crm.create_interaction.call_args
        assert call_kwargs.kwargs["channel"] is Channel.EMAIL
        assert call_kwargs.kwargs["direction"] is Direction.INBOUND
        assert call_kwargs.kwargs["subject"] == "Test email"

    def test_safe_parse_json_valid(self):
        from ira.interfaces.email_processor import EmailProcessor
        result = EmailProcessor._safe_parse_json('{"intent": "QUOTE_REQUEST"}')
        assert result["intent"] == "QUOTE_REQUEST"

    def test_safe_parse_json_markdown_fenced(self):
        from ira.interfaces.email_processor import EmailProcessor
        result = EmailProcessor._safe_parse_json('```json\n{"intent": "SUPPORT"}\n```')
        assert result["intent"] == "SUPPORT"

    def test_safe_parse_json_invalid_returns_raw(self):
        from ira.interfaces.email_processor import EmailProcessor
        result = EmailProcessor._safe_parse_json("not json at all")
        assert "raw_response" in result


class TestEmailProcessorOperational:
    """EmailProcessor in OPERATIONAL mode: drafts, notifications, no direct send."""

    @pytest.fixture()
    def operational_processor(self):
        settings = _make_settings(EmailMode.OPERATIONAL)
        delphi = AsyncMock()
        delphi.handle = AsyncMock(
            return_value='{"intent":"QUOTE_REQUEST","urgency":"HIGH",'
            '"suggested_agent":"plutus","summary":"Pricing inquiry"}',
        )
        digestive = AsyncMock()
        digestive.ingest_email = AsyncMock(
            return_value={"chunks_created": 2, "entities_found": {"companies": 1}},
        )
        sensory = AsyncMock()
        sensory.resolve_identity = AsyncMock(return_value=Contact(
            name="Test Client", email="client@example.com", source="test",
        ))
        crm = AsyncMock()
        crm.create_interaction = AsyncMock()

        plutus = AsyncMock()
        plutus.handle = AsyncMock(return_value="Thank you for your inquiry. Here is the quote.")
        athena = AsyncMock()
        athena.handle = AsyncMock(return_value="Athena fallback reply.")

        pantheon = MagicMock()
        def _get_agent(name: str):
            if name == "plutus":
                return plutus
            if name == "athena":
                return athena
            return None
        pantheon.get_agent = MagicMock(side_effect=_get_agent)

        from ira.interfaces.email_processor import EmailProcessor
        proc = EmailProcessor(
            delphi, digestive, sensory, crm,
            pantheon=pantheon, settings=settings,
        )
        proc._plutus = plutus
        proc._athena = athena
        return proc

    def test_operational_mode_initialises(self, operational_processor):
        assert operational_processor._mode is EmailMode.OPERATIONAL
        assert operational_processor._operational_email == "ira@machinecraft.org"

    def test_operational_stores_dependencies(self, operational_processor):
        assert operational_processor._delphi is not None
        assert operational_processor._pantheon is not None

    async def test_observe_inbox_returns_empty_in_operational(self, operational_processor):
        result = await operational_processor.observe_inbox()
        assert result == []

    async def test_process_inbox_creates_draft_for_reply_intent(self, operational_processor):
        """Verify that process_inbox creates a draft and does NOT send directly."""
        raw_msg = _make_gmail_raw_message(
            to_addr="ira@machinecraft.org",
            body="I need a quote for the PF1-C machine.",
        )

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg_001"}],
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = raw_msg
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft_001",
        }
        mock_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

        operational_processor._service = mock_service

        with patch.object(operational_processor, "_send_telegram_notification", new_callable=AsyncMock) as mock_tg:
            results = await operational_processor.process_inbox()

        assert len(results) == 1
        assert results[0]["draft_created"] is True

        mock_service.users.return_value.drafts.return_value.create.assert_called_once()
        mock_service.users.return_value.messages.return_value.modify.assert_called_once()
        mock_tg.assert_awaited_once()

        send_mock = mock_service.users.return_value.messages.return_value.send
        send_mock.assert_not_called()

    async def test_process_inbox_skips_draft_for_spam(self, operational_processor):
        """SPAM intent should not create a draft."""
        operational_processor._delphi.handle = AsyncMock(
            return_value='{"intent":"SPAM","urgency":"LOW","suggested_agent":"","summary":"Spam"}',
        )
        raw_msg = _make_gmail_raw_message(
            to_addr="ira@machinecraft.org",
            body="Buy cheap watches now!",
        )

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg_spam"}],
        }
        mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = raw_msg
        mock_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

        operational_processor._service = mock_service

        with patch.object(operational_processor, "_send_telegram_notification", new_callable=AsyncMock) as mock_tg:
            results = await operational_processor.process_inbox()

        assert len(results) == 1
        assert results[0]["draft_created"] is False
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        mock_tg.assert_not_awaited()

    async def test_telegram_notification_sent_with_subject(self, operational_processor):
        """Verify the Telegram notification includes the email subject."""
        with patch("ira.interfaces.email_processor.get_settings") as mock_gs:
            mock_gs.return_value.telegram.bot_token.get_secret_value.return_value = "fake-token"
            mock_gs.return_value.telegram.admin_chat_id = "12345"

            with patch("ira.interfaces.email_processor.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await operational_processor._send_telegram_notification("PF1-C Quote Request")

                mock_client.post.assert_awaited_once()
                call_kwargs = mock_client.post.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                assert "PF1-C Quote Request" in payload["text"]
                assert "review and send" in payload["text"].lower()

    async def test_mark_as_read_removes_unread_label(self, operational_processor):
        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}
        await operational_processor._mark_as_read(mock_service, "msg_001")

        mock_service.users.return_value.messages.return_value.modify.assert_called_once()
        call_kwargs = mock_service.users.return_value.messages.return_value.modify.call_args
        assert call_kwargs.kwargs["body"] == {"removeLabelIds": ["UNREAD"]}

    async def test_create_draft_includes_thread_id(self, operational_processor):
        mock_service = MagicMock()
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft_001",
        }
        await operational_processor._create_draft(
            mock_service, "client@example.com", "Test", "Reply body", "thread_001",
        )

        call_kwargs = mock_service.users.return_value.drafts.return_value.create.call_args
        draft_body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert draft_body["message"]["threadId"] == "thread_001"

    def test_infer_direction_operational_inbound(self, operational_processor):
        email = _make_email(
            from_addr="client@example.com",
            to_addr="ira@machinecraft.org",
        )
        assert operational_processor._infer_direction(email) is Direction.INBOUND

    def test_infer_direction_operational_outbound(self, operational_processor):
        email = _make_email(
            from_addr="ira@machinecraft.org",
            to_addr="client@example.com",
        )
        assert operational_processor._infer_direction(email) is Direction.OUTBOUND


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLI:
    """Test CLI commands via typer's CliRunner."""

    @pytest.fixture()
    def runner(self):
        from typer.testing import CliRunner
        return CliRunner()

    @pytest.fixture()
    def cli_app(self):
        from ira.interfaces.cli import app
        return app

    def test_help_shows_all_commands(self, runner, cli_app):
        result = runner.invoke(cli_app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("chat", "ask", "agents", "email", "pipeline", "health", "board", "dream", "ingest", "graduate"):
            assert cmd in result.output

    def test_email_subcommands_exist(self, runner, cli_app):
        result = runner.invoke(cli_app, ["email", "--help"])
        assert result.exit_code == 0
        assert "draft" in result.output
        assert "learn" in result.output

    @patch("ira.interfaces.cli._build_pipeline")
    @patch("ira.interfaces.cli._build_pantheon")
    def test_ask_invokes_pantheon(self, mock_build, mock_build_pipeline, runner, cli_app):
        mock_pantheon = MagicMock()
        mock_pantheon.process = AsyncMock(return_value="Test response from Ira")
        mock_pantheon.start = AsyncMock()
        mock_pantheon.stop = AsyncMock()
        mock_pantheon.__aenter__ = AsyncMock(return_value=mock_pantheon)
        mock_pantheon.__aexit__ = AsyncMock(return_value=False)
        mock_build.return_value = mock_pantheon

        mock_pipeline = MagicMock()
        mock_pipeline.process_request = AsyncMock(return_value="Test response from Ira")
        mock_build_pipeline.return_value = mock_pipeline

        result = runner.invoke(cli_app, ["ask", "What machines do we sell?"])
        assert result.exit_code == 0
        assert "Test response from Ira" in result.output

    @patch("ira.interfaces.cli._build_pantheon")
    def test_agents_lists_all(self, mock_build, runner, cli_app):
        mock_agent = MagicMock()
        mock_agent.name = "clio"
        mock_agent.role = "Research"
        mock_agent.description = "Knowledge retrieval"

        mock_pantheon = MagicMock()
        mock_pantheon.agents = {"clio": mock_agent}
        mock_build.return_value = mock_pantheon

        result = runner.invoke(cli_app, ["agents"])
        assert result.exit_code == 0
        assert "clio" in result.output
        assert "Research" in result.output

    @patch("ira.interfaces.cli._build_pantheon")
    def test_email_draft_produces_output(self, mock_build, runner, cli_app):
        mock_calliope = AsyncMock()
        mock_calliope.handle = AsyncMock(return_value="Dear Client, here is your follow-up.")

        mock_pantheon = MagicMock()
        mock_pantheon.get_agent = MagicMock(return_value=mock_calliope)
        mock_pantheon.start = AsyncMock()
        mock_pantheon.stop = AsyncMock()
        mock_pantheon.__aenter__ = AsyncMock(return_value=mock_pantheon)
        mock_pantheon.__aexit__ = AsyncMock(return_value=False)
        mock_build.return_value = mock_pantheon

        result = runner.invoke(cli_app, [
            "email", "draft",
            "--to", "client@example.com",
            "--subject", "Follow-up",
            "--context", "Draft a follow-up about PF1-C pricing",
        ])
        assert result.exit_code == 0
        assert "client@example.com" in result.output
        assert "Follow-up" in result.output
        assert "Dear Client" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Graduate
# ═══════════════════════════════════════════════════════════════════════════════


class TestCLIGraduate:
    """Test the ``ira graduate`` command with mocked CRM and file I/O."""

    @pytest.fixture()
    def runner(self):
        from typer.testing import CliRunner
        return CliRunner()

    @pytest.fixture()
    def cli_app(self):
        from ira.interfaces.cli import app
        return app

    @patch("ira.interfaces.cli.subprocess.run")
    @patch("ira.interfaces.cli._update_env_file")
    def test_graduate_passes_when_thresholds_met(
        self, mock_env, mock_subproc, runner, cli_app,
    ):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=2000)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=15)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = 5.0

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert result.exit_code == 0
        assert "Graduation successful" in result.output
        mock_env.assert_called_once_with({
            "IRA_EMAIL_MODE": "OPERATIONAL",
            "IRA_EMAIL": "ira@machinecraft.org",
        })
        assert mock_subproc.call_count == 2

    def test_graduate_fails_when_interactions_too_low(self, runner, cli_app):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=500)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=15)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = 5.0

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert result.exit_code == 1
        assert "Graduation blocked" in result.output

    def test_graduate_fails_when_avg_score_too_low(self, runner, cli_app):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=2000)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=15)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = 3.0

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_graduate_fails_when_no_feedback(self, runner, cli_app):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=2000)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=15)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = None

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert result.exit_code == 1

    def test_graduate_fails_when_procedures_too_few(self, runner, cli_app):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=2000)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=3)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = 5.0

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert result.exit_code == 1
        assert "Graduation blocked" in result.output

    def test_graduate_shows_assessment_table(self, runner, cli_app):
        mock_crm = AsyncMock()
        mock_crm.create_tables = AsyncMock()
        mock_crm.count_interactions = AsyncMock(return_value=500)

        mock_procedural = AsyncMock()
        mock_procedural.initialize = AsyncMock()
        mock_procedural.count_procedures = AsyncMock(return_value=5)
        mock_procedural.close = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.get_average_score.return_value = 3.2

        with (
            patch("ira.data.crm.CRMDatabase", return_value=mock_crm),
            patch("ira.memory.procedural.ProceduralMemory", return_value=mock_procedural),
            patch("ira.systems.learning_hub.LearningHub", return_value=mock_hub),
        ):
            result = runner.invoke(cli_app, ["graduate"])

        assert "Total interactions" in result.output
        assert "Avg feedback score" in result.output
        assert "Procedures learned" in result.output
        assert "500" in result.output
        assert "3.20" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Server
# ═══════════════════════════════════════════════════════════════════════════════


class TestServerEndpoints:
    """Test FastAPI endpoints by injecting mocks into the service registry."""

    @pytest.fixture()
    def server_app(self):
        from ira.interfaces.server import app, _services
        _services.clear()
        yield app, _services
        _services.clear()

    @pytest.fixture()
    def mock_pantheon(self):
        p = MagicMock()
        p.process = AsyncMock(return_value="Athena says hello")
        agent = MagicMock()
        agent.name = "athena"
        agent.role = "CEO"
        agent.description = "Orchestrator"
        p.agents = {"athena": agent}
        calliope = AsyncMock()
        calliope.handle = AsyncMock(return_value="Draft body text")
        p.get_agent = MagicMock(return_value=calliope)
        return p

    async def test_post_query(self, server_app, mock_pantheon):
        app, services = server_app
        services["pantheon"] = mock_pantheon

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query", json={"query": "Hello Ira"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Athena says hello"

    async def test_get_health(self, server_app):
        app, services = server_app
        immune = AsyncMock()
        immune.run_startup_validation = AsyncMock(return_value={
            "qdrant": {"status": "healthy"},
            "neo4j": {"status": "healthy"},
        })
        services["immune"] = immune

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "qdrant" in data["services"]

    async def test_get_agents(self, server_app, mock_pantheon):
        app, services = server_app
        services["pantheon"] = mock_pantheon

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["agents"][0]["name"] == "athena"

    async def test_get_pipeline(self, server_app):
        app, services = server_app
        crm = AsyncMock()
        crm.get_pipeline_summary = AsyncMock(return_value={"total_deals": 5, "total_value": 100000})
        services["crm"] = crm

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/pipeline")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline"]["total_deals"] == 5

    async def test_post_email_draft(self, server_app, mock_pantheon):
        app, services = server_app
        services["pantheon"] = mock_pantheon

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/email/draft", json={
                "to": "client@example.com",
                "subject": "Follow-up",
                "context": "Draft a follow-up email",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["to"] == "client@example.com"
        assert data["subject"] == "Follow-up"
        assert data["body"] == "Draft body text"

    async def test_query_returns_503_when_service_missing(self, server_app):
        app, services = server_app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query", json={"query": "hello"})

        assert resp.status_code == 500

    async def test_query_with_user_id_records_context(self, server_app, mock_pantheon):
        from ira.context import UnifiedContextManager

        app, services = server_app
        services["pantheon"] = mock_pantheon
        uctx = UnifiedContextManager()
        services["unified_context"] = uctx

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/query",
                json={"query": "Hello Ira", "user_id": "alice@test.com"},
            )

        assert resp.status_code == 200
        history = uctx.recent_history("alice@test.com")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello Ira"

    async def test_query_without_user_id_skips_context(self, server_app, mock_pantheon):
        from ira.context import UnifiedContextManager

        app, services = server_app
        services["pantheon"] = mock_pantheon
        uctx = UnifiedContextManager()
        services["unified_context"] = uctx

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query", json={"query": "Hello"})

        assert resp.status_code == 200
        assert uctx.all_users() == []


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard
# ═══════════════════════════════════════════════════════════════════════════════


class TestDashboardEndpoint:
    """Test the /dashboard/ HTML endpoint."""

    @pytest.fixture()
    def server_app(self):
        from ira.interfaces.server import app, _services
        _services.clear()
        yield app, _services
        _services.clear()

    async def test_dashboard_returns_html(self, server_app):
        app, services = server_app

        ix1 = SimpleNamespace(
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            content='{"route": "deterministic", "agents": ["prometheus"]}',
        )
        ix2 = SimpleNamespace(
            created_at=datetime(2025, 6, 2, tzinfo=timezone.utc),
            content='{"route": "llm", "agents": ["athena"]}',
        )

        crm = AsyncMock()
        crm.list_interactions = AsyncMock(return_value=[ix1, ix2])
        crm.get_pipeline_summary = AsyncMock(return_value={
            "stages": {
                "NEW": {"count": 3, "total_value": 5000},
                "QUALIFIED": {"count": 2, "total_value": 20000},
                "WON": {"count": 1, "total_value": 50000},
            },
        })
        crm.list_campaigns = AsyncMock(return_value=[SimpleNamespace(name="EU")])

        learning_hub = MagicMock()
        learning_hub.get_all_feedback.return_value = []

        services["crm"] = crm
        services["learning_hub"] = learning_hub

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        assert "Ira" in body
        assert "Chart" in body or "chart" in body.lower()

    async def test_dashboard_metrics_computed(self, server_app):
        app, services = server_app

        ix = SimpleNamespace(
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
            content='{"route": "deterministic"}',
        )

        crm = AsyncMock()
        crm.list_interactions = AsyncMock(return_value=[ix, ix, ix])
        crm.get_pipeline_summary = AsyncMock(return_value={
            "stages": {"QUALIFIED": {"count": 5, "total_value": 100000}},
        })
        crm.list_campaigns = AsyncMock(return_value=[])

        from ira.systems.learning_hub import FeedbackRecord

        fb = FeedbackRecord(interaction_id="i1", feedback_score=8)
        learning_hub = MagicMock()
        learning_hub.get_all_feedback.return_value = [fb]

        services["crm"] = crm
        services["learning_hub"] = learning_hub

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/")

        assert resp.status_code == 200
        body = resp.text
        assert "3" in body  # total_interactions
        assert "5" in body  # leads_qualified
        assert "8" in body  # avg_feedback (8.0)

    async def test_dashboard_empty_data(self, server_app):
        app, services = server_app

        crm = AsyncMock()
        crm.list_interactions = AsyncMock(return_value=[])
        crm.get_pipeline_summary = AsyncMock(return_value={"stages": {}})
        crm.list_campaigns = AsyncMock(return_value=[])

        learning_hub = MagicMock()
        learning_hub.get_all_feedback.return_value = []

        services["crm"] = crm
        services["learning_hub"] = learning_hub

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/")

        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Bot — inline keyboards and campaign commands
# ═══════════════════════════════════════════════════════════════════════════════


class TestTelegramCallbacks:
    """Test Telegram inline keyboard callbacks and campaign commands."""

    @pytest.fixture(autouse=True)
    def _inject_services(self):
        import ira.interfaces.telegram_bot as tg

        self._tg = tg
        self._orig_pantheon = tg._pantheon
        self._orig_bm = tg._board_meeting
        self._orig_crm = tg._crm
        self._orig_uctx = tg._unified_context

        tg._pantheon = MagicMock()
        tg._board_meeting = AsyncMock()
        tg._crm = AsyncMock()
        tg._unified_context = None

        yield

        tg._pantheon = self._orig_pantheon
        tg._board_meeting = self._orig_bm
        tg._crm = self._orig_crm
        tg._unified_context = self._orig_uctx

    def _make_update(self, text: str = "", chat_id: int = 42, args: list | None = None):
        """Build a minimal mock Update for command handlers."""
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.chat_id = chat_id
        update.effective_message.text = text
        update.effective_message.reply_text = AsyncMock()

        ctx = MagicMock()
        ctx.args = args
        return update, ctx

    def _make_callback_update(self, data: str, chat_id: int = 42):
        """Build a minimal mock Update for CallbackQueryHandler."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.chat_id = chat_id

        ctx = MagicMock()
        return update, ctx

    # ── Draft approve / reject ────────────────────────────────────────

    async def test_draft_approve_with_cached_draft(self):
        self._tg._pending_drafts[42] = {"context": "test", "body": "Draft body"}

        update, ctx = self._make_callback_update("draft_approve", chat_id=42)
        await self._tg.on_draft_callback(update, ctx)

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "approved" in text.lower()
        assert "Draft body" in text
        assert 42 not in self._tg._pending_drafts

    async def test_draft_approve_without_cached_draft(self):
        update, ctx = self._make_callback_update("draft_approve", chat_id=99)
        await self._tg.on_draft_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "approved" in text.lower()

    async def test_draft_reject(self):
        self._tg._pending_drafts[42] = {"context": "test", "body": "Draft body"}

        update, ctx = self._make_callback_update("draft_reject", chat_id=42)
        await self._tg.on_draft_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "rejected" in text.lower()

    # ── /campaign start ───────────────────────────────────────────────

    async def test_campaign_start_missing_args(self):
        update, ctx = self._make_update(args=["start"])
        await self._tg.cmd_campaign(update, ctx)

        reply = update.effective_message.reply_text
        reply.assert_awaited()
        assert "Usage" in reply.call_args[0][0]

    async def test_campaign_start_contact_not_found(self):
        hermes = AsyncMock()
        hermes.handle = AsyncMock(return_value="plan")
        self._tg._pantheon.get_agent = MagicMock(return_value=hermes)
        self._tg._crm.get_contact_by_email = AsyncMock(return_value=None)

        update, ctx = self._make_update(args=["start", "TestCampaign", "nobody@test.com"])
        await self._tg.cmd_campaign(update, ctx)

        calls = update.effective_message.reply_text.call_args_list
        texts = [c[0][0] for c in calls]
        assert any("not found" in t.lower() for t in texts)

    async def test_campaign_start_success(self):
        hermes = AsyncMock()
        hermes.handle = AsyncMock(return_value="3-step campaign plan")
        self._tg._pantheon.get_agent = MagicMock(return_value=hermes)

        contact = MagicMock()
        contact.name = "Alice"
        contact.lead_score = 75.0
        contact.company_id = "comp-1"
        self._tg._crm.get_contact_by_email = AsyncMock(return_value=contact)

        update, ctx = self._make_update(args=["start", "EULaunch", "alice@test.com"])
        await self._tg.cmd_campaign(update, ctx)

        hermes.handle.assert_awaited_once()
        calls = update.effective_message.reply_text.call_args_list
        texts = " ".join(c[0][0] for c in calls)
        assert "Campaign Plan" in texts

    # ── /campaign status ──────────────────────────────────────────────

    async def test_campaign_status_not_found(self):
        hermes = AsyncMock()
        self._tg._pantheon.get_agent = MagicMock(return_value=hermes)
        self._tg._crm.list_campaigns = AsyncMock(return_value=[])

        update, ctx = self._make_update(args=["status", "NoSuchCampaign"])
        await self._tg.cmd_campaign(update, ctx)

        calls = update.effective_message.reply_text.call_args_list
        texts = [c[0][0] for c in calls]
        assert any("not found" in t.lower() or "No campaign" in t for t in texts)

    async def test_campaign_status_success(self):
        hermes = AsyncMock()
        hermes.handle = AsyncMock(return_value="Campaign is performing well.")
        self._tg._pantheon.get_agent = MagicMock(return_value=hermes)

        campaign = MagicMock()
        campaign.name = "EULaunch"
        campaign.id = "camp-1"
        campaign.status = MagicMock(value="ACTIVE")
        self._tg._crm.list_campaigns = AsyncMock(return_value=[campaign])

        step = MagicMock()
        step.sent_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
        step.reply_received = False
        self._tg._crm.list_drip_steps = AsyncMock(return_value=[step])

        update, ctx = self._make_update(args=["status", "EULaunch"])
        await self._tg.cmd_campaign(update, ctx)

        calls = update.effective_message.reply_text.call_args_list
        texts = " ".join(c[0][0] for c in calls)
        assert "EULaunch" in texts
        assert "1 sent" in texts

    # ── /campaign unknown sub-command ─────────────────────────────────

    async def test_campaign_unknown_subcommand(self):
        hermes = AsyncMock()
        self._tg._pantheon.get_agent = MagicMock(return_value=hermes)

        update, ctx = self._make_update(args=["delete", "SomeCampaign"])
        await self._tg.cmd_campaign(update, ctx)

        text = update.effective_message.reply_text.call_args[0][0]
        assert "Unknown" in text

    # ── /board ────────────────────────────────────────────────────────

    async def test_board_returns_minutes(self):
        minutes = SimpleNamespace(
            topic="Q3 Strategy",
            participants=["athena", "prometheus"],
            contributions={"prometheus": "Revenue is up."},
            synthesis="We should expand.",
            action_items=["Hire more reps"],
        )
        self._tg._board_meeting.run_meeting = AsyncMock(return_value=minutes)

        update, ctx = self._make_update(args=["Q3", "Strategy"])
        await self._tg.cmd_board(update, ctx)

        calls = update.effective_message.reply_text.call_args_list
        texts = " ".join(c[0][0] for c in calls)
        assert "Board Meeting" in texts
        assert "prometheus" in texts
        assert "expand" in texts

    async def test_board_no_topic(self):
        update, ctx = self._make_update(args=[])
        await self._tg.cmd_board(update, ctx)

        text = update.effective_message.reply_text.call_args[0][0]
        assert "Usage" in text


# ═══════════════════════════════════════════════════════════════════════════════
# RequestPipeline — full 11-step end-to-end
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequestPipeline:
    """End-to-end pipeline tests with fully mocked subsystems."""

    @pytest.fixture()
    def mock_sensory(self):
        s = AsyncMock()
        s.perceive = AsyncMock(return_value={
            "resolved_contact": {
                "name": "Alice",
                "email": "alice@example.com",
                "company": "Acme",
                "region": "EU",
                "score": 75.0,
            },
            "emotional_state": {"state": "NEUTRAL", "confidence": 0.5},
            "conversation_history": [],
            "relationship": {"warmth": "STRANGER"},
            "channel_context": {"channel": "TELEGRAM", "sender_id": "alice_tg", "metadata": {}},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return s

    @pytest.fixture()
    def mock_conversation(self):
        c = AsyncMock()
        c.get_history = AsyncMock(return_value=[])
        c.resolve_coreferences = AsyncMock(side_effect=lambda msg, _: msg)
        c.add_message = AsyncMock()
        return c

    @pytest.fixture()
    def mock_pantheon(self):
        router = MagicMock()
        router.route = MagicMock(return_value=None)

        sophia = AsyncMock()
        sophia.handle = AsyncMock(return_value="reflection noted")

        p = MagicMock()
        p._router = router
        p._retriever = AsyncMock()
        p._retriever.search = AsyncMock(return_value=[])
        p.process = AsyncMock(return_value="Raw agent response")
        p.get_agent = MagicMock(return_value=sophia)
        return p

    @pytest.fixture()
    def mock_voice(self):
        v = AsyncMock()
        v.shape_response = AsyncMock(return_value="Shaped response for channel")
        return v

    @pytest.fixture()
    def pipeline(self, mock_sensory, mock_conversation, mock_pantheon, mock_voice):
        from ira.pipeline import RequestPipeline
        return RequestPipeline(
            sensory=mock_sensory,
            conversation_memory=mock_conversation,
            pantheon=mock_pantheon,
            voice=mock_voice,
        )

    @pytest.fixture()
    def full_pipeline(self, mock_sensory, mock_conversation, mock_pantheon, mock_voice):
        from ira.pipeline import RequestPipeline

        relationship = AsyncMock()
        relationship.get_relationship = AsyncMock(return_value=SimpleNamespace(
            warmth_level=SimpleNamespace(value="FAMILIAR"),
            interaction_count=15,
        ))

        goals = AsyncMock()
        goals.get_active_goal = AsyncMock(return_value=None)
        goals.detect_goal = AsyncMock(return_value=None)

        procedural = AsyncMock()
        procedural.find_procedure = AsyncMock(return_value=None)
        procedural.learn_procedure = AsyncMock()

        metacognition = AsyncMock()
        metacognition.assess_knowledge = AsyncMock(return_value={
            "state": KnowledgeState.KNOW_VERIFIED,
            "confidence": 0.9,
            "gaps": [],
        })
        metacognition.generate_confidence_prefix = MagicMock(
            return_value="Based on our verified documentation, "
        )
        metacognition.log_knowledge_gap = AsyncMock()

        inner_voice = AsyncMock()
        inner_voice.reflect = AsyncMock(return_value={
            "reflection_type": "OBSERVATION",
            "content": "",
            "should_surface": False,
        })

        endocrine = MagicMock()
        endocrine.get_behavioral_modifiers = MagicMock(return_value={
            "response_style": "balanced",
            "verbosity": "normal",
        })
        endocrine.boost = MagicMock()

        crm = AsyncMock()
        crm.get_contact_by_email = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        crm.create_interaction = AsyncMock()

        musculoskeletal = AsyncMock()
        musculoskeletal.record_action = AsyncMock()

        return RequestPipeline(
            sensory=mock_sensory,
            conversation_memory=mock_conversation,
            relationship_memory=relationship,
            goal_manager=goals,
            procedural_memory=procedural,
            metacognition=metacognition,
            inner_voice=inner_voice,
            pantheon=mock_pantheon,
            voice=mock_voice,
            endocrine=endocrine,
            crm=crm,
            musculoskeletal=musculoskeletal,
        )

    async def test_returns_shaped_response(self, pipeline):
        result = await pipeline.process_request("Hello", "TELEGRAM", "alice_tg")
        assert result == "Shaped response for channel"

    async def test_step1_perceive_called(self, pipeline, mock_sensory):
        await pipeline.process_request("Hello", "TELEGRAM", "alice_tg")
        mock_sensory.perceive.assert_awaited_once()
        event = mock_sensory.perceive.call_args[0][0]
        assert event.raw_input == "Hello"
        assert event.channel == Channel.TELEGRAM

    async def test_step2_remember_fetches_history(self, pipeline, mock_conversation):
        await pipeline.process_request("Hello", "TELEGRAM", "alice_tg")
        mock_conversation.get_history.assert_awaited_once_with("alice@example.com", "TELEGRAM", limit=20)

    async def test_step5_llm_route_when_no_fast_match(self, pipeline, mock_pantheon):
        mock_pantheon._router.route.return_value = None
        await pipeline.process_request("Tell me something", "CLI", "user1")
        mock_pantheon.process.assert_awaited_once()

    async def test_step3_deterministic_route_bypasses_llm(self, pipeline, mock_pantheon):
        mock_pantheon._router.route.return_value = {
            "intent": "PIPELINE",
            "required_agents": ["prometheus"],
            "optional_agents": [],
            "required_tools": [],
        }
        prometheus = AsyncMock()
        prometheus.handle = AsyncMock(return_value="Pipeline data")

        def _get_agent(name: str):
            if name == "prometheus":
                return prometheus
            return None

        mock_pantheon.get_agent = MagicMock(side_effect=_get_agent)

        await pipeline.process_request("Show pipeline", "CLI", "user1")

        mock_pantheon.process.assert_not_awaited()
        prometheus.handle.assert_awaited_once()

    async def test_step9_shape_uses_channel(self, pipeline, mock_voice):
        await pipeline.process_request("Hello", "EMAIL", "user@test.com")
        call_args = mock_voice.shape_response.call_args
        assert call_args[0][1] == "EMAIL"

    async def test_step10_learn_records_conversation(self, pipeline, mock_conversation):
        await pipeline.process_request("Hello", "TELEGRAM", "alice_tg")
        calls = mock_conversation.add_message.call_args_list
        assert len(calls) == 2
        assert calls[0].args[2] == "user"
        assert calls[1].args[2] == "assistant"

    async def test_full_pipeline_all_steps_execute(self, full_pipeline):
        result = await full_pipeline.process_request(
            "What is the price of PF1-C?", "TELEGRAM", "alice_tg",
        )
        assert result == "Shaped response for channel"

        full_pipeline._sensory.perceive.assert_awaited_once()
        full_pipeline._conversation.get_history.assert_awaited_once()
        full_pipeline._relationship.get_relationship.assert_awaited_once()
        full_pipeline._goals.get_active_goal.assert_awaited_once()
        full_pipeline._pantheon.process.assert_awaited_once()
        full_pipeline._metacognition.assess_knowledge.assert_awaited_once()
        full_pipeline._inner_voice.reflect.assert_awaited_once()
        full_pipeline._voice.shape_response.assert_awaited_once()
        full_pipeline._conversation.add_message.assert_awaited()
        full_pipeline._crm.create_interaction.assert_awaited_once()
        full_pipeline._musculoskeletal.record_action.assert_awaited_once()

    async def test_full_pipeline_endocrine_feedback(self, full_pipeline):
        await full_pipeline.process_request("Hello", "CLI", "user1")
        full_pipeline._endocrine.boost.assert_called()

    async def test_full_pipeline_goal_detection_on_no_active_goal(self, full_pipeline):
        await full_pipeline.process_request("I need a quote", "EMAIL", "lead@co.com")
        full_pipeline._goals.detect_goal.assert_awaited_once()

    async def test_full_pipeline_procedural_learning(self, full_pipeline):
        await full_pipeline.process_request("Show pipeline", "CLI", "user1")
        full_pipeline._procedural.learn_procedure.assert_awaited_once()

    async def test_pipeline_with_history_resolves_coreferences(self, pipeline, mock_conversation):
        mock_conversation.get_history = AsyncMock(return_value=[
            {"role": "user", "content": "Tell me about PF1-C", "timestamp": "2025-01-01T00:00:00"},
        ])
        mock_conversation.resolve_coreferences = AsyncMock(return_value="Tell me more about PF1-C")

        await pipeline.process_request("Tell me more about it", "TELEGRAM", "alice_tg")
        mock_conversation.resolve_coreferences.assert_awaited_once()

    async def test_pipeline_optional_systems_gracefully_skipped(self):
        from ira.pipeline import RequestPipeline

        sensory = AsyncMock()
        sensory.perceive = AsyncMock(return_value={
            "resolved_contact": {"name": "Bob", "email": "bob@test.com", "company": None, "region": None, "score": 0},
            "emotional_state": {"state": "NEUTRAL", "confidence": 0.0},
            "conversation_history": [],
            "relationship": {"warmth": "STRANGER"},
            "channel_context": {"channel": "CLI", "sender_id": "bob", "metadata": {}},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        conversation = AsyncMock()
        conversation.get_history = AsyncMock(return_value=[])
        conversation.add_message = AsyncMock()

        router = MagicMock()
        router.route = MagicMock(return_value=None)
        pantheon = MagicMock()
        pantheon._router = router
        pantheon.process = AsyncMock(return_value="Minimal response")
        pantheon.get_agent = MagicMock(return_value=None)

        voice = AsyncMock()
        voice.shape_response = AsyncMock(return_value="Shaped minimal")

        pipe = RequestPipeline(
            sensory=sensory,
            conversation_memory=conversation,
            pantheon=pantheon,
            voice=voice,
        )
        result = await pipe.process_request("Hello", "CLI", "bob")
        assert result == "Shaped minimal"
