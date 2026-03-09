from __future__ import annotations

from ira.brain.ingestion_reconcile import plan_reconciliation_actions


def test_plan_reconciliation_actions_maps_core_gaps() -> None:
    actions = plan_reconciliation_actions(
        [
            "metadata_index_incomplete",
            "qdrant_incomplete",
            "memory_incomplete",
            "neo4j_unavailable",
        ]
    )
    assert "rebuild_metadata_index" in actions
    assert "run_ingestion_cycle" in actions
    assert "check_neo4j_credentials" in actions


def test_plan_reconciliation_actions_empty() -> None:
    actions = plan_reconciliation_actions([])
    assert actions == []

