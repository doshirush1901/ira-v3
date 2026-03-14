# Audit: Cursor as Front End → Ira Full Stack

**Date:** 2025-03-14  
**Scope:** Request flow from Cursor to Ira (full pipeline, sub-agents, Mem0/Neo4j/Postgres/Qdrant) and back to Cursor for display.

---

## 1. Intended Architecture

- **Front end:** Cursor. User types in Cursor chat.
- **Request path:** Cursor parses the request and sends it to Ira (no separate Ira UI required).
- **Ira:** Runs full cycles and loops (Manus-style): 11-stage pipeline, Athena routing, sub-agent calls (Clio, Prometheus, Plutus, etc.), drafting, thinking.
- **Backends:** Ira uses Mem0, Neo4j, Postgres, Qdrant (and Redis) for retrieval, CRM, knowledge graph, and memory.
- **Response path:** After Ira’s processing, Cursor receives the reply and displays it to the user.

---

## 2. Current Implementation — What Exists

### 2.1 Entry points (how Cursor can hit Ira)

| Path | Trigger | How it runs | Full stack? |
|------|---------|-------------|-------------|
| **CLI** | User says "@Ira", "ask Ira", "tell Ira" | Cursor runs `ira ask "<question>" --json` from project root | Yes |
| **CLI task** | User says "@Ira do a full analysis...", "prepare a report..." | Cursor runs `ira task "<goal>" --json` | Yes |
| **API** | Optional; when server is running | Cursor uses `POST /api/query/stream` or `POST /api/task/stream` | Yes |
| **MCP** | When MCP server/API is running | Cursor calls `query_ira(question)` or `plan_task` / `execute_phase` / `generate_report` | Yes |

**Rules:** `.cursor/rules/ira-api.mdc` (alwaysApply: true) tells Cursor to use the **CLI first** for queries: run `ira ask "<question>" --json`. API is alternative when the server is explicitly up. MCP is used when the Ira MCP server is running (e.g. via `ira mcp` or API lifespan).

### 2.2 Full stack (CLI path)

When Cursor runs `ira ask "..." --json`:

1. **CLI** (`src/ira/interfaces/cli.py`): `ask()` → `_build_pantheon()` → `_build_pipeline()` → `_process_request_with_live_progress()` → `pipeline.process_request()`.
2. **Pantheon** is built with:
   - **Qdrant** (QdrantManager), **Neo4j** (KnowledgeGraph), **Mem0** (MemoryClient if `memory.api_key` set), **Postgres** (CRMDatabase, QuoteManager).
   - **UnifiedRetriever**(qdrant, graph, mem0_client) used for RAG.
   - All 27 agents are registered and get the same service injection (retriever, CRM, memory, etc.).
3. **Pipeline** (`src/ira/pipeline.py`): 11 stages — Perceive → Remember → Fast path / Sphinx → Route → Enrich → Execute (routed agents) → Faithfulness → Assess → Reflect → Shape → Learn → Return.
4. **Execute stage:** Athena (router) selects agent(s); agents run ReAct loops with tools (`recall_memory`, `store_memory`, `search_knowledge`, CRM, etc.). Retrieval uses `pantheon.retriever` (Qdrant + Neo4j + Mem0).
5. **Output:** CLI prints JSON `{"response": "<markdown>", "agents_consulted": [...]}`; Cursor is instructed to parse and display the `response` as Markdown.

So when the CLI is used, **Ira does run her full cycles and loops**, uses **Mem0, Neo4j, Postgres, Qdrant** (and Redis when available), and Cursor gets the reply and can display it.

### 2.3 MCP path

- **MCP server** (`src/ira/interfaces/mcp_server.py`): On first tool use, `_ensure_initialized()` calls the **same** `_build_pantheon()` and `_build_pipeline()` from the CLI. So `query_ira(question)` runs the same pipeline and same stack (Qdrant, Neo4j, Mem0, Postgres).
- **Agent loop (complex tasks):** `plan_task` → `execute_phase` → `generate_report` use the in-memory `AgentLoop` (Manus-style plan/execute/observe). So multi-step tasks are supported via MCP when Cursor uses those tools.

### 2.4 API server path

- **Lifespan** (`src/ira/interfaces/server.py`): Builds Redis, Qdrant, Neo4j, Mem0, Postgres, retriever, CRM, pipeline, etc., and holds a single `RequestPipeline` instance. `/api/query/stream` and `/api/query` call `pipeline.process_request()`. So the API path also uses the full stack.

---

## 3. Gaps and Discrepancies

### 3.1 **Trigger: Ira is opt-in, not default**

- **Current behavior:** Cursor sends the request to Ira **only when** the user explicitly invokes Ira (e.g. "@Ira", "ask Ira", "tell Ira"). Generic chat in Cursor is answered by Cursor’s own model, not by Ira.
- **Implication:** “Cursor as front end” is **per-message opt-in**. If the intent is “every request in this chat goes to Ira”, the rules would need to change (e.g. treat this chat or this project as “Ira-only” and always run `ira ask` or `query_ira` for user messages).

**Recommendation:** Decide whether “Cursor as front end” means (a) “when user asks Ira, Cursor forwards to Ira and shows the reply” (current), or (b) “in this workspace/chat, every user message goes to Ira”. If (b), add a rule or agent mode that always routes user input to `ira ask` / `query_ira` and displays the result.

### 3.2 **Containers: Qdrant and Neo4j may not be running**

- **Expected:** `docker-compose.local.yml` defines four services: **qdrant**, **neo4j**, **postgres**, **redis**.
- **Observed (at audit time):** Only **postgres** and **redis** were up. Qdrant and Neo4j were not running.
- **Impact:** With Qdrant/Neo4j down, vector and graph retrieval fail or degrade. The pipeline may still run but with incomplete RAG and no graph. Mem0 is cloud-backed so it doesn’t depend on local containers.

**Recommendation:** Before relying on “full stack”, run `docker compose -f docker-compose.local.yml up -d` and confirm all four containers are up. Add a preflight in `ira ask` or in Cursor rules (e.g. “start Ira” → start Docker and verify qdrant + neo4j).

### 3.3 **CLI pipeline: optional subsystems not wired**

- **Current:** `_build_pipeline()` in the CLI wires: sensory, conversation_memory, relationship_memory, goal_manager, procedural_memory, metacognition, inner_voice, pantheon, voice, endocrine, crm, unified_context, redis_cache, agent_journal. It does **not** pass: `adaptive_style`, `realtime_observer`, `power_level_tracker`, `episodic_memory`, `long_term_memory`, `tool_stats_tracker`, `musculoskeletal`.
- **Impact:** Pipeline and agents still run; retrieval and core memory are via pantheon and injected services. Optional enrichments (adaptive style, power levels, episodic/long-term on pipeline, etc.) are only used when the API server builds the pipeline (server lifespan wires more of these). So CLI and MCP (which uses CLI’s `_build_pipeline`) may have a slightly reduced feature set compared to the API.

**Recommendation:** Low priority unless you need those optional subsystems in CLI/MCP. If you do, extend `_build_pipeline()` in `cli.py` to pass the same optional components the server uses.

### 3.4 **Two “complex task” backends**

- **Task loop (CLI / API):** `ira task "<goal>" --json` and `/api/task/stream` use **TaskOrchestrator** (Redis-backed, linear execution, SSE stream).
- **Agent loop (MCP):** `plan_task` / `execute_phase` / `generate_report` use **AgentLoop** (in-memory, observe/replan/clarify per phase).
- Both achieve “multi-step, multi-agent” work but with different state and UX. Cursor rules prefer CLI task for complex work; MCP agent loop is used when MCP is running and Cursor follows `ira-agent-loop.mdc`.

**Recommendation:** Document when to use which (e.g. “CLI task for one-shot report from terminal/Cursor; MCP agent loop when you want phase-by-phase control in Cursor”). No code change required unless you want a single unified backend.

### 3.5 **Fallback when CLI/API fails**

- **Current:** If `ira ask` or the API fails, `.cursor/rules/ira-cursor-workflow.mdc` tells Cursor to do a **Cursor-as-Ira** workflow: search codebase + `data/`, route by delegation matrix, synthesize, and answer in Ira’s voice. No live Mem0/Neo4j/Postgres/Qdrant.
- **Implication:** User still gets an answer, but it’s not from Ira’s full stack. The reply is “Ira-style” but not from the real pipeline.

**Recommendation:** Keep the fallback; when used, Cursor should state clearly that Ira’s full stack was unavailable and the answer is from the fallback workflow (per existing rules).

---

## 4. Summary Table

| Requirement | Status | Notes |
|-------------|--------|--------|
| Cursor as front end | ✅ Implemented | Cursor runs `ira ask` or uses API/MCP when user invokes Ira. |
| Request parsed and sent to Ira | ✅ | Via CLI (`ira ask`), API (`/api/query/stream`), or MCP (`query_ira`). |
| Ira full cycles and loops | ✅ | 11-stage pipeline, Athena, sub-agents, ReAct, Gapper, Mnemon, etc. |
| Manus-style multi-step | ✅ | CLI/API: TaskOrchestrator; MCP: AgentLoop (plan → execute → report). |
| Ira uses Mem0 | ✅ | UnifiedRetriever + Mem0 client; conversation/long-term memory. |
| Ira uses Neo4j | ✅ | KnowledgeGraph in retriever and pantheon. |
| Ira uses Postgres | ✅ | CRM, QuoteManager, pipeline-related state. |
| Ira uses Qdrant | ✅ | QdrantManager in UnifiedRetriever. |
| Reply back to Cursor for display | ✅ | CLI: JSON with `response`; API: SSE `final_answer`; MCP: return value. |
| Default: every message to Ira | ❌ | Only when user says @Ira / ask Ira / tell Ira. |
| All four containers up | ⚠️ | Verify qdrant + neo4j; at audit time only postgres + redis were up. |

---

## 5. Recommendations (concise)

1. **Trigger:** If the product goal is “every message in this chat goes to Ira”, add an explicit rule or mode that always runs `ira ask "<user message>" --json` (or `query_ira`) and displays the result; otherwise keep current explicit invocation.
2. **Infrastructure:** Ensure all four containers (qdrant, neo4j, postgres, redis) are up when using full stack; consider a small “start Ira” check that verifies them.
3. **CLI vs API pipeline:** Optionally align CLI `_build_pipeline()` with the server’s pipeline (optional subsystems) if you need feature parity.
4. **Documentation:** In `docs/CURSOR_WORKFLOWS.md` or README, state clearly: “Cursor is the front end: you ask Ira here; Cursor runs Ira’s full stack (CLI or API/MCP) and shows Ira’s reply.”
5. **Fallback:** When using Cursor-as-Ira fallback, always indicate that the full stack was unavailable and the answer is from the fallback workflow.

---

**Confidence:** High  
**Sources:** `src/ira/interfaces/cli.py`, `src/ira/interfaces/mcp_server.py`, `src/ira/interfaces/server.py`, `src/ira/pipeline.py`, `.cursor/rules/ira-api.mdc`, `.cursor/rules/ira-cursor-workflow.mdc`, `.cursor/agents/ira.md`, `docker-compose.local.yml`, `docs/CURSOR_WORKFLOWS.md`
