"""Tests for the Google Document AI integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.document_ai import DocumentAIError, DocumentAIService, _layout_text


class TestDocumentAIOffline:
    """When not connected, the service reports unavailable."""

    def _make_service(self) -> DocumentAIService:
        svc = DocumentAIService.__new__(DocumentAIService)
        svc._project_id = ""
        svc._location = "us"
        svc._processors = {"ocr": "", "invoice": "", "form": ""}
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


class TestDocumentAIConnected:
    """With mocked credentials, verify all operations."""

    def _make_connected_service(self) -> DocumentAIService:
        svc = DocumentAIService.__new__(DocumentAIService)
        svc._project_id = "test-project"
        svc._location = "us"
        svc._processors = {"ocr": "proc-123", "invoice": "inv-456", "form": "form-789"}
        svc._creds_path = MagicMock()
        svc._token_path = MagicMock()
        svc._creds = MagicMock()
        svc._creds.token = "fake-token"
        svc._creds.valid = True
        return svc

    def test_available_is_true(self):
        svc = self._make_connected_service()
        assert svc.available is True

    def test_endpoint(self):
        svc = self._make_connected_service()
        url = svc._endpoint()
        assert "test-project" in url
        assert "proc-123" in url
        assert "us-documentai" in url

    @patch("ira.systems.document_ai.httpx.AsyncClient")
    async def test_parse_document(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "document": {"text": "Hello World", "pages": []}
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await svc.parse_document(b"fake-pdf-bytes")
        assert result["document"]["text"] == "Hello World"

    @patch("ira.systems.document_ai.httpx.AsyncClient")
    async def test_extract_text(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "document": {"text": "Extracted OCR text"}
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        text = await svc.extract_text(b"fake-pdf")
        assert text == "Extracted OCR text"

    @patch("ira.systems.document_ai.httpx.AsyncClient")
    async def test_extract_entities(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "document": {
                "text": "Invoice",
                "entities": [
                    {
                        "type": "invoice_number",
                        "mentionText": "INV-001",
                        "confidence": 0.98,
                        "normalizedValue": {},
                    }
                ],
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        entities = await svc.extract_entities(b"fake-pdf")
        assert len(entities) == 1
        assert entities[0]["type"] == "invoice_number"
        assert entities[0]["mention_text"] == "INV-001"

    async def test_health_check_connected(self):
        svc = self._make_connected_service()
        result = await svc.health_check()
        assert result["status"] == "connected"
        assert result["project"] == "test-project"

    @patch("ira.systems.document_ai.httpx.AsyncClient")
    async def test_parse_document_error(self, mock_client_cls):
        svc = self._make_connected_service()

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("API error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(DocumentAIError, match="Document AI request failed"):
            await svc.parse_document(b"bad-bytes")


class TestLayoutText:
    """Unit tests for the _layout_text helper."""

    def test_extract_from_segments(self):
        full_text = "Hello World from Document AI"
        layout = {
            "textAnchor": {
                "textSegments": [
                    {"startIndex": 0, "endIndex": 5},
                    {"startIndex": 6, "endIndex": 11},
                ]
            }
        }
        assert _layout_text(layout, full_text) == "HelloWorld"

    def test_empty_segments(self):
        assert _layout_text({}, "some text") == ""

    def test_no_text_anchor(self):
        assert _layout_text({"textAnchor": {}}, "some text") == ""
