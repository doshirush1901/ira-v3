from __future__ import annotations

from ira.brain.asana_planning_mapper import (
    classify_task_type,
    extract_component_key,
    map_phase_std,
    normalize_section_name,
    normalize_task_record,
    pair_procurement_events,
)


def test_normalize_section_name_typo_fix():
    assert normalize_section_name("MECHNICAL") == "MECHANICAL"
    assert normalize_section_name("  ELECTICAL   & PNEUMTIC  ") == "ELECTRICAL & PNEUMATIC"


def test_classify_task_type_prefixes():
    assert classify_task_type("O: Bearings") == "procure_order"
    assert classify_task_type("R: Bearings") == "procure_receive"
    assert classify_task_type("S: ANP Minutes") == "communication"
    assert classify_task_type("CNC: Plate profile cutting") == "fabrication"


def test_map_phase_std_from_section_then_fallback():
    assert map_phase_std("RFQs", "other") == "gate_material_ready"
    assert map_phase_std("", "assembly_postpaint") == "gate_assembly_done"
    assert map_phase_std("", "other") == "gate_unknown"


def test_extract_component_key_removes_noise():
    assert extract_component_key("O: Chrome shaft for MT and SC") == "chrome shaft"
    assert extract_component_key("R: Chain and Sprockets from DC") == "chain sprockets dc"


def test_normalize_task_record_sets_phase_and_component():
    row = {
        "Task ID": "1201",
        "Name": "O: Gearboxes SEW",
        "Section/Column": "RFQs",
        "Created At": "2022-10-08",
        "Completed At": "",
    }
    normalized = normalize_task_record(row)
    assert normalized.task_type == "procure_order"
    assert normalized.phase_std == "gate_material_ready"
    assert normalized.component_key == "gearboxes sew"
    assert normalized.created_at is not None
    assert normalized.completed_at is None


def test_normalize_task_record_supports_bom_task_id_header():
    row = {
        "\ufeffTask ID": "A-123",
        "Name": "R: Servo motor",
        "Section/Column": "Manufacturing queue",
        "Created At": "2024-01-02",
        "Completed At": "2024-01-10",
    }
    normalized = normalize_task_record(row)
    assert normalized.task_id == "A-123"
    assert normalized.phase_std == "gate_fabrication_done"
    assert normalized.task_type == "procure_receive"


def test_pair_procurement_events_returns_lead_time():
    rows = [
        {
            "Task ID": "o1",
            "Name": "O: Bearings",
            "Projects": "22014 - ALP Delhi - PF1 3520 SA",
            "Created At": "2022-10-08",
            "Completed At": "",
        },
        {
            "Task ID": "r1",
            "Name": "R: bearings",
            "Projects": "22014 - ALP Delhi - PF1 3520 SA",
            "Created At": "2022-10-08",
            "Completed At": "2022-11-23",
        },
    ]
    pairs = pair_procurement_events(rows)
    assert len(pairs) == 1
    assert pairs[0]["status"] == "received"
    assert pairs[0]["order_task_id"] == "o1"
    assert pairs[0]["receipt_task_id"] == "r1"
    assert pairs[0]["lead_time_days"] == 46


def test_pair_procurement_events_open_when_no_receipt():
    rows = [
        {
            "Task ID": "o1",
            "Name": "O: Cylinders",
            "Projects": "22014 - ALP Delhi - PF1 3520 SA",
            "Created At": "2022-10-08",
            "Completed At": "",
        },
    ]
    pairs = pair_procurement_events(rows)
    assert len(pairs) == 1
    assert pairs[0]["status"] == "open"
    assert pairs[0]["receipt_task_id"] == ""
    assert pairs[0]["lead_time_days"] is None

