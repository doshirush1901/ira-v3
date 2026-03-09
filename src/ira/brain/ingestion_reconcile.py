"""Reconciliation workflow for ingestion audit gaps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ira.brain.imports_metadata_index import build_index
from ira.brain.ingestion_audit import run_ingestion_audit
from ira.brain.ingestion_gatekeeper import run_ingestion_cycle


def plan_reconciliation_actions(gaps: list[str]) -> list[str]:
    """Map audit gap keys to reconciliation actions."""
    actions: list[str] = []
    if "metadata_index_incomplete" in gaps:
        actions.append("rebuild_metadata_index")
    if any(
        g in gaps
        for g in (
            "ingestion_log_incomplete",
            "qdrant_incomplete",
            "memory_incomplete",
            "memory_per_file_audit_not_supported",
        )
    ):
        actions.append("run_ingestion_cycle")
    if "neo4j_unavailable" in gaps:
        actions.append("check_neo4j_credentials")
    return actions


async def reconcile_ingestion(
    *,
    batch_size: int = 712,
    concurrency: int = 3,
    apply: bool = False,
    use_llm_for_reindex: bool = True,
    output_path: str = "data/brain/ingestion_reconcile_latest.json",
) -> dict[str, Any]:
    """Reconcile ingestion gaps by applying audit-driven corrective actions."""
    before = await run_ingestion_audit()
    gaps = before.get("gaps", [])
    actions = plan_reconciliation_actions(gaps)

    results: dict[str, Any] = {
        "before": before,
        "planned_actions": actions,
        "applied": apply,
        "action_results": {},
    }

    if apply:
        if "rebuild_metadata_index" in actions:
            results["action_results"]["rebuild_metadata_index"] = await build_index(
                use_llm=use_llm_for_reindex,
                force=False,
            )
        if "run_ingestion_cycle" in actions:
            results["action_results"]["run_ingestion_cycle"] = await run_ingestion_cycle(
                force=False,
                batch_size=batch_size,
                concurrency=concurrency,
            )

    after = await run_ingestion_audit()
    results["after"] = after

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str))
    return results

