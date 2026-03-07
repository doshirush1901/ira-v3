"""Tests for the Google Docs/Drive integration — GoogleDocsService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.systems.google_docs import GoogleDocsError, GoogleDocsService, _extract_text


# ═════════════════════════════════════════════════════════════════════════
# GoogleDocsService — offline mode (not connected)
# ═════════════════════════════════════════════════════════════════════════


class TestGoogleDocsOffline:
    """When not connected, the service reports unavailable."""

    def _make_service(self) -> GoogleDocsService:
        svc = GoogleDocsService.__new__(GoogleDocsService)
        svc._creds_path = MagicMock()
        svc._token_path = MagicMock()
        svc._docs_service = None
        svc._drive_service = None
        return svc

    def test_available_is_false(self):
        svc = self._make_service()
        assert svc.available is False

    async def test_health_check_disconnected(self):
        svc = self._make_service()
        result = await svc.health_check()
        assert result["status"] == "disconnected"
        assert result["available"] is False

    async def test_close_when_not_connected(self):
        svc = self._make_service()
        await svc.close()
        assert svc.available is False


# ═════════════════════════════════════════════════════════════════════════
# GoogleDocsService — connected (mocked services)
# ═════════════════════════════════════════════════════════════════════════


class TestGoogleDocsConnected:
    """With mocked Google API services, verify all operations."""

    def _make_connected_service(self) -> GoogleDocsService:
        svc = GoogleDocsService.__new__(GoogleDocsService)
        svc._creds_path = MagicMock()
        svc._token_path = MagicMock()
        svc._docs_service = MagicMock()
        svc._drive_service = MagicMock()
        return svc

    def test_available_is_true(self):
        svc = self._make_connected_service()
        assert svc.available is True

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_get_document(self, mock_to_thread):
        svc = self._make_connected_service()
        fake_doc = {"documentId": "abc123", "title": "Test", "body": {"content": []}}
        mock_to_thread.return_value = fake_doc

        result = await svc.get_document("abc123")
        assert result["documentId"] == "abc123"
        mock_to_thread.assert_called_once()

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_read_document_text(self, mock_to_thread):
        svc = self._make_connected_service()
        fake_doc = {
            "documentId": "abc123",
            "title": "Test",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Hello "}},
                                {"textRun": {"content": "World"}},
                            ]
                        }
                    }
                ]
            },
        }
        mock_to_thread.return_value = fake_doc

        result = await svc.read_document_text("abc123")
        assert result == "Hello World"

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_create_document(self, mock_to_thread):
        svc = self._make_connected_service()
        fake_doc = {"documentId": "new123", "title": "New Doc", "body": {"content": []}}
        mock_to_thread.return_value = fake_doc

        result = await svc.create_document("New Doc")
        assert result["documentId"] == "new123"

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_create_document_with_body(self, mock_to_thread):
        svc = self._make_connected_service()
        fake_doc = {"documentId": "new123", "title": "New Doc", "body": {"content": []}}
        mock_to_thread.side_effect = [fake_doc, None, fake_doc]

        result = await svc.create_document("New Doc", body_text="Hello")
        assert result["documentId"] == "new123"
        assert mock_to_thread.call_count == 3

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_append_text(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = None

        await svc.append_text("abc123", "new text")
        mock_to_thread.assert_called_once()

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_replace_text(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = None

        await svc.replace_text("abc123", "old", "new")
        mock_to_thread.assert_called_once()

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_insert_text(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = None

        await svc.insert_text("abc123", "inserted", index=5)
        mock_to_thread.assert_called_once()

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_search_files(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = [
            {"id": "f1", "name": "Report.docx", "mimeType": "application/vnd.google-apps.document"},
        ]

        results = await svc.search_files("name contains 'Report'")
        assert len(results) == 1
        assert results[0]["id"] == "f1"

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_search_docs(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = [
            {"id": "d1", "name": "Quote Doc"},
        ]

        results = await svc.search_docs("Quote")
        assert len(results) == 1

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_list_folder(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = [
            {"id": "f1", "name": "File1"},
            {"id": "f2", "name": "File2"},
        ]

        results = await svc.list_folder("folder_abc")
        assert len(results) == 2

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_get_file_metadata(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = {
            "id": "f1", "name": "Test", "mimeType": "text/plain",
        }

        result = await svc.get_file_metadata("f1")
        assert result["name"] == "Test"

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_health_check_connected(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.return_value = {
            "user": {"displayName": "Ira", "emailAddress": "ira@machinecraft.org"},
        }

        result = await svc.health_check()
        assert result["status"] == "connected"
        assert result["available"] is True
        assert result["user"] == "Ira"

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_health_check_error(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.side_effect = Exception("API down")

        result = await svc.health_check()
        assert result["status"] == "error"
        assert result["available"] is False

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_get_document_error_raises(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.side_effect = Exception("Not found")

        with pytest.raises(GoogleDocsError, match="Failed to get document"):
            await svc.get_document("bad_id")

    @patch("ira.systems.google_docs.asyncio.to_thread")
    async def test_search_files_error_raises(self, mock_to_thread):
        svc = self._make_connected_service()
        mock_to_thread.side_effect = Exception("Drive error")

        with pytest.raises(GoogleDocsError, match="Drive search failed"):
            await svc.search_files("query")


# ═════════════════════════════════════════════════════════════════════════
# _extract_text helper
# ═════════════════════════════════════════════════════════════════════════


class TestExtractText:
    """Unit tests for the text extraction helper."""

    def test_empty_doc(self):
        assert _extract_text({"body": {"content": []}}) == ""

    def test_single_paragraph(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Hello World\n"}},
                            ]
                        }
                    }
                ]
            }
        }
        assert _extract_text(doc) == "Hello World\n"

    def test_multiple_paragraphs(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Line 1\n"}},
                            ]
                        }
                    },
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Line 2\n"}},
                            ]
                        }
                    },
                ]
            }
        }
        assert _extract_text(doc) == "Line 1\nLine 2\n"

    def test_mixed_elements(self):
        doc = {
            "body": {
                "content": [
                    {"sectionBreak": {}},
                    {
                        "paragraph": {
                            "elements": [
                                {"textRun": {"content": "Text"}},
                                {"inlineObjectElement": {"inlineObjectId": "img1"}},
                            ]
                        }
                    },
                ]
            }
        }
        assert _extract_text(doc) == "Text"

    def test_no_body(self):
        assert _extract_text({}) == ""
