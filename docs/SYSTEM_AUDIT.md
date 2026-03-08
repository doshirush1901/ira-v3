# Ira v3 — Comprehensive System Audit

**Date:** 2026-03-08 (updated for v3.3.0)
**Auditor:** Principal Engineer Review
**Scope:** Full codebase (`src/ira/`, `tests/`, `scripts/`, `prompts/`, infrastructure)
**Codebase:** 106 source files, ~33,000 lines | 23 test files, ~10,600 lines | 68 prompt files

---

## Part 1: Infrastructure & Deployment Readiness

### 1.1 Docker

**`docker-compose.yml` — Production-grade.** 116 lines, 4 services:

| Service | Image | Health Check | Restart | Memory Limit |
|---------|-------|:---:|:---:|:---:|
| `qdrant` | `qdrant/qdrant:latest` | `curl /healthz` | `unless-stopped` | 2 GB |
| `neo4j` | `neo4j:5.15.0-community` | `neo4j status` | `unless-stopped` | 2 GB |
| `postgres` | `postgres:16` | `pg_isready` | `unless-stopped` | 1 GB |
| `ira-app` | `build: .` (Dockerfile) | `curl /health` | `unless-stopped` | 4 GB |

**Findings:**

| # | Severity | Finding |
|---|----------|---------|
| 1.1a | **RESOLVED** | `Dockerfile` now exists. Docker healthcheck URL fixed to `/api/health` in v3.3.0. |
| 1.1b | LOW | `qdrant` uses `latest` tag — not pinned. Builds are non-reproducible. |
| 1.1c | GOOD | All services have health checks, restart policies, resource limits, and proper networking. |
| 1.1d | GOOD | `docker-compose.local.yml` exists for local dev (no health checks, bind mounts to `./data/`). |
| 1.1e | GOOD | Secrets are injected via `env_file: .env`, not hardcoded in compose. |

### 1.2 Database

| # | Severity | Finding |
|---|----------|---------|
| 1.2a | GOOD | Alembic migration exists: `alembic/versions/001_initial_crm_schema.py` (170 lines). |
| 1.2b | GOOD | `alembic/env.py` (78 lines) properly configured with async engine support. |
| 1.2c | GOOD | `DATABASE_URL` is configurable via environment variable in `config.py` (`DatabaseConfig`). |
| 1.2d | MEDIUM | `docker-compose.local.yml` hardcodes `POSTGRES_PASSWORD: ira` — acceptable for local dev only. |

### 1.3 Dependencies

**`pyproject.toml` declares 28 runtime dependencies.** Cross-referencing against actual imports:

| # | Severity | Finding |
|---|----------|---------|
| 1.3a | GOOD | All runtime imports (`mem0ai`, `httpx`, `neo4j`, `qdrant-client`, `tiktoken`, `flashrank`, `pypdf`, `openpyxl`, `python-docx`, etc.) are declared. |
| 1.3b | MEDIUM | `voyageai` is not declared — the code uses `httpx` to call the Voyage API directly, so no package is needed. However, this means there's a hidden dependency on the Voyage REST API contract with no SDK version pinning. |
| 1.3c | LOW | `greenlet` is declared but only needed as a transitive dependency of SQLAlchemy's asyncio support. Explicit declaration is defensive but unnecessary. |
| 1.3d | GOOD | Dev dependencies (`pytest`, `pytest-asyncio`) are in a separate `[tool.poetry.group.dev.dependencies]` section. |

### 1.4 Configuration

| # | Severity | Finding |
|---|----------|---------|
| 1.4a | GOOD | `.env.example` exists with 25+ variables, well-organized with section headers. |
| 1.4b | GOOD | `config.py` uses `pydantic-settings` with `SecretStr` for all API keys. No secrets are logged. |
| 1.4c | GOOD | `get_settings()` is cached via `@lru_cache(maxsize=1)` — singleton pattern. |
| 1.4d | GOOD | No hardcoded secrets found anywhere in `src/ira/`. |
| 1.4e | LOW | 16 hardcoded OpenAI/Voyage API endpoint URLs across brain modules. Should be centralized in config. |

### 1.5 Documentation

| # | Severity | Finding |
|---|----------|---------|
| 1.5a | GOOD | `docs/ARCHITECTURE.md` — 183 lines. Complete with ASCII diagrams, pipeline stages, agent roster, memory systems, and infrastructure tables. |
| 1.5b | GOOD | `CONTRIBUTING.md` — 91 lines. Covers setup, running, testing, adding agents, and code style. |
| 1.5c | GOOD | `AGENTS.md` — Complete agent roster with roles and responsibilities. |

---

## Part 2: Code Quality & Maintainability

### 2.1 Code Smell Markers

**Zero `TODO`, `FIXME`, `HACK`, `XXX`, `STUB`, or `NotImplemented` markers found** across all 95 source files. The codebase is clean.

### 2.2 Empty Shells

**Zero functions containing only `pass` found** in `src/ira/`. All functions have implementations.

**Empty script stubs (0 lines):**

| File | Status |
|------|--------|
| `scripts/migrate_from_v1.py` | Empty — dead file |
| `scripts/run_dream.py` | Empty — dead file |
| `scripts/run_ingestion.py` | Empty — dead file |

### 2.3 Error Handling

**No bare `except:` found.** All exception handlers specify at least `Exception`.

**Broad `except Exception:` inventory — 198 instances across 60 files:**

The most concerning patterns:

| # | Severity | File | Line(s) | Issue |
|---|----------|------|---------|-------|
| 2.3a | **HIGH** | `brain/retriever.py` | 305-306 | `except Exception: pass` — **silently swallows all errors** in `_log_retrieval()` with no logging whatsoever. |
| 2.3b | **HIGH** | `brain/retriever.py` | 390-391 | `except Exception: pass` — **silently swallows all errors** in `_apply_learned_corrections()` with no logging. |
| 2.3c | MEDIUM | `pipeline.py` | 25 instances | Every `_learn()` subsystem call is wrapped in `except Exception` — errors in learning are fire-and-forget. Acceptable for non-critical path, but makes debugging impossible. |
| 2.3d | MEDIUM | `brain/document_ingestor.py` | 377, 389, 399, 409, 427 | Five `except Exception:` blocks in entity extraction — each swallows a different entity type failure. |
| 2.3e | LOW | All agent `_tool_ask_*` methods | ~40 instances | Deliberate sandboxing pattern — tools return error strings instead of raising. Acceptable. |

**No custom exception classes defined anywhere.** The entire codebase relies on built-in exceptions and broad catches.

### 2.4 Logging

| # | Severity | Finding |
|---|----------|---------|
| 2.4a | GOOD | **Zero bare `print()` statements** for logging. All CLI output uses `rich.console.print()`. All internal logging uses `logging.getLogger(__name__)`. |
| 2.4b | GOOD | Log level is configurable via `LOG_LEVEL` environment variable (`AppConfig.log_level`). |
| 2.4c | GOOD | Consistent `logger = logging.getLogger(__name__)` at module top in every file. |

---

## Part 3: Agent Architecture & Agency

### 3.1 ReAct Loop Verification

**All 24 agents' `handle()` methods reach `self.run()`.** The ReAct loop (`base_agent.py` lines 351-433) correctly cycles through THINKING → ACTING → OBSERVING states with a configurable `max_iterations` (default 8).

| Agent | Fast-paths before `self.run()` | Bypasses ReAct? |
|-------|-------------------------------|:---:|
| Athena | Synthesizes if `agent_responses` pre-populated | No — still calls `run()` for new queries |
| Nemesis | Runs `run_training_cycle()` when learning_hub configured | **YES** — training path bypasses ReAct |
| All other 22 agents | Various `task`/`action` fast-paths | No — all reach `self.run()` |

**Nemesis bypass (line 444):** When `_learning_hub` and `_peer_agents` are configured, Nemesis runs its training cycle directly without engaging the ReAct loop. This is intentional — training is a structured multi-step process, not a free-form reasoning task.

### 3.2 Tool Registration

Every agent correctly registers its tools in `_register_tools()`. Full inventory:

| Agent | Custom Tools | Default Tools Available |
|-------|:---:|:---:|
| Athena | 3 | 7 (when services injected) |
| Alexandros | 6 | 7 |
| Arachne | 5 | 7 |
| Asclepius | 5 | 7 |
| Atlas | 5 (1 conditional on `pantheon`) | 7 |
| Cadmus | 5 | 7 |
| Calliope | 4 | 7 |
| Chiron | 5 | 7 |
| Clio | 4 | 7 |
| Delphi | 5 | 7 |
| Hephaestus | 5 | 7 |
| Hera | 4 | 7 |
| Hermes | 6 | 7 |
| Iris | 3 | 7 |
| Mnemosyne | 5 (all conditional on services) | 7 |
| Nemesis | 4 | 7 |
| Plutus | 6 (2 conditional) | 7 |
| Prometheus | 7 (4 conditional) | 7 |
| Quotebuilder | 5 | 7 |
| Sophia | 2 | 7 |
| Sphinx | 2 | 7 |
| Themis | 3 | 7 |
| Tyche | 3 | 7 |
| Vera | 2 | 7 |

**No unused tools found.** Every registered tool has a corresponding handler method.

### 3.3 Memory Access

**Default tools registered by `BaseAgent._register_default_tools()` (lines 102-175):**

| Service Key | Tool(s) Registered |
|-------------|-------------------|
| `long_term_memory` | `recall_memory`, `store_memory` |
| `conversation_memory` | `get_conversation_history` |
| `relationship_memory` | `check_relationship` |
| `goal_manager` | `check_goals` |
| `episodic_memory` | `recall_episodes` |
| `pantheon` | `ask_agent` |

**Finding:** Tools are registered dynamically based on which services are present. If a service key is misspelled during injection, the corresponding tool **silently fails to register** — no error, no warning. This is a fragile pattern.

### 3.4 State Management

| Agent | Storage | Path | Async-Safe? | Race Condition Risk? |
|-------|---------|------|:---:|:---:|
| Asclepius | SQLite | `data/brain/asclepius.db` | Yes (aiosqlite + WAL) | Low |
| Atlas | SQLite | `data/brain/atlas_logbook.db` | Yes (aiosqlite + WAL) | Low |
| Chiron | JSON file | `data/brain/sales_training.json` | **No** (sync `Path.read_text/write_text`) | **YES** |
| Quotebuilder | Text file | `data/brain/quote_sequence.txt` | **No** (sync read/write) | **YES — critical** |
| Nemesis | SQLite (CorrectionStore) | `data/brain/corrections.db` | Yes (aiosqlite) | Low |
| Alexandros | JSON index (read-only) | `data/imports/metadata_index.json` | **No** (sync read) | Low (read-only) |

| # | Severity | Finding |
|---|----------|---------|
| 3.4a | **HIGH** | `quotebuilder.py` line 30-45: `_next_quote_id()` reads and writes a sequence counter via sync file I/O. Two concurrent requests could read the same ID, producing duplicate quote numbers. |
| 3.4b | MEDIUM | `chiron.py` lines 28-44: `_load_patterns()` / `_save_patterns()` use sync file I/O. Concurrent writes could corrupt the JSON file. |
| 3.4c | LOW | `atlas.py` line 58: `_db_initialised` is a **class-level attribute**, not instance-level. Shared across all instances. |

### 3.5 Encapsulation Violations

| # | Severity | File | Line | Issue |
|---|----------|------|------|-------|
| 3.5a | MEDIUM | `sophia.py` | 59-60 | Accesses `nemesis._ensure_correction_store()` and `nemesis._correction_store` (private attributes). |
| 3.5b | MEDIUM | `nemesis.py` | 520 | Accesses `self._learning_hub._crm` (private attribute of LearningHub). |
| 3.5c | MEDIUM | `pipeline.py` | 73 | Accesses `pantheon._router` (private attribute). |
| 3.5d | MEDIUM | `pipeline.py` | 292 | Accesses `pantheon._retriever` (private attribute). |

### 3.6 Discarded Parameters

| # | Severity | File | Line | Issue |
|---|----------|------|------|-------|
| 3.6a | MEDIUM | `asclepius.py` | 112-113 | `_tool_close_punch_item` receives `resolution` parameter but doesn't pass it to `close_punch_item()`. Resolution text is lost. |
| 3.6b | LOW | `atlas.py` | 112 | `_tool_get_production_schedule` receives `project_id` but `production_schedule()` ignores it. |

---

## Part 4: Pipeline Integrity & Leaks

### 4.1 Linear Flow

The pipeline is **strictly linear, single-pass, fire-and-forget.** The 11 steps execute sequentially in `process_request()`:

```
PERCEIVE → REMEMBER → ROUTE(fast) → TRUTH_HINTS → ROUTE(procedure) → ROUTE(LLM)
    → ENRICH → EXECUTE → ASSESS → REFLECT → SHAPE → LEARN → RETURN
```

**No hidden loops or recursion in the pipeline itself.** However, within the EXECUTE step, agents can call other agents via `ask_agent` (which calls `pantheon.process()`), creating potential recursion. This is bounded by the ReAct loop's `max_iterations` (default 8) and the LLM's tendency to converge, but there is **no explicit recursion depth limit** on inter-agent calls.

| # | Severity | Finding |
|---|----------|---------|
| 4.1a | MEDIUM | No recursion depth limit on inter-agent delegation. Agent A can ask Agent B, which asks Agent C, etc. Each has its own 8-iteration ReAct budget, but the chain depth is unbounded. |

### 4.2 Resource Management

| # | Severity | File | Line | Issue |
|---|----------|------|------|-------|
| 4.2a | **HIGH** | `brain/ingestion_gatekeeper.py` | 226-227 | `qdrant.close()` and `ingestor.close()` are called, but **`graph.close()` is never called**. The Neo4j driver connection leaks. |
| 4.2b | MEDIUM | `brain/document_ingestor.py` | 49-63 | `DocumentIngestor` stores a `sqlite3.Connection` in `self._ledger`. Has a `close()` method (line 464) but no `__aenter__`/`__aexit__` — callers must remember to close manually. |
| 4.2c | MEDIUM | `brain/document_ingestor.py` | 87-94 | `load_workbook()` is not in a `try/finally` block. An exception before `wb.close()` (line 94) leaks the workbook handle. |
| 4.2d | GOOD | All `httpx.AsyncClient()` instances use `async with` blocks. No leaks. |
| 4.2e | GOOD | `KnowledgeGraph`, `QdrantManager`, and `CorrectionStore` all implement `close()` and `__aexit__`. |
| 4.2f | GOOD | `server.py` `lifespan()` properly shuts down all services in the `finally` block (lines 392-449). |

### 4.3 Error Propagation

| # | Severity | Finding |
|---|----------|---------|
| 4.3a | MEDIUM | **Pipeline LEARN step is entirely fire-and-forget.** All 9 subsystem calls in `_learn()` (lines 417-544) are wrapped in individual `except Exception` blocks. A failure in CRM logging, memory storage, or goal extraction is silently swallowed. This means the system can appear to work while silently losing data. |
| 4.3b | MEDIUM | **No retry logic anywhere.** Failed LLM calls (in `base_agent._call_openai`, `_call_anthropic`) return `"(LLM call failed)"` and the ReAct loop continues with this error string as the observation. There are no retries with exponential backoff. |
| 4.3c | LOW | Agent failures during parallel execution (`pantheon._gather_responses`) are caught and returned as error strings: `"(Agent 'X' encountered an error)"`. Athena then synthesizes including these error messages. |

### 4.4 Context Passing

The pipeline context is a **mutable dictionary** constructed in step 6 (EXECUTE):

```python
context: dict[str, Any] = {
    "perception": perception,
    "channel": channel,
    "services": { ... },
    "history": history,
    "cross_channel_history": cross_channel_history,
    "active_goal": active_goal,
    "resolved_input": resolved_input,
    ...
}
```

| # | Severity | Finding |
|---|----------|---------|
| 4.4a | LOW | Context is a plain `dict[str, Any]` with no schema validation. Any stage can add/remove/overwrite any key. No TypedDict or Pydantic model enforces the contract. |
| 4.4b | LOW | Each request gets a fresh context dict — no risk of cross-request contamination within a single process. |

---

## Part 5: Modularity & Wiring

### 5.1 Orphaned Modules

| # | File | Lines | Status |
|---|------|:---:|--------|
| 1 | `brain/hybrid_search.py` | 215 | **COMPLETELY DEAD.** Contains a working BM25 + RRF implementation. Never imported by any file in the entire project. |
| 2 | `brain/machine_intelligence.py` | 182 | **No production consumer.** Only imported by `tests/test_brain.py`. Has its own duplicate `_llm_call()` method instead of using `BaseAgent.call_llm()`. |

### 5.2 Circular Dependencies

**No circular import chains exist.** The dependency graph is a clean DAG with 6 layers:

- **Layer 0:** Leaf modules (`config.py`, `data/models.py`, `context.py`, `prompt_loader.py`, etc.)
- **Layer 1:** Brain primitives (`embeddings.py`, `knowledge_graph.py`, etc.)
- **Layer 2:** Brain composites (`qdrant_manager.py`, `document_ingestor.py`, etc.)
- **Layer 3:** Brain orchestrators (`retriever.py`, `imports_fallback_retriever.py`, etc.)
- **Layer 4:** Agents (`base_agent.py` + 24 agents)
- **Layer 5:** Orchestrators (`pantheon.py`, `pipeline.py`)
- **Layer 6:** Entry points (`server.py`, `cli.py`)

`pipeline.py` uses **6 inline imports** inside method bodies to avoid import-time cycles. These create hidden runtime dependencies invisible to static analysis.

### 5.3 Dependency Injection

**There is no DI container.** Services are wired through **three independent service locator dictionaries:**

| Locator | Location | Scope | Keys | Failure Mode |
|---------|----------|-------|:---:|--------------|
| `server._services` | `server.py:61` | Global module dict | ~35 | `RuntimeError` |
| `BaseAgent._services` | `base_agent.py:70` | Per-agent instance (×24) | ~14 | Tool silently not registered |
| `handlers._SERVICES` | `skills/handlers.py:22` | Global module dict | ~4 | Returns error string |

| # | Severity | Finding |
|---|----------|---------|
| 5.3a | **HIGH** | **CLI creates duplicate CRM instances.** `cli.py` `_build_pantheon()` creates one `CRMDatabase()` at line 123, then `_build_pipeline()` creates a **second** `CRMDatabase()` at line 199. Agents and the pipeline operate on different database connection pools. |
| 5.3b | MEDIUM | **Two separate `inject_services()` calls** are required during bootstrap (first CRM/pricing, then memory services). If the second call is missed, agents silently lack memory tools. |
| 5.3c | MEDIUM | **Direct attribute mutation** instead of injection: `dream_mode._procedural = procedural_memory` (server.py:254), `sensory._emotional_intelligence = emotional_intelligence` (server.py:290). |
| 5.3d | MEDIUM | **All service keys are bare strings** with no constants or enums. A typo like `"long_term_memoyr"` silently fails. |

### 5.4 Bootstrap Divergence (server.py vs cli.py)

| Subsystem | `server.py` | `cli.py` |
|-----------|:---:|:---:|
| `DataEventBus.start()` | Called | **Never called** |
| `data_event_bus` injected to agents | Yes | **No** |
| `DreamMode` | Constructed | **Not constructed** |
| `MusculoskeletalSystem` | Constructed | **Not constructed** in pipeline |
| `ImmuneSystem` | Constructed | **Not constructed** |
| `RespiratorySystem` | Constructed + started | **Not constructed** |
| `EmailProcessor` | Constructed | **Not constructed** |
| `DripEngine` | Constructed | **Not constructed** |

The CLI path creates a **minimal subset** of the full system. This means CLI users get degraded functionality with no warning.

---

## Part 6: Test Coverage Gaps

### 6.1 Test Inventory

| Test File | Lines | Functions | Focus |
|-----------|:---:|:---:|-------|
| `test_agents.py` | 785 | ~50 | MessageBus, BaseAgent, all 24 agent `handle()` methods, Pantheon, BoardMeeting |
| `test_react_loop.py` | 491 | ~18 | ReAct loop: direct answers, tool use, max iterations, tool errors, service injection |
| `test_brain.py` | 764 | ~37 | EmbeddingService, QdrantManager, Chunking, UnifiedRetriever, DeterministicRouter, MachineIntelligence, PricingEngine, SalesIntelligence |
| `test_memory.py` | 671 | ~31 | ConversationMemory, LongTermMemory, EpisodicMemory, Metacognition, EmotionalIntelligence, InnerVoice, RelationshipMemory, DreamMode |
| `test_systems.py` | 1,194 | ~42 | DigestiveSystem, RespiratorySystem, ImmuneSystem, EndocrineSystem, SensorySystem, VoiceSystem, LearningHub, Nemesis training |
| `test_interfaces.py` | 1,409 | ~39 | EmailProcessor, CLI, FastAPI server, Dashboard, RequestPipeline (full 11-step) |
| `test_crm.py` | 665 | ~27 | CRMDatabase CRUD, pipeline summary, stale leads, QuoteManager, AutonomousDripEngine |
| `test_drip_engine.py` | 468 | ~15 | Campaign creation, step scheduling, cycle execution, reply checking |
| `test_context.py` | 210 | ~21 | UnifiedContextManager, cross-channel preservation, goal management |
| `test_skills.py` | 122 | ~12 | SKILL_MATRIX integrity, `use_skill` dispatcher, individual handlers |

### 6.2 Untested Modules (Zero Coverage)

**Brain modules — 20 untested:**

| Module | Lines | Risk |
|--------|:---:|------|
| `adaptive_style.py` | 158 | Low — style tracking |
| `correction_learner.py` | 161 | Medium — learns from corrections |
| `correction_store.py` | 180 | Medium — SQLite persistence |
| `error_monitor.py` | 190 | Medium — error alerting |
| `feedback_handler.py` | 262 | Medium — feedback detection |
| `graph_consolidation.py` | 211 | High — modifies graph edges |
| `hybrid_search.py` | 215 | N/A — dead code |
| `imports_fallback_retriever.py` | 477 | High — file retrieval |
| `imports_metadata_index.py` | 435 | High — metadata indexing |
| `ingestion_gatekeeper.py` | 243 | High — ingestion orchestration |
| `ingestion_log.py` | 98 | Low — simple log |
| `knowledge_discovery.py` | 240 | Medium — fact extraction |
| `knowledge_graph.py` | 560 | **Critical** — Neo4j operations |
| `knowledge_health.py` | 256 | Medium — health monitoring |
| `power_levels.py` | 148 | Low — agent scoring |
| `pricing_learner.py` | 262 | Medium — price learning |
| `quality_filter.py` | 212 | Medium — dedup/quality |
| `realtime_observer.py` | 146 | Low — observation logging |
| `sleep_trainer.py` | 322 | Medium — 5-phase training |
| `truth_hints.py` | 181 | Medium — fast-path answers |

**Systems modules — 5 untested:**

| Module | Lines | Risk |
|--------|:---:|------|
| `circulatory.py` | 370 | High — event propagation |
| `crm_enricher.py` | 493 | Medium — CRM enrichment |
| `crm_populator.py` | 584 | Medium — CRM population |
| `data_event_bus.py` | 123 | Medium — event bus |
| `musculoskeletal.py` | 340 | Medium — action tracking |

**Other untested:**

| Module | Lines | Risk |
|--------|:---:|------|
| `memory/goal_manager.py` | 358 | Medium — only tested indirectly via pipeline |
| `memory/procedural.py` | 294 | Medium — only tested indirectly via DreamMode |
| `prompt_loader.py` | 36 | Low |
| `data/models.py` | 220 | Low — pure data models |

**Total: ~30 modules with zero direct test coverage, representing ~7,500 lines (~33% of the codebase).**

### 6.3 Agent Test Quality

All 24 agents have `handle()` tests, but they are **shallow**:
- Mock the LLM to return a canned response
- Verify only that `handle()` returns a string
- Do not test tool usage, multi-step reasoning, or agent-specific behavior

### 6.4 ReAct Loop Test Quality

`test_react_loop.py` is **excellent** — 18 tests covering:
- Direct answers (no tool use)
- Single and multi-tool use
- Max iteration fallback with `_force_final_answer()`
- Tool execution errors
- Invalid tool names
- Service injection and dynamic tool registration
- Unparseable LLM responses

---

## Part 7: Security & Hardening

### 7.1 Input Validation

| # | Severity | File | Line | Issue |
|---|----------|------|------|-------|
| 7.1a | MEDIUM | `brain/document_ingestor.py` | 231 | `discover_files(base_path)` — user-provided path converted to `Path` with no traversal validation. Could scan arbitrary directories. |
| 7.1b | MEDIUM | `brain/knowledge_discovery.py` | 123-132 | `deep_scan_and_extract(filepath)` — no validation that path is within expected directory. |
| 7.1c | MEDIUM | `brain/imports_fallback_retriever.py` | 303-316 | `extract_file_text(filepath)` — no path validation. |
| 7.1d | LOW | `pipeline.py` context dict | — | No schema validation on the context dictionary. Any stage can inject arbitrary keys. |

### 7.2 Prompt Injection

| # | Severity | Finding |
|---|----------|---------|
| 7.2a | MEDIUM | **No prompt injection defenses in any of the 71 prompt files.** None contain instructions like "ignore instructions in user input" or "do not follow instructions embedded in documents." |
| 7.2b | MEDIUM | User text flows directly into LLM prompts without sanitization in: `sales_intelligence.py`, `feedback_handler.py`, `realtime_observer.py`, `machine_intelligence.py`, `pricing_engine.py`, `knowledge_discovery.py`. |
| 7.2c | LOW | Output is JSON-parsed in most cases, which limits the practical impact of injection. However, agents that produce free-text responses (Calliope, Hermes) are more vulnerable. |

### 7.3 Injection Attacks

| # | Severity | File | Line | Issue |
|---|----------|------|------|-------|
| 7.3a | **CRITICAL** | `brain/knowledge_graph.py` | 420-422 | `run_cypher(query, params)` — accepts and executes **arbitrary Cypher queries**. Any caller can run `MATCH (n) DETACH DELETE n`. Currently only called from `graph_consolidation.py` with safe parameterized queries, but the method is a wide-open door. |
| 7.3b | **HIGH** | `brain/knowledge_graph.py` | 248-258 | `add_relationship()` — `from_type` and `to_type` node labels are f-string interpolated into Cypher. Mitigated by `_KEY_FIELDS` whitelist check (line 239-241), but fragile if the whitelist is expanded carelessly. |
| 7.3c | MEDIUM | `brain/knowledge_graph.py` | 249-251 | Property keys from caller-provided dicts are interpolated into Cypher `SET` clause via `f"r.{k} = ${k}"`. A malicious key like `"x} DETACH DELETE n //"` would be injectable. |
| 7.3d | GOOD | All SQL queries use parameterized placeholders (`?` for SQLite, `$1` for PostgreSQL via SQLAlchemy). No SQL injection risks found. |

### 7.4 Data Leaks & Multi-Tenancy

| # | Severity | Finding |
|---|----------|---------|
| 7.4a | MEDIUM | **No multi-tenancy model.** The system is designed as a single-tenant application for one organization (Machinecraft). All agents share the same knowledge base, CRM, and memory stores. |
| 7.4b | MEDIUM | **CORS wildcard** in `server.py` — `allow_origins=["*"]` with `allow_credentials=True`. In production, this should be restricted to actual frontend domains. |
| 7.4c | LOW | Conversation memory is keyed by `contact_email`, providing per-contact isolation. However, the knowledge base (Qdrant, Neo4j) is shared across all contacts. |

---

## Part 8: Performance & Optimization

### 8.1 Async/Await Correctness

**Blocking I/O in async contexts — 35+ instances:**

| Category | Files Affected | Example |
|----------|:---:|---------|
| `Path.read_text()` / `Path.write_text()` | 15 files | `power_levels.py:61,71`, `pricing_learner.py:45,55`, `truth_hints.py:74,181`, `correction_learner.py:148,159`, `feedback_handler.py:252,260`, `adaptive_style.py:65,74`, `realtime_observer.py:51`, `sleep_trainer.py:222,233,257,269`, `ingestion_log.py:36,44`, `imports_metadata_index.py:194,202,207`, `imports_fallback_retriever.py:137,187,310,348,375,391`, `knowledge_health.py:64`, `chiron.py:28-44`, `quotebuilder.py:30-45` |
| `open()` in async methods | 3 files | `graph_consolidation.py:53,71,145`, `realtime_observer.py:62`, `document_ingestor.py:68,106,111` |
| `time.sleep()` in async | 1 file | `imports_metadata_index.py:277` — **`time.sleep(0.3)` inside `async def build_index()`** |
| Sync file readers from async callers | 2 files | `document_ingestor.py:294` (calls sync `read_pdf`, `read_xlsx`), `knowledge_discovery.py:132` |

| # | Severity | Finding |
|---|----------|---------|
| 8.1a | **HIGH** | `imports_metadata_index.py:277` — `time.sleep(0.3)` blocks the entire event loop. Must be `await asyncio.sleep(0.3)`. |
| 8.1b | MEDIUM | ~35 instances of sync file I/O in async contexts. Each blocks the event loop for the duration of the disk operation. Should use `aiofiles` or `asyncio.to_thread()`. |
| 8.1c | MEDIUM | `document_ingestor.py:294` — sync PDF/XLSX/DOCX readers called from async `ingest_file()`. These can take seconds for large files. Should be wrapped in `asyncio.to_thread()`. |

### 8.2 Caching

| Location | Type | What's Cached |
|----------|------|---------------|
| `config.py:128` | `@lru_cache(maxsize=1)` | `Settings` singleton |
| `prompt_loader.py:20` | `@lru_cache(maxsize=None)` | All loaded prompt templates |
| `brain/deterministic_router.py` | Compiled regex patterns | Route patterns (at class init) |

| # | Severity | Finding |
|---|----------|---------|
| 8.2a | MEDIUM | **No caching on LLM calls.** Identical queries to the same agent produce fresh LLM calls every time. A simple response cache (keyed on query + agent + context hash) could significantly reduce costs and latency. |
| 8.2b | MEDIUM | **No caching on embedding calls.** `EmbeddingService.embed()` calls the Voyage API every time. Repeated searches for the same query re-embed it. |
| 8.2c | LOW | `imports_fallback_retriever.py` has its own embedding cache (`EMBEDDING_CACHE_PATH`) for file summaries — good pattern that should be extended to the main `EmbeddingService`. |

### 8.3 LLM Call Volume

Per request, the pipeline makes **at minimum 3-5 LLM calls**, and up to **15+ for complex queries:**

| Step | LLM Calls | Notes |
|------|:---:|-------|
| PERCEIVE (SensorySystem) | 1-2 | Emotion detection, entity extraction |
| REMEMBER (ConversationMemory) | 0-1 | Coreference resolution (if history exists) |
| ROUTE (DeterministicRouter) | 0 | Regex-based, no LLM |
| TRUTH_HINTS | 0 | Pattern matching, no LLM |
| EXECUTE (Agent ReAct) | 2-8 | Per agent: 1 per ReAct iteration. Multi-agent queries multiply this. |
| ASSESS (Metacognition) | 1 | Knowledge assessment |
| REFLECT (InnerVoice) | 0-1 | Optional reflection |
| SHAPE (VoiceSystem) | 1 | Response formatting |
| LEARN | 0-2 | Goal extraction, observation |

| # | Severity | Finding |
|---|----------|---------|
| 8.3a | MEDIUM | **Step 5.5 (ENRICH) creates fresh instances** of `AdaptiveStyleTracker`, `RealTimeObserver`, and `PowerLevelTracker` on every request. Each re-reads its JSON file from disk. These should be long-lived singletons. |
| 8.3b | LOW | Multi-agent queries (where Athena delegates to 2-3 agents) can generate 10-15 LLM calls per request. This is inherent to the architecture but should be monitored. |

### 8.4 Unbounded Memory Growth

| # | Severity | File | Issue |
|---|----------|------|-------|
| 8.4a | MEDIUM | `message_bus.py` | `MessageBus._history` is an unbounded `list[Message]`. Every message ever published is retained in memory. No eviction policy. |
| 8.4b | MEDIUM | `context.py` | `UnifiedContextManager._store` is an unbounded `dict[str, list[ContextEntry]]`. Every contact's history grows without limit. |

---

## Part 9: Prompts & Knowledge Base

### 9.1 Prompt Inventory

**71 prompt files, 1,536 total lines.** Breakdown:

| Category | Count |
|----------|:---:|
| Agent system prompts | 24 |
| Nemesis training | 4 |
| Dream mode | 9 |
| Digestive system | 3 |
| Brain/Knowledge | 13 |
| Memory | 4 |
| Sales/CRM | 5 |
| Drip engine | 2 |
| Goal management | 2 |
| Other | 4 |

### 9.2 Prompt Consistency

**All 24 agent system prompts follow a consistent structure:**
1. Identity statement ("You are {name}, the {role} of the Machinecraft AI Pantheon.")
2. TOOLS section (listing default + agent-specific tools with descriptions)
3. RESPONSE FORMAT section (ReAct JSON protocol)
4. GUIDELINES section (agent-specific behavioral rules)

**All task-specific prompts specify:**
- "Return ONLY valid JSON"
- Explicit JSON schema
- "No markdown fences"

### 9.3 Tool Definition Accuracy

**Tool definitions in prompts match actual implementations.** Verified for all 24 agents — the tools listed in each `{name}_system.txt` correspond exactly to the tools registered in `_register_tools()`.

### 9.4 Orphaned Prompts

**5 prompt files are never loaded by any code:**

| File | Expected Purpose |
|------|-----------------|
| ~~`prompts/dream_morning_summary.txt`~~ | ~~Morning summary generation~~ (handled inline in Stage 10) |
| ~~`prompts/dream_price_check.txt`~~ | ~~Price validation during dreams~~ (handled by PricingLearner) |
| ~~`prompts/dream_quality_review.txt`~~ | ~~Quality review of stored knowledge~~ (handled by GraphConsolidation) |
| `prompts/drip_adjust.txt` | Drip campaign adjustment |
| `prompts/drip_evaluate.txt` | Drip campaign evaluation |

These appear to be prompts for planned features that haven't been implemented yet.

### 9.5 Placeholder Prompts

**6 prompt files contain only 1 line** (a bare instruction with no structure):

| File | Content |
|------|---------|
| `consolidate_episode.txt` | Single-line instruction |
| `conversation_extract_entities.txt` | Single-line instruction |
| `conversation_resolve_coreferences.txt` | Single-line instruction |
| `memorable_moments.txt` | Single-line instruction |
| `pattern_extraction.txt` | Single-line instruction |
| `weave_episodes.txt` | Single-line instruction |

These are functional but minimal — they rely entirely on the LLM's general capability rather than providing structured guidance.

---

## Part 10: Final Synthesis

### Production-Readiness Score: **62 / 100**

| Category | Score | Weight | Weighted |
|----------|:---:|:---:|:---:|
| Infrastructure & Deployment | 7/10 | 15% | 10.5 |
| Code Quality | 7/10 | 10% | 7.0 |
| Agent Architecture | 8/10 | 15% | 12.0 |
| Pipeline Integrity | 6/10 | 10% | 6.0 |
| Modularity & Wiring | 5/10 | 10% | 5.0 |
| Test Coverage | 5/10 | 15% | 7.5 |
| Security | 4/10 | 15% | 6.0 |
| Performance | 6/10 | 5% | 3.0 |
| Prompts & KB | 8/10 | 5% | 4.0 |
| | | | **61.0** |

**Rounded: 62/100**

### Breakdown Rationale

- **Infrastructure (7/10):** Docker compose is excellent, but the missing Dockerfile is a showstopper for deployment. Alembic, config, and docs are solid.
- **Code Quality (7/10):** Zero TODOs, zero bare prints, consistent logging. But 198 broad `except Exception:` catches (2 silent `pass`), no custom exceptions, and no error handling strategy.
- **Agent Architecture (8/10):** All 24 agents are genuine ReAct agents. Tool registration is correct. Memory access works. The architecture is clean and well-designed. Deductions for encapsulation violations and race conditions.
- **Pipeline Integrity (6/10):** Linear flow is correct, but fire-and-forget learning, no retry logic, no recursion depth limit, and a leaked Neo4j connection.
- **Modularity (5/10):** Clean DAG with no circular deps, but three competing service locators, duplicate CRM instances in CLI, direct attribute mutation, and bare-string service keys.
- **Test Coverage (5/10):** 33% of the codebase has zero tests. Agent tests are shallow. Critical modules like `knowledge_graph.py` and `circulatory.py` are untested. ReAct loop tests are excellent.
- **Security (4/10):** Arbitrary Cypher execution, Cypher injection via f-strings, no prompt injection defenses, no input path validation, CORS wildcard. SQL is properly parameterized.
- **Performance (6/10):** 35+ blocking I/O calls in async contexts, `time.sleep()` in async, no LLM/embedding caching, fresh instances created per request. httpx clients are properly managed.
- **Prompts (8/10):** Consistent structure, accurate tool definitions, good coverage. 5 orphaned files and 6 minimal placeholders.

---

### Top 10 Priority Fixes

| # | Severity | Issue | Impact | Effort |
|---|----------|-------|--------|--------|
| **1** | **CRITICAL** | **Missing `Dockerfile`.** `docker-compose.yml` references it but it doesn't exist. Deployment is impossible. | Blocks all deployment | Low — create a standard Python Dockerfile |
| **2** | **CRITICAL** | **Cypher injection in `knowledge_graph.py`.** `run_cypher()` (line 420) accepts arbitrary queries. Property keys are f-string interpolated into `SET` clauses (line 249). Node labels are interpolated (line 248). | Data destruction, exfiltration | Medium — add allowlists, parameterize all dynamic values, remove or restrict `run_cypher()` |
| **3** | **HIGH** | **Duplicate CRM instances in CLI path.** `cli.py` creates two separate `CRMDatabase()` objects — one for agents, one for the pipeline. They operate on different connection pools, leading to stale reads and potential data inconsistency. | Data inconsistency | Low — pass the same CRM instance to both |
| **4** | **HIGH** | **35+ blocking I/O calls in async contexts.** `Path.read_text()`, `Path.write_text()`, `open()`, `time.sleep(0.3)` called from async functions across 15+ files. Blocks the event loop, degrading throughput for all concurrent requests. | Performance degradation under load | Medium — wrap in `asyncio.to_thread()` or use `aiofiles` |
| **5** | **HIGH** | **Race condition in `quotebuilder.py:30-45`.** `_next_quote_id()` reads and writes a sequence counter via sync file I/O with no locking. Concurrent requests produce duplicate quote numbers. | Duplicate quote IDs | Low — use `aiosqlite` with autoincrement, or `asyncio.Lock` |
| **6** | **HIGH** | **33% of codebase has zero test coverage.** 30 modules (~7,500 lines) including critical-path code like `knowledge_graph.py`, `circulatory.py`, `imports_fallback_retriever.py`, and `graph_consolidation.py` have no tests. | Regressions go undetected | High — write tests for the 10 highest-risk modules |
| **7** | **HIGH** | **Neo4j driver leak in `ingestion_gatekeeper.py:226-227`.** `graph.close()` is never called. Each ingestion run leaks a Neo4j driver connection. | Connection pool exhaustion over time | Low — add `await graph.close()` |
| **8** | **HIGH** | **Silent error swallowing in `retriever.py`.** Lines 305-306 and 390-391: `except Exception: pass` — errors in retrieval logging and learned corrections are silently discarded with no logging whatsoever. | Invisible failures, impossible debugging | Low — add `logger.debug()` at minimum |
| **9** | **MEDIUM** | **No prompt injection defenses.** The system processes external emails and documents. User/document content flows directly into LLM prompts without sanitization. No defensive instructions in any of the 71 prompt files. | Prompt manipulation via crafted emails/documents | Medium — add defensive preambles to agent system prompts, sanitize external input |
| **10** | **MEDIUM** | **Three competing service locators with bare-string keys.** `server._services`, `BaseAgent._services`, and `handlers._SERVICES` are independent dicts with overlapping keys. A typo in a service key silently fails. No type safety. | Silent misconfiguration, debugging nightmares | High — introduce a typed `ServiceRegistry` class with constants for keys |

---

### What's Done Well

Despite the issues above, this codebase has significant strengths:

1. **Architecture is genuinely impressive.** A 24-agent pantheon with a biological-metaphor body system, 11-step pipeline, and 9 memory subsystems — all working together coherently.
2. **All 24 agents are real ReAct agents** with genuine tool-calling loops, not wrappers around prompt templates.
3. **Zero code smell markers** (TODO/FIXME/HACK) — the codebase is clean and intentional.
4. **Consistent logging** — no bare `print()` statements, configurable log levels.
5. **Secrets management** — Pydantic `SecretStr` for all API keys, `.env.example` is comprehensive.
6. **Docker compose** is production-grade with health checks, restart policies, and resource limits.
7. **ReAct loop tests** are excellent — 18 tests covering edge cases.
8. **Prompt engineering** is consistent and well-structured across all 71 files.
9. **No circular dependencies** — clean layered architecture.
10. **httpx client management** — every `AsyncClient` uses `async with`. No connection leaks from HTTP clients.
