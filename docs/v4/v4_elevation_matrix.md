# Ira v4 Elevation Matrix

Goal: elevate Ira into a Cursor-first, Manus-like orchestration agent for Machinecraft by using v3 as the runtime base and selectively porting high-value v2 patterns.

## Priority legend

- **P0**: unblock correctness/reliability now
- **P1**: major capability lift
- **P2**: optimization and scale-hardening

## Decision legend

- `keep`: retain as-is, continue using
- `upgrade`: modify/extend existing v3 file
- `port_pattern`: re-implement ideas from v2 file into v3 destination
- `archive`: keep as historical reference only, non-runtime

## Matrix

| Priority | File/Folder | Decision | Owner | Effort | Why it matters |
|---|---|---|---|---|---|
| P0 | `src/ira/pipeline_loop.py` | upgrade | platform | M | Critical MCP loop bug: `_parse_plan` path needs completion and robust parse fallback. |
| P0 | `src/ira/interfaces/mcp_server.py` | upgrade | platform | S | Ensure MCP task loop parity with API path and stable service wiring. |
| P0 | `src/ira/systems/task_orchestrator.py` | upgrade | platform | M | Canonical multi-phase loop for Manus-style execution, clarification, and reporting. |
| P0 | `src/ira/interfaces/server.py` | upgrade | platform | M | Add/normalize operator controls (status, abort, retry, plan approval flow). |
| P0 | `src/ira/services/llm_client.py` | upgrade | platform | M | Reliability backbone (retry/fallback/circuit-breaker behavior consistency). |
| P0 | `src/ira/services/resilience.py` | keep | platform | S | Shared retry/backoff primitives already aligned with v4 reliability goals. |
| P0 | `src/ira/services/structured_logging.py` | keep | platform | S | Structured event traces are required for operator observability. |
| P0 | `src/ira/systems/legacy_guard.py` | keep | platform | S | Prevents accidental runtime dependency on archived v2 trees. |
| P0 | `src/ira/systems/outbound_approvals.py` | keep | operations_platform | S | Approval-gated outbound flow aligns with safety and governance. |
| P0 | `tests/test_mcp_server.py` | upgrade | qa_platform | M | Add real task-loop path tests to catch parser/runtime regressions. |
| P0 | `tests/test_task_orchestrator.py` | upgrade | qa_platform | M | Strengthen failure-mode coverage (Redis unavailable, retries, partial reruns). |
| P1 | `src/ira/pipeline.py` | upgrade | platform | M | Unify progress schema/events and orchestration semantics across all loops. |
| P1 | `src/ira/pantheon.py` | keep | platform | S | Core bounded-agent orchestration stays as v4 backbone. |
| P1 | `src/ira/agents/athena.py` | upgrade | agents | M | Improve planning/delegation quality and phase decomposition. |
| P1 | `src/ira/brain/deterministic_router.py` | upgrade | brain | M | Add complexity hints and better pre-plan routing logic. |
| P1 | `src/ira/brain/fast_path.py` | upgrade | brain | M | Faster deterministic handling for common high-frequency asks. |
| P1 | `src/ira/brain/retriever.py` | upgrade | brain | M | Improve multi-source retrieval quality and source-grounding. |
| P1 | `src/ira/brain/qdrant_manager.py` | upgrade | brain | M | Strengthen indexing consistency and retrieval filters for domain corpora. |
| P1 | `src/ira/brain/knowledge_graph.py` | upgrade | brain | M | Better relation grounding for long, multi-phase tasks. |
| P1 | `src/ira/brain/feedback_handler.py` | keep | memory | S | Correction loop remains core truth-hardening path. |
| P1 | `src/ira/agents/mnemon.py` | keep | memory | S | Correction authority should remain non-negotiable in v4. |
| P1 | `src/ira/memory/goal_manager.py` | upgrade | memory | M | Improve long-running objective persistence and execution continuity. |
| P1 | `src/ira/interfaces/email_processor.py` | upgrade | operations_platform | M | Keep draft-first behavior, add deeper task/event integration. |
| P1 | `web-ui/src/lib/api.ts` | upgrade | web_ui | M | Normalize task/query SSE event contracts for consistent UX. |
| P1 | `web-ui/src/components/Chat.tsx` | upgrade | web_ui | M | Add task-loop mode toggle for complex asks. |
| P1 | `web-ui/src/app/chat/page.tsx` | upgrade | web_ui | M | Add task planning/approval surface, not just message stream. |
| P1 | `docs/v4/readiness_criteria.md` | keep | platform | S | v4 go-live gate source of truth. |
| P2 | `src/ira/services/trace_store.py` (new) | port_pattern | platform | M | Port persistent run-trace idea from v2 for replay/debuggability. |
| P2 | `src/ira/brain/reasoning_policies.py` (new) | port_pattern | brain | M | Port selected reflection/self-consistency policies from v2 engine. |
| P2 | `src/ira/brain/retrieval_conflict.py` (new) | port_pattern | brain | M | Port conflict detection pattern before synthesis for higher trust. |
| P2 | `src/ira/systems/ingestion_jobs.py` (new) | port_pattern | data_platform | L | Consolidate one-off ingest scripts into governed reusable jobs. |
| P2 | `scripts/start.sh` | upgrade | devops | S | Align startup path with actual local infra/runtime expectations. |
| P2 | `scripts/stop.sh` | upgrade | devops | S | Ensure reliable shutdown path and operator parity with start path. |
| P2 | `scripts/README.md` | upgrade | devops | S | Keep runbook accurate for Cursor operators and contributors. |
| P2 | `docs/v4/data_lifecycle_policy.md` | keep | data_governance | S | Governs repo vs external store decisions and retention standards. |
| P2 | `docs/v4/script_productization_matrix.md` | keep | operations_platform | S | Canonical policy for script promotion into product paths. |

## v2 Archive Mapping (Port vs Archive)

| Source (v2 archive) | Destination (v3/v4) | Decision | Priority |
|---|---|---|---|
| `core_modules/reasoning_engine_v2.py` | `src/ira/brain/reasoning_policies.py` + `src/ira/pipeline_loop.py` | port_pattern | P2 |
| `core_modules/ki_sensing.py` | `src/ira/brain/deterministic_router.py` | port_pattern | P1 |
| `core_modules/api_rate_limiter.py` | `src/ira/services/resilience.py` and call sites | port_pattern | P0 |
| `core_modules/structured_logger.py` | `src/ira/services/structured_logging.py` | port_pattern | P0 |
| `core_modules/consolidation_scheduler.py` | `src/ira/memory/dream_mode.py` + CLI | port_pattern | P2 |
| `legacy_pipelines/query_analysis_pipeline.py` | `src/ira/brain/fast_path.py` helpers | port_pattern | P1 |
| `legacy_pipelines/deep_research_pipeline.py` | `src/ira/brain/retrieval_conflict.py` | port_pattern | P2 |
| `core_modules/agent.py` | n/a | archive | P0 |
| `legacy_pipelines/*` (runtime usage) | n/a | archive | P0 |
| `skills/*` (legacy executable instructions) | prompts/tests in current runtime | archive+translate | P1 |

## Data/Corpus Elevation Map

| Data path | Role | Action |
|---|---|---|
| `data/imports/01_Quotes_and_Proposals` | pricing/quote retrieval core | keep + prioritize ingestion coverage |
| `data/imports/02_Orders_and_POs` | execution/order ground truth | keep + prioritize ingestion coverage |
| `data/imports/04_Machine_Manuals_and_Specs` | technical correctness core | keep + prioritize ingestion coverage |
| `data/imports/07_Leads_and_Contacts` | lead intelligence | keep + clean/schema normalize |
| `data/imports/23_Asana` | project/production signal | keep + improve entity extraction |
| `data/imports/24_WebSite_Leads` | fresh inbound demand signal | keep + dedupe/enrich |
| `data/knowledge/*` snapshots | high churn derived artifacts | externalize/archive with retention |
| `data/case_studies/*/attachments` | heavy binary evidence | external object storage + metadata pointers |
| `data/cadmus/manus_outputs/*` | generated media artifacts | externalize + artifact registry |

## Sprint sequencing

- **Sprint 1 (P0):** task-loop correctness, MCP/API parity, reliability enforcement, test hardening.
- **Sprint 2 (P1):** retrieval/router upgrades, Cursor/web operator UX improvements, event schema unification.
- **Sprint 3 (P2):** v2 pattern ports (reasoning/conflict/trace), ingestion job consolidation, ops/runbook polish.
