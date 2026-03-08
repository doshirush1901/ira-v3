# Dream Mode Audit Report

**Date:** 2026-03-09
**Scope:** `src/ira/memory/dream_mode.py`, all entry points, prompts, schemas, tests
**Auditor:** Cursor Agent

---

## Executive Summary

Dream mode is a well-designed 11-stage nightly consolidation pipeline. However,
it has **2 crash-level bugs** in CLI entry points, a **schema-prompt mismatch**
that will cause `AttributeError` at runtime, and significant gaps in test
coverage (6 of 11 stages untested). The server-side path is the only entry
point that is fully wired and lifecycle-correct.

| Severity | Count |
|:---------|------:|
| CRITICAL | 3 |
| HIGH     | 4 |
| MEDIUM   | 6 |
| LOW      | 4 |

---

## 1. Entry Point Wiring

### 1.1 Dependency Comparison

| Dependency          | CLI `dream` | CLI `system exhale` | Server API | Nap script |
|:--------------------|:-----------:|:-------------------:|:----------:|:----------:|
| `long_term`         | Yes         | Yes (wrong kwarg)   | Yes        | Yes        |
| `episodic`          | Yes (broken)| No                  | Yes        | Yes        |
| `conversation`      | Yes         | No                  | Yes        | Yes        |
| `musculoskeletal`   | No          | No                  | Yes        | Yes        |
| `retriever`         | Yes         | No                  | Yes        | Yes        |
| `crm`              | No          | No                  | Yes        | Yes        |
| `procedural_memory` | No          | No                  | Yes        | No         |
| `data_event_bus`    | No          | No                  | Yes        | No         |
| **`initialize()`**  | **No**      | Yes                 | Yes        | Yes        |
| **`close()`**       | **No**      | No                  | Yes        | Yes        |

### 1.2 Stages Silently Skipped per Entry Point

| Stage | CLI `dream` | CLI `exhale` | Server | Nap script |
|:------|:-----------:|:------------:|:------:|:----------:|
| 0 — Deferred Ingestion    | Runs | N/A | Runs | Runs |
| 0.5 — Sleep Training      | Runs | N/A | Runs | Runs |
| 1 — CRM Ingestion         | **Skips** (no CRM) | N/A | Runs | Runs |
| 2 — Episodic Consolidation| Runs | N/A | Runs | Runs |
| 3a — Cross-episode Insights| Runs | N/A | Runs | Runs |
| 3b — Gap Detection        | **Skips** (no DB) | N/A | Runs | Runs |
| 3c — Creative Synthesis   | **Skips** (no DB) | N/A | Runs | Runs |
| 3d — Campaign Reflection  | **Skips** (no musculoskeletal) | N/A | Runs | Runs |
| 3e — Gap Resolution       | Runs | N/A | Runs | Runs |
| 4 — Procedural Learning   | **Skips** (no procedural) | N/A | Runs | **Skips** |
| 5 — Memory Pruning        | **Skips** (no DB) | N/A | Runs | Runs |
| 6 — Price Conflict Check  | Runs | N/A | Runs | Runs |
| 7 — Quality Review        | Runs | N/A | Runs | Runs |
| 8 — Graph Consolidation   | Runs | N/A | Runs | Runs |
| 9 — Follow-up Automation  | **Skips** (no CRM) | N/A | Runs | Runs |
| 10 — Morning Summary      | Runs | N/A | Runs | Runs |

The CLI `dream` command silently skips **7 of 11 stages**.

---

## 2. Findings

### CRITICAL

#### C1 — CLI `dream`: `EpisodicMemory()` called without required `long_term` argument

**File:** `src/ira/interfaces/cli.py:1463`
**Impact:** `TypeError` — the `ira dream` CLI command crashes immediately.

```python
# Current (broken)
episodic = EpisodicMemory()

# EpisodicMemory.__init__ signature requires long_term:
#   def __init__(self, long_term: LongTermMemory, db_path: str = "conversations.db")
```

#### C2 — CLI `system exhale`: `DreamMode` constructed with wrong keyword argument

**File:** `src/ira/interfaces/cli.py:1241`
**Impact:** `TypeError` — the `ira system exhale` command crashes immediately.

```python
# Current (broken)
dream_mode = DreamMode(long_term_memory=long_term)

# DreamMode.__init__ expects `long_term`, not `long_term_memory`,
# and requires `episodic` and `conversation` as positional args.
```

#### C3 — `DreamInsight` schema does not match prompt or consumer code

**File:** `src/ira/schemas/llm_outputs.py:220-224`
**Impact:** Stage 4 (Procedural Learning) calls `.get("priority")` on
recommendation strings, causing `AttributeError` whenever the LLM returns
non-empty recommendations.

```python
# Current schema — all list[str]
class DreamInsight(BaseModel):
    patterns: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

# But the prompt asks for structured objects:
#   "recommendations": [{"action": "", "priority": "HIGH|MEDIUM|LOW", "rationale": ""}]
#
# And dream_mode.py Stage 4 does:
#   high_confidence = [r for r in recommendations if r.get("priority") == "HIGH"]
#   → AttributeError: 'str' object has no attribute 'get'
```

---

### HIGH

#### H1 — CLI `dream`: `initialize()` never called

**File:** `src/ira/interfaces/cli.py:1466-1480`
**Impact:** `self._db` stays `None`. Stages 3b, 3c, and 5 silently skip all
database queries. Dream reports are not persisted.

#### H2 — CLI `dream`: no `close()` — resource leak

**File:** `src/ira/interfaces/cli.py:1466-1513`
**Impact:** SQLite connection (if opened by sub-components) is never closed.
Minor for a CLI command that exits, but violates resource hygiene.

#### H3 — Module docstring says "5-stage" but implementation has 11 stages

**File:** `src/ira/memory/dream_mode.py:1-10`
**Impact:** Misleading documentation. Developers may not realize stages 0,
0.5, 3e, 6-10 exist.

#### H4 — No stage-level status in `DreamReport`

**File:** `src/ira/data/models.py` (DreamReport)
**Impact:** Callers have no way to know which stages succeeded, failed, or
were skipped. A dream cycle where 8/11 stages error still returns a
"successful" report. The stage log is written to `dream_log.json` but not
exposed through the API or report model.

---

### MEDIUM

#### M1 — Stage 0 creates new `EmbeddingService`/`QdrantManager` per file

**File:** `src/ira/memory/dream_mode.py:208-229`
**Impact:** If 20 files are queued for deferred ingestion, 20 separate Qdrant
connections are opened and closed. Should create once outside the loop.

#### M2 — Stages 7 and 8 each create separate `KnowledgeGraph` instances

**Files:** `src/ira/memory/dream_mode.py:750-757` and `766-782`
**Impact:** Two Neo4j connection pools opened back-to-back for consecutive
stages. Should share one instance.

#### M3 — Nap script missing `procedural_memory` and `data_event_bus`

**File:** `scripts/nap.py:174-181`
**Impact:** Stage 4 (Procedural Learning) always skips during nap cycles.
The nap script is meant to be the "full" offline learning pipeline but
misses this dependency.

#### M4 — `DreamPrune` uses `list[str]` for episode IDs but SQLite stores integers

**File:** `src/ira/schemas/llm_outputs.py` (DreamPrune)
**Impact:** If the LLM returns integer IDs (matching the SQLite `INTEGER
PRIMARY KEY`), the Pydantic model coerces them to strings. The SQL query
then compares strings against integers, which may silently fail depending
on SQLite type affinity.

#### M5 — Stage 3b queries `knowledge_gaps` table but no migration creates it

**File:** `src/ira/memory/dream_mode.py:384-401`
**Impact:** The `knowledge_gaps` table is expected to exist in the
`conversations.db` SQLite database. If `Metacognition.initialize()` hasn't
been called in the same DB, this table won't exist and the query will fail
(caught by the broad exception handler, but silently).

#### M6 — Stage 3c queries `episodes` table from `self._db` (dream DB), not episodic DB

**File:** `src/ira/memory/dream_mode.py:410-416`
**Impact:** The dream mode's own SQLite DB (`conversations.db`) may not
contain an `episodes` table unless `EpisodicMemory` was initialized with
the same `db_path`. If paths differ, the query fails silently.

---

### LOW

#### L1 — `_write_dream_log` uses relative path by default

**File:** `src/ira/memory/dream_mode.py:44`
**Impact:** `_DREAM_LOG_PATH = Path("dream_log.json")` resolves relative to
the process working directory. If the server or CLI is started from a
different directory, the log file lands in an unexpected location.

#### L2 — Dream log capped at 500 entries with no rotation

**File:** `src/ira/memory/dream_mode.py:878`
**Impact:** After 500 dream cycles (~1.4 years of daily runs), the oldest
entries are silently dropped. No warning or archival mechanism.

#### L3 — Stage 10 Telegram message has no error context

**File:** `src/ira/memory/dream_mode.py:834-843`
**Impact:** The morning summary reports counts but not which stages failed.
A cycle with 5 failed stages sends the same "Good morning!" message as a
fully successful one.

#### L4 — Three expected prompt files never created

**Files:** `prompts/dream_morning_summary.txt`, `prompts/dream_price_check.txt`,
`prompts/dream_quality_review.txt`
**Impact:** Listed in `docs/SYSTEM_AUDIT.md` as expected but missing. Stages
6, 7, and 10 don't use prompts (they use Python logic or external modules),
so these are documentation errors rather than functional gaps.

---

## 3. Test Coverage

### 3.1 Stage Coverage Matrix

| Stage | Dedicated Test | Indirect (full-cycle) |
|:------|:--------------:|:---------------------:|
| 0 — Deferred Ingestion     | No  | No  |
| 0.5 — Sleep Training       | No  | No  |
| 1 — CRM Ingestion          | Yes | Yes |
| 2 — Episodic Consolidation | Yes | Yes |
| 3a — Cross-episode Insights| Yes | Yes |
| 3b — Gap Detection         | No  | Indirect |
| 3c — Creative Synthesis    | No  | Indirect |
| 3d — Campaign Reflection   | No  | Indirect |
| 3e — Gap Resolution        | No  | No  |
| 4 — Procedural Learning    | Yes | Yes |
| 5 — Memory Pruning         | Yes | Yes |
| 6 — Price Conflict Check   | No  | No  |
| 7 — Quality Review         | No  | No  |
| 8 — Graph Consolidation    | No  | No  |
| 9 — Follow-up Automation   | No  | No  |
| 10 — Morning Summary       | No  | No  |

### 3.2 Feature Coverage

| Feature | Tested? |
|:--------|:-------:|
| Dream report persistence (`_persist_report`) | No |
| Dream log writing (`_write_dream_log`) | Yes |
| `get_dream_reports()` query | No |
| CLI `ira dream` execution | No (only help text) |
| Server `GET /api/dream-report` | No |
| Nap script `scripts/nap.py` | No |
| Stage failure resilience | Yes (stages 1, 2 only) |

### 3.3 Summary

- **5 of 11 stages** have dedicated tests.
- **6 of 11 stages** (0, 0.5, 3e, 6, 7, 8, 9, 10) have zero test coverage.
- No integration tests for any entry point (CLI, server, nap).
- No tests verify that `DreamReport` is correctly persisted or retrieved.

---

## 4. Corrective Actions

### Priority 1 — Fix Crash Bugs (CRITICAL)

| ID | Action | Files |
|:---|:-------|:------|
| C1 | Pass `long_term` to `EpisodicMemory(long_term=long_term)` in CLI `dream` command | `cli.py:1463` |
| C2 | Rewrite CLI `system exhale` to construct `DreamMode` with correct kwargs (`long_term`, `episodic`, `conversation`) | `cli.py:1241` |
| C3 | Replace `DreamInsight` schema fields with structured sub-models matching the prompt (patterns as `list[DreamPattern]`, recommendations as `list[DreamRecommendation]`, etc.) | `llm_outputs.py:220-224` |

### Priority 2 — Fix Silent Failures (HIGH)

| ID | Action | Files |
|:---|:-------|:------|
| H1 | Add `await dream_mode.initialize()` and `await dream_mode.close()` (in try/finally) to CLI `dream` | `cli.py:1466-1513` |
| H2 | Wire missing dependencies (`crm`, `musculoskeletal`) in CLI `dream` to match nap script | `cli.py:1448-1471` |
| H3 | Update module docstring to reflect the actual 11-stage pipeline | `dream_mode.py:1-10` |
| H4 | Add `stage_results: dict[str, str]` field to `DreamReport` so callers can see per-stage status | `models.py`, `dream_mode.py` |

### Priority 3 — Improve Robustness (MEDIUM)

| ID | Action | Files |
|:---|:-------|:------|
| M1 | Hoist `EmbeddingService`/`QdrantManager` creation outside the deferred-ingestion loop | `dream_mode.py:208-229` |
| M2 | Share a single `KnowledgeGraph` instance between stages 7 and 8 | `dream_mode.py:748-782` |
| M3 | Wire `procedural_memory` in nap script | `nap.py:174-181` |
| M4 | Change `DreamPrune.archive` and `.keep` to `list[int]` to match SQLite integer PKs | `llm_outputs.py` |
| M5 | Ensure `knowledge_gaps` table exists before querying (CREATE IF NOT EXISTS or guard) | `dream_mode.py:384-401` |
| M6 | Pass the same `db_path` to DreamMode and EpisodicMemory, or query episodes through the episodic service | `dream_mode.py:410-416` |

### Priority 4 — Improve Observability (LOW)

| ID | Action | Files |
|:---|:-------|:------|
| L1 | Use an absolute path for `_DREAM_LOG_PATH` (e.g. `data/dream_log.json`) | `dream_mode.py:44` |
| L2 | Add log rotation or archival when approaching the 500-entry cap | `dream_mode.py:878` |
| L3 | Include failed-stage names in the Stage 10 Telegram summary | `dream_mode.py:834-843` |
| L4 | Remove the three phantom prompt entries from `SYSTEM_AUDIT.md` | `docs/SYSTEM_AUDIT.md` |

### Priority 5 — Increase Test Coverage

| ID | Action | Effort |
|:---|:-------|:-------|
| T1 | Add dedicated tests for stages 0, 0.5, 3b, 3c, 3d, 3e | Medium |
| T2 | Add dedicated tests for stages 6, 7, 8, 9, 10 | Medium |
| T3 | Add test for `_persist_report` and `get_dream_reports()` | Small |
| T4 | Add CLI integration test: `runner.invoke(cli_app, ["dream"])` | Small |
| T5 | Add server integration test: `GET /api/dream-report` | Small |
| T6 | Add test that verifies `DreamInsight` schema matches Stage 4 consumer code | Small |

### Priority 6 — Extract Shared Bootstrap

| ID | Action | Effort |
|:---|:-------|:-------|
| B1 | Create a `build_dream_mode()` factory function that all entry points share, ensuring consistent dependency wiring and lifecycle | Medium |
| B2 | The factory should accept optional overrides but default to the full dependency set (CRM, musculoskeletal, procedural, etc.) | — |

---

## 5. Recommended Fix Order

1. **C1 + C2 + H1** — Fix the two CLI crashes and missing `initialize()`. These are blocking bugs.
2. **C3** — Fix the `DreamInsight` schema mismatch. This causes runtime errors when the LLM returns recommendations.
3. **H4 + L3** — Add stage status to `DreamReport` and Telegram summary for observability.
4. **B1** — Extract shared bootstrap factory to prevent future wiring drift.
5. **M1 + M2** — Performance fixes for resource creation in loops.
6. **T1-T6** — Test coverage expansion.
