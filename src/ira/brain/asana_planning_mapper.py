"""Normalize Asana exports into ETO planning signals.

This module provides deterministic parsing helpers for Asana task exports used
by Atlas and planning workflows:
  - task type classification from task names/prefixes
  - section normalization and phase mapping
  - O:/R: component-key extraction and pairing
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_SECTION_NORMALIZATION_OVERRIDES = {
    "MECHNICAL": "MECHANICAL",
    "ELECTICAL & PNEUMTIC": "ELECTRICAL & PNEUMATIC",
}

_PHASE_STD_MAP = {
    "PO": "gate_po_confirmed",
    "COMMERCIAL": "gate_po_confirmed",
    "DRAWINGS": "gate_design_freeze",
    "DESIGN": "gate_design_freeze",
    "MECHANICAL": "gate_design_freeze",
    "ELECTRICAL & PNEUMATIC": "gate_design_freeze",
    "RFQS": "gate_material_ready",
    "PROCUREMENT": "gate_material_ready",
    "PURCHASE": "gate_material_ready",
    "FABRICATION": "gate_fabrication_done",
    "ASSEMBLY": "gate_assembly_done",
    "TESTING": "gate_fat_done",
    "FAT": "gate_fat_done",
    "QUALITY": "gate_fat_done",
    "DISPATCH": "gate_dispatch_ready",
    "PACKING": "gate_dispatch_ready",
}

_TASK_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*O\s*[:\-]\s*", re.IGNORECASE), "procure_order"),
    (re.compile(r"^\s*R\s*[:\-]\s*", re.IGNORECASE), "procure_receive"),
    (re.compile(r"\bRFQ\b|\bquote\b|\bvendor\b|\bpurchase\b", re.IGNORECASE), "procure_activity"),
    (re.compile(r"^\s*S\s*[:\-]\s*|\bminutes\b|\bcall\b|\bemail\b|\bmeeting\b", re.IGNORECASE), "communication"),
    (re.compile(r"\bdrawing\b|\b3d model\b|\bsolidworks\b|\bconcept\b|\bapproval\b", re.IGNORECASE), "engineering"),
    (re.compile(r"^\s*(BR|CT|W|CNC|FT)\s*[:\-]\s*|\bfabricat|\bweld|\bcutting\b|\bbending\b", re.IGNORECASE), "fabrication"),
    (re.compile(r"\bassembly\b.*\bpre[- ]?paint\b|\bpre[- ]?paint\b.*\bassembly\b", re.IGNORECASE), "assembly_prepaint"),
    (re.compile(r"\bassembly\b.*\bpost[- ]?paint\b|\bpost[- ]?paint\b.*\bassembly\b", re.IGNORECASE), "assembly_postpaint"),
    (re.compile(r"\bassembly\b", re.IGNORECASE), "assembly_general"),
    (re.compile(r"\bFAT\b|\btesting\b|\binspection\b|\bquality\b|\bpunch\b", re.IGNORECASE), "qa_fat"),
    (re.compile(r"\bdispatch\b|\bpacking\b|\bvacuum\s*pack\b|\bloading\b|\bshipment\b", re.IGNORECASE), "dispatch"),
    (re.compile(r"\bPO\b|\bpurchase order\b|\badvance\b|\binvoice\b|\bpayment\b", re.IGNORECASE), "commercial"),
]

_TASK_TYPE_TO_PHASE = {
    "procure_order": "gate_material_ready",
    "procure_receive": "gate_material_ready",
    "procure_activity": "gate_material_ready",
    "fabrication": "gate_fabrication_done",
    "assembly_prepaint": "gate_assembly_done",
    "assembly_postpaint": "gate_assembly_done",
    "assembly_general": "gate_assembly_done",
    "qa_fat": "gate_fat_done",
    "dispatch": "gate_dispatch_ready",
}

_COMPONENT_STOPWORDS = {"from", "for", "and", "the", "a", "an", "to", "of", "mt", "sc", "plug"}


def normalize_section_name(section: str) -> str:
    """Normalize Asana section/column names into canonical uppercase labels."""
    normalized = re.sub(r"\s+", " ", (section or "").strip()).upper()
    return _SECTION_NORMALIZATION_OVERRIDES.get(normalized, normalized)


def classify_task_type(task_name: str) -> str:
    """Classify task type from task text using deterministic rules."""
    for pattern, label in _TASK_TYPE_RULES:
        if pattern.search(task_name or ""):
            return label
    return "other"


def map_phase_std(section: str, task_type: str) -> str:
    """Map section/task metadata to standard ETO phase gates."""
    section_normalized = normalize_section_name(section)
    if section_normalized in _PHASE_STD_MAP:
        return _PHASE_STD_MAP[section_normalized]
    return _TASK_TYPE_TO_PHASE.get(task_type, "gate_unknown")


def extract_component_key(task_name: str) -> str:
    """Extract a normalized component key from O:/R: procurement task names."""
    without_prefix = re.sub(r"^\s*[OR]\s*[:\-]\s*", "", task_name or "", flags=re.IGNORECASE)
    clean = re.sub(r"[^a-zA-Z0-9 ]+", " ", without_prefix).lower()
    tokens = [token for token in clean.split() if token not in _COMPONENT_STOPWORDS]
    return " ".join(tokens[:5]).strip()


def parse_iso_date(value: str | None) -> datetime | None:
    """Best-effort parsing for ISO-like dates found in Asana exports."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(slots=True)
class NormalizedTask:
    task_id: str
    task_name: str
    phase_raw: str
    phase_std: str
    task_type: str
    component_key: str
    created_at: datetime | None
    completed_at: datetime | None


def normalize_task_record(row: dict[str, Any]) -> NormalizedTask:
    """Normalize one Asana-export row into planning-ready fields."""
    task_name = str(row.get("Name", "")).strip()
    task_type = classify_task_type(task_name)
    phase_raw = str(row.get("Section/Column", "")).strip()
    return NormalizedTask(
        task_id=str(row.get("Task ID", "")).strip(),
        task_name=task_name,
        phase_raw=phase_raw,
        phase_std=map_phase_std(phase_raw, task_type),
        task_type=task_type,
        component_key=extract_component_key(task_name) if task_type in {"procure_order", "procure_receive"} else "",
        created_at=parse_iso_date(str(row.get("Created At", "")).strip()),
        completed_at=parse_iso_date(str(row.get("Completed At", "")).strip()),
    )


def pair_procurement_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair O:/R: tasks by project and component key for lead-time tracking."""
    normalized = [normalize_task_record(row) for row in rows]
    orders: list[tuple[NormalizedTask, str]] = []
    receipts: dict[tuple[str, str], list[NormalizedTask]] = {}

    for idx, row in enumerate(rows):
        n = normalized[idx]
        project = str(row.get("Projects", "")).strip().lower()
        key = (project, n.component_key)
        if n.task_type == "procure_order" and n.component_key:
            orders.append((n, project))
        elif n.task_type == "procure_receive" and n.component_key:
            receipts.setdefault(key, []).append(n)

    for key in receipts:
        receipts[key].sort(key=lambda t: t.completed_at or datetime.max)

    pairs: list[dict[str, Any]] = []
    for order, project in orders:
        key = (project, order.component_key)
        candidates = receipts.get(key, [])
        matched_idx: int | None = None
        for idx, candidate in enumerate(candidates):
            if order.created_at and candidate.completed_at and candidate.completed_at >= order.created_at:
                matched_idx = idx
                break
            if order.created_at is None and candidate.completed_at:
                matched_idx = idx
                break
        receipt = candidates.pop(matched_idx) if matched_idx is not None else None
        lead_days: int | None = None
        if receipt and order.created_at and receipt.completed_at:
            lead_days = (receipt.completed_at.date() - order.created_at.date()).days
        pairs.append({
            "component_key": order.component_key,
            "project": project,
            "order_task_id": order.task_id,
            "receipt_task_id": receipt.task_id if receipt else "",
            "lead_time_days": lead_days,
            "status": "received" if receipt else "open",
        })
    return pairs

