"""Tests for ingestion gatekeeper and imports fallback retriever.

Validates:
  - run_ingestion_cycle close() calls (Neo4j connection leak fix)
  - scan_for_undigested filtering and sorting
  - extract_file_text path traversal guard
  - deferred ingestion queue round-trip
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.exceptions import PathTraversalError


# ── Ingestion Gatekeeper: run_ingestion_cycle ────────────────────────────


class TestRunIngestionCycle:
    """Verify that shared services are always closed, even on error."""

    @pytest.fixture()
    def _mock_services(self):
        """Patch the lazy imports inside run_ingestion_cycle.

        The function uses local imports (``from ira.brain.embeddings import ...``)
        so we must patch at the *source* module, not at the gatekeeper module.
        """
        mock_qdrant = MagicMock()
        mock_qdrant.close = AsyncMock()

        mock_graph = MagicMock()
        mock_graph.close = AsyncMock()

        mock_ingestor = MagicMock()
        mock_ingestor.close = MagicMock()

        mock_digestive = MagicMock()
        mock_digestive.ingest = AsyncMock(return_value={"chunks_created": 3})

        mock_settings = MagicMock()
        mock_settings.qdrant.collection = "test_collection"

        with patch("ira.brain.ingestion_gatekeeper.scan_for_undigested", new_callable=AsyncMock) as scan, \
             patch.dict("sys.modules", {
                 "ira.brain.document_ingestor": MagicMock(
                     DocumentIngestor=MagicMock(return_value=mock_ingestor),
                     _READERS={".txt": lambda p: "sample text content"},
                 ),
                 "ira.brain.embeddings": MagicMock(
                     EmbeddingService=MagicMock(),
                 ),
                 "ira.brain.qdrant_manager": MagicMock(
                     QdrantManager=MagicMock(return_value=mock_qdrant),
                 ),
                 "ira.brain.knowledge_graph": MagicMock(
                     KnowledgeGraph=MagicMock(return_value=mock_graph),
                 ),
                 "ira.config": MagicMock(
                     get_settings=MagicMock(return_value=mock_settings),
                 ),
                 "ira.systems.digestive": MagicMock(
                     DigestiveSystem=MagicMock(return_value=mock_digestive),
                 ),
             }), \
             patch("ira.brain.ingestion_gatekeeper.load_log", new_callable=AsyncMock, return_value={}) as load_log, \
             patch("ira.brain.ingestion_gatekeeper.save_log", new_callable=AsyncMock) as save_log, \
             patch("ira.brain.ingestion_gatekeeper.record_ingestion"):
            yield {
                "scan": scan,
                "qdrant": mock_qdrant,
                "graph": mock_graph,
                "ingestor": mock_ingestor,
                "digestive": mock_digestive,
                "load_log": load_log,
                "save_log": save_log,
            }

    @staticmethod
    def _make_queue(count: int = 1) -> list[dict]:
        return [
            {
                "rel_path": f"docs/f{i}.txt",
                "path": f"/tmp/f{i}.txt",
                "hash": f"h{i}",
                "reason": "new",
                "category": "other",
                "extension": ".txt",
                "name": f"f{i}.txt",
                "size_kb": 1,
            }
            for i in range(count)
        ]

    async def test_all_three_close_calls_on_success(self, _mock_services):
        """qdrant.close(), graph.close(), ingestor.close() all called on happy path."""
        from ira.brain.ingestion_gatekeeper import run_ingestion_cycle

        svc = _mock_services
        svc["scan"].return_value = self._make_queue(1)

        result = await run_ingestion_cycle(batch_size=10, concurrency=1)

        svc["qdrant"].close.assert_awaited_once()
        svc["graph"].close.assert_awaited_once()
        svc["ingestor"].close.assert_called_once()
        assert result["files_processed"] == 1

    async def test_close_calls_happen_on_digest_error(self, _mock_services):
        """All close() calls fire even when digestive.ingest() raises."""
        from ira.brain.ingestion_gatekeeper import run_ingestion_cycle

        svc = _mock_services
        svc["scan"].return_value = self._make_queue(1)
        svc["digestive"].ingest = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        result = await run_ingestion_cycle(batch_size=10, concurrency=1)

        svc["qdrant"].close.assert_awaited_once()
        svc["graph"].close.assert_awaited_once()
        svc["ingestor"].close.assert_called_once()
        assert result["files_failed"] == 1

    async def test_close_calls_happen_on_save_log_error(self, _mock_services):
        """close() fires even when save_log raises after gather completes."""
        from ira.brain.ingestion_gatekeeper import run_ingestion_cycle

        svc = _mock_services
        svc["scan"].return_value = self._make_queue(1)
        svc["digestive"].ingest = AsyncMock(return_value={"chunks_created": 1})

        call_count = 0

        async def _save_log_bomb(log):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise OSError("disk full")

        svc["save_log"].side_effect = _save_log_bomb

        with pytest.raises(OSError, match="disk full"):
            await run_ingestion_cycle(batch_size=10, concurrency=1)

        svc["qdrant"].close.assert_awaited_once()
        svc["graph"].close.assert_awaited_once()
        svc["ingestor"].close.assert_called_once()

    async def test_empty_queue_returns_early(self, _mock_services):
        """When no files need ingestion, return immediately without creating services."""
        from ira.brain.ingestion_gatekeeper import run_ingestion_cycle

        svc = _mock_services
        svc["scan"].return_value = []

        result = await run_ingestion_cycle()
        assert result["files_processed"] == 0
        assert result["reason"] == "up_to_date"

    async def test_progress_callback_invoked(self, _mock_services):
        """The progress callback fires once per file."""
        from ira.brain.ingestion_gatekeeper import run_ingestion_cycle

        svc = _mock_services
        svc["scan"].return_value = self._make_queue(3)
        svc["digestive"].ingest = AsyncMock(return_value={"chunks_created": 2})

        progress_calls = []

        def on_progress(done, total, name, result):
            progress_calls.append((done, total, name))

        await run_ingestion_cycle(
            batch_size=10, concurrency=1, progress_callback=on_progress,
        )
        assert len(progress_calls) == 3
        assert all(t == 3 for _, t, _ in progress_calls)


# ── Ingestion Gatekeeper: scan_for_undigested ────────────────────────────


class TestScanForUndigested:
    async def test_sorts_new_before_changed(self, tmp_path: Path):
        from ira.brain.ingestion_gatekeeper import scan_for_undigested

        fa = tmp_path / "a.txt"
        fb = tmp_path / "b.txt"
        fa.write_text("a")
        fb.write_text("b")

        index = {
            "files": {
                "a.txt": {"path": str(fa), "hash": "h1", "size_kb": 1},
                "b.txt": {"path": str(fb), "hash": "h2", "size_kb": 1},
            }
        }

        def mock_needs(log, rel, h, force=False):
            return "changed" if rel == "a.txt" else "new"

        with patch("ira.brain.ingestion_gatekeeper.load_index", new_callable=AsyncMock, return_value=index), \
             patch("ira.brain.ingestion_gatekeeper.load_log", new_callable=AsyncMock, return_value={}), \
             patch("ira.brain.ingestion_gatekeeper.needs_ingestion", side_effect=mock_needs):
            result = await scan_for_undigested()

        assert result[0]["reason"] == "new"
        assert result[1]["reason"] == "changed"

    async def test_skips_missing_files(self):
        from ira.brain.ingestion_gatekeeper import scan_for_undigested

        index = {
            "files": {
                "gone.txt": {"path": "/nonexistent/gone.txt", "hash": "h1"},
            }
        }

        with patch("ira.brain.ingestion_gatekeeper.load_index", new_callable=AsyncMock, return_value=index), \
             patch("ira.brain.ingestion_gatekeeper.load_log", new_callable=AsyncMock, return_value={}):
            result = await scan_for_undigested()

        assert result == []


# ── Imports Fallback Retriever: extract_file_text ────────────────────────


class TestExtractFileText:
    async def test_valid_text_file(self, tmp_path: Path):
        content = "Hello, this is a test document with enough content to extract."
        test_file = tmp_path / "data" / "imports" / "test.txt"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(content)

        with patch("ira.brain.imports_fallback_retriever._PROJECT_ROOT", tmp_path):
            from ira.brain.imports_fallback_retriever import extract_file_text
            result = await extract_file_text(str(test_file))

        assert result == content

    async def test_path_outside_data_raises(self, tmp_path: Path):
        evil_path = tmp_path / "etc" / "passwd"
        evil_path.parent.mkdir(parents=True)
        evil_path.write_text("root:x:0:0")

        with patch("ira.brain.imports_fallback_retriever._PROJECT_ROOT", tmp_path):
            from ira.brain.imports_fallback_retriever import extract_file_text
            with pytest.raises(PathTraversalError):
                await extract_file_text(str(evil_path))

    async def test_truncates_to_max_chars(self, tmp_path: Path):
        long_content = "A" * 10_000
        test_file = tmp_path / "data" / "big.txt"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(long_content)

        with patch("ira.brain.imports_fallback_retriever._PROJECT_ROOT", tmp_path):
            from ira.brain.imports_fallback_retriever import extract_file_text
            result = await extract_file_text(str(test_file), max_chars=100)

        assert len(result) == 100

    async def test_unsupported_extension_returns_empty(self, tmp_path: Path):
        test_file = tmp_path / "data" / "image.png"
        test_file.parent.mkdir(parents=True)
        test_file.write_bytes(b"\x89PNG")

        with patch("ira.brain.imports_fallback_retriever._PROJECT_ROOT", tmp_path):
            from ira.brain.imports_fallback_retriever import extract_file_text
            result = await extract_file_text(str(test_file))

        assert result == ""


# ── Imports Fallback Retriever: deferred ingestion queue ─────────────────


class TestDeferredIngestionQueue:
    async def test_queue_and_load_round_trip(self, tmp_path: Path):
        queue_path = tmp_path / "deferred_ingestion_queue.jsonl"

        with patch("ira.brain.imports_fallback_retriever.DEFERRED_QUEUE_PATH", queue_path):
            from ira.brain.imports_fallback_retriever import (
                load_deferred_queue,
                queue_for_deferred_ingestion,
            )

            await queue_for_deferred_ingestion(
                filepath="/data/imports/quote.pdf",
                filename="quote.pdf",
                query="PF1 pricing",
                doc_type="quote",
            )
            await queue_for_deferred_ingestion(
                filepath="/data/imports/spec.xlsx",
                filename="spec.xlsx",
                query="machine specs",
                doc_type="spec",
            )

            entries = await load_deferred_queue()

        assert len(entries) == 2
        assert entries[0]["filename"] == "quote.pdf"
        assert entries[0]["status"] == "pending"
        assert entries[1]["filename"] == "spec.xlsx"

    async def test_load_empty_queue(self, tmp_path: Path):
        queue_path = tmp_path / "deferred_ingestion_queue.jsonl"

        with patch("ira.brain.imports_fallback_retriever.DEFERRED_QUEUE_PATH", queue_path):
            from ira.brain.imports_fallback_retriever import load_deferred_queue
            entries = await load_deferred_queue()

        assert entries == []

    async def test_mark_deferred_ingested(self, tmp_path: Path):
        queue_path = tmp_path / "deferred_ingestion_queue.jsonl"

        with patch("ira.brain.imports_fallback_retriever.DEFERRED_QUEUE_PATH", queue_path):
            from ira.brain.imports_fallback_retriever import (
                load_deferred_queue,
                mark_deferred_ingested,
                queue_for_deferred_ingestion,
            )

            await queue_for_deferred_ingestion(
                filepath="/data/imports/a.pdf",
                filename="a.pdf",
                query="test",
                doc_type="other",
            )
            await queue_for_deferred_ingestion(
                filepath="/data/imports/b.pdf",
                filename="b.pdf",
                query="test2",
                doc_type="other",
            )

            await mark_deferred_ingested("/data/imports/a.pdf")
            pending = await load_deferred_queue()

        assert len(pending) == 1
        assert pending[0]["filename"] == "b.pdf"
