"""Tests for the Google Cloud DLP integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.dlp import DlpError, DlpService


class TestDlpOffline:
    """When not connected, the service reports unavailable."""

    def _make_service(self) -> DlpService:
        svc = DlpService.__new__(DlpService)
        svc._project_id = ""
        svc._creds_path = MagicMock()
        svc._token_path = MagicMock()
        svc._creds = None
        return svc

    def test_available_is_false(self):
        svc = self._make_service()
        assert svc.available is False

    def test_configured_is_false(self):
        svc = self._make_service()
        assert svc.configured is False

    async def test_health_check_not_configured(self):
        svc = self._make_service()
        result = await svc.health_check()
        assert result["status"] == "not_configured"

    async def test_close_when_not_connected(self):
        svc = self._make_service()
        await svc.close()
        assert svc.available is False


class TestDlpConnected:
    """With mocked credentials, verify all operations."""

    def _make_connected_service(self) -> DlpService:
        svc = DlpService.__new__(DlpService)
        svc._project_id = "test-project"
        svc._creds_path = MagicMock()
        svc._token_path = MagicMock()
        svc._creds = MagicMock()
        svc._creds.token = "fake-token"
        svc._creds.valid = True
        return svc

    def test_available_is_true(self):
        svc = self._make_connected_service()
        assert svc.available is True

    @patch("ira.systems.dlp.httpx.AsyncClient")
    async def test_inspect_text(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "findings": [
                    {
                        "infoType": {"name": "EMAIL_ADDRESS"},
                        "likelihood": "VERY_LIKELY",
                        "quote": "test@example.com",
                        "location": {"codepointRange": {"start": 10, "end": 26}},
                    },
                    {
                        "infoType": {"name": "PHONE_NUMBER"},
                        "likelihood": "LIKELY",
                        "quote": "+91-9876543210",
                        "location": {"codepointRange": {"start": 30, "end": 45}},
                    },
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        findings = await svc.inspect_text("Contact test@example.com or +91-9876543210")
        assert len(findings) == 2
        assert findings[0]["info_type"] == "EMAIL_ADDRESS"
        assert findings[1]["info_type"] == "PHONE_NUMBER"

    @patch("ira.systems.dlp.httpx.AsyncClient")
    async def test_inspect_text_no_findings(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": {"findings": []}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        findings = await svc.inspect_text("No PII here")
        assert findings == []

    @patch("ira.systems.dlp.httpx.AsyncClient")
    async def test_deidentify_text(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "item": {"value": "Contact ****************** for details"}
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        redacted = await svc.deidentify_text("Contact test@example.com for details")
        assert "test@example.com" not in redacted
        assert "***" in redacted

    @patch("ira.systems.dlp.httpx.AsyncClient")
    async def test_inspect_and_report(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "findings": [
                    {
                        "infoType": {"name": "EMAIL_ADDRESS"},
                        "likelihood": "VERY_LIKELY",
                        "quote": "a@b.com",
                        "location": {"codepointRange": {"start": 0, "end": 7}},
                    },
                    {
                        "infoType": {"name": "EMAIL_ADDRESS"},
                        "likelihood": "LIKELY",
                        "quote": "c@d.com",
                        "location": {"codepointRange": {"start": 10, "end": 17}},
                    },
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        report = await svc.inspect_and_report("a@b.com and c@d.com")
        assert report["total_findings"] == 2
        assert report["has_pii"] is True
        assert report["findings_by_type"]["EMAIL_ADDRESS"] == 2

    async def test_health_check_connected(self):
        svc = self._make_connected_service()
        result = await svc.health_check()
        assert result["status"] == "connected"
        assert result["project"] == "test-project"

    @patch("ira.systems.dlp.httpx.AsyncClient")
    async def test_inspect_error_raises(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("API error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(DlpError, match="DLP inspect failed"):
            await svc.inspect_text("test")
