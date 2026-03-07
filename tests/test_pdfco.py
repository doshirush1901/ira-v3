"""Tests for the PDF.co integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.pdfco import PdfCoError, PdfCoService


class TestPdfCoOffline:
    """When API key is not set, service reports unavailable."""

    def _make_service(self) -> PdfCoService:
        svc = PdfCoService.__new__(PdfCoService)
        svc._api_key = ""
        return svc

    def test_available_is_false(self):
        svc = self._make_service()
        assert svc.available is False

    async def test_html_to_pdf_raises_when_not_configured(self):
        svc = self._make_service()
        with pytest.raises(PdfCoError, match="not configured"):
            await svc.html_to_pdf("<h1>Test</h1>")

    async def test_extract_text_raises_when_not_configured(self):
        svc = self._make_service()
        with pytest.raises(PdfCoError, match="not configured"):
            await svc.extract_text(b"fake")

    async def test_health_check_not_configured(self):
        svc = self._make_service()
        result = await svc.health_check()
        assert result["status"] == "not_configured"


class TestPdfCoConnected:
    """With mocked API, verify all operations."""

    def _make_service(self) -> PdfCoService:
        svc = PdfCoService.__new__(PdfCoService)
        svc._api_key = "test-api-key"
        return svc

    def test_available_is_true(self):
        svc = self._make_service()
        assert svc.available is True

    @patch("ira.systems.pdfco.httpx.AsyncClient")
    async def test_html_to_pdf(self, mock_client_cls):
        svc = self._make_service()

        mock_convert_resp = MagicMock()
        mock_convert_resp.raise_for_status = MagicMock()
        mock_convert_resp.json.return_value = {
            "error": False,
            "url": "https://pdf.co/output/test.pdf",
        }

        mock_pdf_resp = MagicMock()
        mock_pdf_resp.raise_for_status = MagicMock()
        mock_pdf_resp.content = b"%PDF-1.4 fake content"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_convert_resp
        mock_client.get.return_value = mock_pdf_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        pdf_bytes = await svc.html_to_pdf("<h1>Quote</h1>")
        assert pdf_bytes == b"%PDF-1.4 fake content"

    @patch("ira.systems.pdfco.httpx.AsyncClient")
    async def test_html_to_pdf_api_error(self, mock_client_cls):
        svc = self._make_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "error": True,
            "message": "Invalid HTML",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(PdfCoError, match="Invalid HTML"):
            await svc.html_to_pdf("<bad>")

    @patch("ira.systems.pdfco.httpx.AsyncClient")
    async def test_extract_text_from_url(self, mock_client_cls):
        svc = self._make_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "error": False,
            "body": "Extracted text from PDF",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        text = await svc.extract_text(file_url="https://example.com/doc.pdf")
        assert text == "Extracted text from PDF"

    async def test_extract_text_no_input_raises(self):
        svc = self._make_service()
        with pytest.raises(PdfCoError, match="Either file_bytes or file_url"):
            await svc.extract_text()

    @patch("ira.systems.pdfco.httpx.AsyncClient")
    async def test_extract_tables_csv(self, mock_client_cls):
        svc = self._make_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "error": False,
            "body": "col1,col2\nval1,val2",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        csv_text = await svc.extract_tables_csv(file_url="https://example.com/doc.pdf")
        assert "col1" in csv_text

    @patch("ira.systems.pdfco.httpx.AsyncClient")
    async def test_health_check_connected(self, mock_client_cls):
        svc = self._make_service()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"remainingCredits": 9500}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await svc.health_check()
        assert result["status"] == "connected"
        assert result["credits_remaining"] == 9500
