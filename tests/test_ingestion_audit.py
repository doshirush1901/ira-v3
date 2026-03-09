from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ira.brain import ingestion_audit


def test_normalise_qdrant_source_handles_relative_and_absolute(tmp_path: Path) -> None:
    rel = "data/imports/file.txt"
    abs_path = str((tmp_path / "x.txt").resolve())

    normalized_rel = ingestion_audit._normalise_qdrant_source(rel)
    normalized_abs = ingestion_audit._normalise_qdrant_source(abs_path)

    assert normalized_rel.endswith("data/imports/file.txt")
    assert normalized_abs == abs_path


@pytest.mark.asyncio
async def test_run_ingestion_audit_builds_expected_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    imports_root = Path("/tmp/imports")
    file_a = imports_root / "a.txt"
    file_b = imports_root / "nested" / "b.csv"
    import_files = [file_a.resolve(), file_b.resolve()]

    async def _fake_load_index() -> dict:
        return {
            "files": {
                "a.txt": {},
                "nested/b.csv": {},
            },
            "built_at": "2026-03-09T00:00:00+00:00",
        }

    async def _fake_load_log() -> dict:
        return {
            "files": {
                "a.txt": {"pipeline": "digestive_v2"},
                "nested/b.csv": {"pipeline": "digestive_v2"},
            },
            "last_full_scan": "2026-03-09T01:00:00+00:00",
        }

    async def _fake_scan_for_undigested(*, force: bool = False) -> list[dict]:
        _ = force
        return []

    async def _fake_fetch_qdrant_sources(collection: str) -> tuple[set[str], dict]:
        _ = collection
        return (
            {str(file_a.resolve()), str(file_b.resolve())},
            {
                "status": "ok",
                "collection": "test_collection",
                "count_estimate": 2,
                "points_scanned": 2,
                "distinct_sources": 2,
            },
        )

    async def _fake_fetch_neo4j_evidence() -> dict:
        return {
            "status": "ok",
            "nodes": 10,
            "relationships": 6,
            "nodes_with_source": 2,
            "distinct_source_values": 2,
            "source_values": {str(file_a.resolve()), str(file_b.resolve())},
            "per_file_source_supported": True,
        }

    monkeypatch.setattr(ingestion_audit, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(ingestion_audit, "_collect_supported_import_files", lambda _: import_files)
    monkeypatch.setattr(ingestion_audit, "load_index", _fake_load_index)
    monkeypatch.setattr(ingestion_audit, "load_log", _fake_load_log)
    monkeypatch.setattr(ingestion_audit, "scan_for_undigested", _fake_scan_for_undigested)
    monkeypatch.setattr(ingestion_audit, "_fetch_qdrant_sources", _fake_fetch_qdrant_sources)
    monkeypatch.setattr(ingestion_audit, "_fetch_neo4j_evidence", _fake_fetch_neo4j_evidence)
    monkeypatch.setattr(
        ingestion_audit,
        "get_settings",
        lambda: SimpleNamespace(qdrant=SimpleNamespace(collection="test_collection")),
    )

    report = await ingestion_audit.run_ingestion_audit()
    summary = report["summary"]

    assert summary["metadata_index"]["coverage_pct"] == 100.0
    assert summary["ingestion_log"]["coverage_pct"] == 100.0
    assert summary["qdrant"]["coverage_pct"] == 100.0
    assert summary["neo4j"]["coverage_pct"] == 100.0
    assert "memory_per_file_audit_not_supported" in report["gaps"]

