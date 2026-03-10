# Asana Production Data Patterns Report

Date: 2026-03-09  
Scope: `data/imports/23_Asana` + Atlas deterministic ETO parsing path

## Executive Snapshot

- Source volume is strong: 21 files in Asana imports (15 CSV, 3 XLSX, 2 PDF).
- CSV task volume is substantial: 7,249 rows across 15 exports.
- Ingestion completeness is partial: 37 Asana-indexed entries, with 9 up-to-date and 28 marked new.
- Most planning signal loss comes from sparse source fields (`Section/Column`, `Projects`, dependency columns), not parser crashes.
- Hardening pass improved robustness:
  - BOM-safe `Task ID` parsing fixed empty IDs from 7,249 to 0.
  - Duplicate export filenames (`name (1).csv`) are now deduped in Atlas scan selection.
  - Section fuzzy-mapping improved phase assignment (`gate_unknown` reduced from 76.73% to 75.00%).

## Production Data Patterns

### 1) Workflow Gate Distribution

- `gate_unknown`: 5,437 tasks (75.00%)
- `gate_fabrication_done`: 772 tasks
- `gate_material_ready`: 661 tasks
- `gate_assembly_done`: 246 tasks
- `gate_design_freeze`: 84 tasks
- `gate_dispatch_ready`: 39 tasks
- `gate_fat_done`: 10 tasks

Pattern: production/fabrication and procurement signals are present, but gate confidence is heavily constrained by missing phase metadata in source exports.

### 2) Task-Type Distribution

Top types:

- `other`: 5,259
- `fabrication`: 718
- `procure_receive`: 404
- `assembly_general`: 190
- `communication`: 174
- `procure_order`: 165
- `engineering`: 144

Pattern: deterministic matching can identify fabrication/procurement/assembly pockets, but a large "other" bucket indicates naming conventions are still too unstructured for high-fidelity classification.

### 3) Section/Column Reality

Top section values:

- `<blank>`: 6,595
- `Part Life cycle (In-House)`: 55
- `Manufacturing`: 51
- `Untitled section`: 42
- `Electrical & Pneumatic Assembly`: 36
- `Fabrication`: 34

Pattern: phase labels are mostly absent at source. This directly suppresses gate-quality and stage-level analytics.

### 4) Project Attribution

- Rows with blank/unknown project: 6,595 (dominant).
- Remaining rows distribute across 14 named projects.

Pattern: portfolio-level views are possible but distorted by project-null rows; project trend analytics should be treated as directional, not authoritative.

### 5) Procurement Lead-Time Signal

- O/R procurement pairs detected: 165
- Received pairs: 97
- Open pairs: 68
- Average lead time (received): 16.47 days
- Maximum observed lead time: 100 days

Pattern: procurement signal is one of the strongest structured outputs currently available and can already support supplier/lead-time monitoring.

## Atlas ETO Runtime Check (Post-Hardening)

Latest deterministic run (`max_files=8`):

- Status: `ok`
- CSV files scanned: 8 (dedupe-aware)
- Tasks scanned: 5,401
- Projects scanned: 8
- Completed tasks: 4,767
- Open tasks: 634
- Procurement pairs: 126 total (72 received, 54 open), avg lead 14.4 days
- Top unblockers: 0 (dependency fields mostly empty)

## Data Quality and Integrity Findings

- Date integrity is good (no invalid timestamp parsing, no completed-before-created anomalies found).
- Dependency fields are nearly empty (`Blocked By` and `Blocking` populated in only 1 row each), limiting unblocker logic.
- Status field is not populated in these exports, so status-vs-completion consistency checks are unavailable.
- Near-duplicate export pair exists (`...800_x_800.csv` and `...800_x_800 (1).csv`), now handled by Atlas dedupe selection.

## Changes Applied in Code

- `src/ira/brain/asana_planning_mapper.py`
  - Added BOM/casing/spacing-tolerant column lookup.
  - Added fuzzy section-to-gate fallback mappings.
  - Added tolerant field lookups for task ID, phase, dates, project.
- `src/ira/agents/atlas.py`
  - Added duplicate-export filename normalization for scan dedupe.
- `tests/test_asana_planning_mapper.py`
  - Added regression test for BOM-prefixed `Task ID`.
- `tests/test_atlas_asana_exports.py`
  - Added test to ensure copied exports (`(1)`) are deduped.

## Priority Next Actions

1. Enforce export hygiene in Asana: require section + project on all production tasks.
2. Add ingestion guardrails that warn on blank `Section/Column` and blank `Projects`.
3. Expand deterministic task-type rules for high-volume "other" naming patterns from your top projects.
4. Add a daily production-quality KPI report (unknown-gate %, blank-project %, procurement lead-time drift).
5. Re-ingest the 28 pending Asana-indexed files to raise retrieval completeness.

