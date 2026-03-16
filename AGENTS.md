# Ira — Agent Instructions

Guidelines for AI coding assistants and human developers working on the
Ira v3 codebase. For Ira's identity and behavioral principles, see
[SOUL.md](SOUL.md). For project direction, see [VISION.md](VISION.md).

## Repository Overview

Ira is a multi-agent AI system built for Machinecraft. It processes requests
through a 17-step pipeline, delegates to 31 specialist agents, and maintains
persistent memory across conversations. Inside Cursor, Ira runs as a
**Cursor-native agentic experience** using an Explore → Think → Act → Loop
→ Result flow with bounded execution, parallel sub-agents, and progressive
disclosure of reasoning.

```
src/ira/
  agents/       # 31 specialist agents + BaseAgent
  brain/        # Retrieval, embeddings, graph, routing, pricing,
                #   entity extraction (GLiNER), guardrails (32 modules)
  memory/       # 10 memory subsystems + dream mode + goal sweep
  systems/      # Body-system metaphor (21 modules)
  interfaces/   # FastAPI server, CLI, MCP server, email processor, dashboard
  data/         # CRM models, quote models
  middleware/   # Auth, request context
  skills/       # Shared skill handlers
  schemas/      # Pydantic models for structured LLM outputs
  services/     # LLMClient (OpenAI + Anthropic SDK wrapper with Langfuse tracing)
  pipeline.py   # 17-step request pipeline
  pantheon.py   # Agent orchestrator + routing
  config.py     # Pydantic settings (all config from .env)
  message_bus.py # Inter-agent pub/sub messaging
prompts/        # LLM prompt templates (75 files)
tests/          # pytest test suite (28 files, ~13,700 lines)
alembic/        # PostgreSQL migrations
scripts/        # Operational + training scripts
web-ui/         # Next.js web interface (App Router + Tailwind CSS)
docs/           # ARCHITECTURE.md, SYSTEM_AUDIT.md
```

## The Pantheon

| Agent | Role | Domain |
|:------|:-----|:-------|
| **Athena** | Orchestrator | Routes requests, delegates, synthesizes multi-agent responses |
| **Alexandros** | Librarian | Raw document archive (data/imports/), fallback when KB is empty |
| **Arachne** | Content Scheduler | Newsletter assembly, content calendar, LinkedIn scheduling |
| **Artemis** | Lead Hunter | Mailbox intelligence, historical email scanning, customer journey mapping, missed lead detection; works with Alexandros for seed data |
| **Asclepius** | Quality | Punch lists, FAT/installation tracking, quality dashboards |
| **Atlas** | Project Manager | Project logbook, production schedules, payment milestones |
| **Cadmus** | CMO / Case Studies | Case studies, LinkedIn posts, NDA-safe content |
| **Calliope** | Writer | Emails, proposals, reports — all external communication |
| **Chiron** | Sales Trainer | Sales patterns, coaching notes for outreach |
| **Clio** | Researcher | Primary KB search via Qdrant/Neo4j/Mem0; falls back to Alexandros |
| **Delphi** | Oracle | Email classification, founder communication style simulation |
| **Gapper** | Gap Resolver | Finds and fills missing data in reports using email search, document archive, KB, web search, CRM, and inter-agent delegation |
| **Hephaestus** | Production | Machine specs, manufacturing processes, production status |
| **Hera** | Procurement | Vendors, components, lead times, inventory |
| **Hermes** | Marketing | Drip campaigns, regional tone, lead intelligence |
| **Iris** | External Intel | Web search, news APIs, company intelligence |
| **Mnemon** | Memory Guardian | Correction authority. Maintains the correction ledger and intercepts stale data at every retrieval point, overriding it with corrected truth |
| **Mnemosyne** | Memory | Long-term memory storage and retrieval via Mem0 |
| **Nemesis** | Trainer | Corrections, adversarial training, sleep training cycles |
| **Plutus** | Finance | Pricing, revenue, margins, budgets, quote analytics |
| **Populator** | CRM Populator | Hunts leads/customers across imports, 07_Leads, Neo4j, KB, Gmail; classifies client vs lead; enriches via web/scraping (Iris); adds to CRM with full detail |
| **Prometheus** | Sales / CRM | CRM pipeline, deals, conversion rates, sales strategy; tracks all emails sent to each contact (what, when); gets punch list from Asclepius/Atlas; logs customer complaints and resolutions in CRM |
| **Quotebuilder** | Quotes | Structured formal quotes with specs, pricing, delivery; auto-creates CRM deals |
| **Sophia** | Reflector | Post-interaction reflection, pattern detection, quality scoring |
| **Sphinx** | Gatekeeper | Detects vague queries, generates clarifying questions |
| **Themis** | HR | Employees, headcount, policies, salary data |
| **Tyche** | Forecasting | Pipeline forecasts, win/loss predictions, deal velocity |
| **Vera** | Fact Checker | Verifies claims against KB, detects hallucinations |
| **Aegis** | Content Safety / DLP | Scans outbound content for PII, confidential terms, data leakage; runs in pipeline before shaping |
| **Aletheia** | Compliance / Provenance | Traces claims to sources (Qdrant, Neo4j, CRM); flags unverifiable assertions; runs in pipeline before shaping |
| **Graphe** | Logger / Scribe | Records Cursor chat sessions to SQLite for dream/sleep learning; runs at end of pipeline |
| **Metis** | Stability Monitor | Scores response quality (0-100), tracks rolling average, announces when system is stable; auto-adjusts max_rounds |

## Development Commands

Ira runs **CLI-first**: no API server is required. Cursor (or any caller) runs `ira ask` and `ira task` from the project root; the full stack (agents, RAG, Postgres, Qdrant, Neo4j, Mem0) runs in-process.

```bash
# Install
poetry install

# Infrastructure (Qdrant, Neo4j, PostgreSQL, Redis) — start only these; no uvicorn
docker compose -f docker-compose.local.yml up -d

# Database migrations
alembic upgrade head

# Interactive CLI
poetry run ira chat

# Single query (--json for Cursor/scripts: stdout only)
poetry run ira ask "What's the lead time for a PF1?"
poetry run ira ask "What's the lead time for a PF1?" --json

# Multi-phase task (plan → execute → report)
poetry run ira task "Full analysis of Acme deal and draft a proposal" --json

# Tests
poetry run pytest
poetry run pytest tests/test_agents.py          # specific file
poetry run pytest -k "test_clio"                # specific test

# Other commands
poetry run ira dream      # memory consolidation
poetry run ira board      # board meeting
poetry run ira ingest     # document ingestion
poetry run ira health     # vital signs
poetry run ira crm sync-apollo   # sync CRM with Apollo (contacts + companies enrichment)
poetry run ira feedback "Correction text"        # record a correction

# Email commands
poetry run ira email sync                           # one-time inbox poll
poetry run ira email learn --thread-id "18f3a..."   # learn from a thread
poetry run ira email rescan --after 2023/01/01      # deep historical scan
poetry run ira email rescan --dry-run --resume      # resume a previous scan

# Optional: Run the API server (for web UI or HTTP integrations)
# Only one Ira process (CLI or server) should use the same data dir at a time; see docs/TROUBLESHOOTING.md.
poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000 --limit-concurrency 5 --timeout-keep-alive 30

# Web UI (Next.js) — requires API server
cd web-ui && npm install && npm run dev             # http://localhost:3000
```

## Code Conventions

### Python style

- `from __future__ import annotations` at the top of every module.
- stdlib `logging` only. Get a logger with `logger = logging.getLogger(__name__)`.
- Type hints required on all public functions.
- Async functions use `async def` / `await`. Never `asyncio.run()` inside async code.

### LLM calls

- Use the centralised `LLMClient` in `src/ira/services/llm_client.py`. Do not use raw `httpx` for LLM calls.
- For structured JSON responses, use `generate_structured()` with a Pydantic model from `src/ira/schemas/llm_outputs.py`.
- For plain text responses, use `generate_text()` or `generate_text_with_fallback()`.
- OpenAI calls are auto-traced via `langfuse.openai.AsyncOpenAI`. Anthropic calls use `@observe()` decorators.
- Embeddings go through `EmbeddingService` (Voyage AI via httpx).

### Agent development

- Every agent inherits from `BaseAgent` and implements `async def handle(self, query, context)`.
- Call `await self.run(query, context)` to enter the ReAct loop. Only bypass for deterministic fast-path logic.
- Register custom tools in `_register_tools()` via `self.register_tool(AgentTool(...))`.
- Agent `name` class attribute must be lowercase and match the filename (e.g. `"clio"` → `clio.py`).
- System prompts live in `prompts/{agent_name}_system.txt`. Use `load_prompt()`, never inline strings.

### Shared identity (SOUL.md)

- `prompt_loader.load_soul_preamble()` extracts Identity, Voice, and Behavioral Boundaries from `SOUL.md`.
- `BaseAgent.run()` prepends this preamble to every agent's system prompt automatically.
- Do not duplicate SOUL.md content in individual agent prompts.

### Memory access

- Agents use ReAct tools: `recall_memory`, `store_memory`, `get_conversation_history`, `check_relationship`, `check_goals`, `recall_episodes`.
- These are auto-registered by `BaseAgent._register_default_tools()` when the service is available.
- Direct memory access in `handle()` is reserved for Mnemosyne and Nemesis.

### Email tools

- When the email processor is injected (`SK.EMAIL_PROCESSOR`), all agents automatically get `search_emails` and `read_email_thread` tools.
- These allow any agent to search Gmail and read full threads as part of their ReAct reasoning.
- Registered in `BaseAgent._register_default_tools()` — no per-agent setup needed.

### Prompts

- Agent system prompts: `prompts/{agent_name}_system.txt`
- Task prompts: `prompts/{module_or_task}.txt`
- Template variables use `{variable_name}` for `.format()` substitution.
- Keep prompts under 2000 tokens where possible.
- Never embed API keys, file paths, or env-specific values in prompts.

### Testing

- Tests in `tests/`. Framework: `pytest` + `pytest-asyncio` with `asyncio_mode = "auto"`.
- Mock all external services (LLM APIs, Qdrant, Neo4j, Mem0) in tests.
- Mock `LLMClient.generate_structured` and `LLMClient.generate_text` (not raw httpx).
- Return Pydantic model instances (e.g. `ReActDecision`) from mocks, not JSON strings.

## Creating a New Agent

1. Create `src/ira/agents/{name}.py` inheriting from `BaseAgent`.
2. Set class attributes: `name`, `role`, `description`, `knowledge_categories`.
3. Implement `_register_tools()` with custom tools via `self.register_tool()`.
4. Implement `handle()` — typically `await self.run(query, context)`.
5. Create `prompts/{name}_system.txt` following the conventions in SOUL.md.
6. Register the class in `src/ira/pantheon.py` → `_AGENT_CLASSES`.
7. Add the agent to the table in this file and in `prompts/athena_system.txt`.
8. Write tests in `tests/test_agents.py`.

## Database Migrations

After changing models in `src/ira/data/crm.py` or `src/ira/data/quotes.py`:

```bash
alembic revision --autogenerate -m "description of change"
alembic upgrade head
```

## Infrastructure

| Service | Image | Port | Purpose |
|:--------|:------|:-----|:--------|
| Qdrant | `qdrant/qdrant:latest` | 6333 | Vector DB for document embeddings |
| Neo4j | `neo4j:5.15.0-community` | 7474/7687 | Knowledge graph |
| PostgreSQL | `postgres:16` | 5432 | CRM relational data |
| Redis | `redis:7-alpine` | 6379 | Response dedup, message stream persistence, caching |

Local dev: `docker-compose.local.yml`. All config comes from `.env`.

## Request Pipeline (17 steps)

Every request flows through `RequestPipeline.process_request()`:

```
 1. PERCEIVE        — SensorySystem resolves identity, emotional state
 2. REMEMBER        — ConversationMemory, coreference resolution, goals
 2.5 FAST PATH      — Regex classifier for greetings/identity/thanks
 2.7 SPHINX GATE    — Sphinx evaluates query clarity; vague → clarify
 3. ROUTE (Fast)    — DeterministicRouter keyword-matched intents
 3.5 TRUTH HINTS    — Canned answers for known factual questions
 4. ROUTE (Proc)    — ProceduralMemory for learned response patterns
 5. ROUTE (LLM)     — Athena for open-ended LLM-based routing
 5.1 EMAIL SCOPE    — Classify query as live_email/imported_email/both/no_email
 5.5 ENRICH         — AdaptiveStyle, RealTimeObserver, Endocrine, episodes
 6. EXECUTE         — Routed agents run (up to 5 in parallel, per-agent timeout)
 6.1a COMPLIANCE    — Aletheia traces claims to sources (provenance)
 6.1b DLP           — Aegis scans for PII and confidential terms
 6.2 CORRECTIONS    — Mnemon applies correction ledger
 6.3 GAP RESOLVE    — Gapper fills missing data
 6.4 FAITHFULNESS   — 4-tier grounding check (see below)
 6.4b GUARDRAILS    — Competitor mentions, confidentiality (LLM-routed only)
 7. ASSESS          — Metacognition confidence scoring
 8. REFLECT         — InnerVoice reflection
 8.5 SOURCE NOTES   — Auto-append limitation notes on timeout/failure
 9. SHAPE           — VoiceSystem formats for channel and recipient
 9.5 LOG SESSION    — Graphe records Cursor session for dream learning
 9.6 STABILITY      — Metis scores response quality (0-100)
10. LEARN           — ConversationMemory, CRM, facts, Sophia, goals
11. RETURN          — Final shaped response
```

## Faithfulness Engine (4-tier)

Faithfulness checking verifies that every claim in the response is
grounded in source evidence. Uses a tiered strategy with automatic
fallback:

| Tier | Engine | Speed | Cost | Notes |
|:-----|:-------|:------|:-----|:------|
| 0 | **Google Check Grounding** (Discovery Engine API) | <700ms | Free tier | Per-claim citations; requires `GOOGLE_CLOUD_PROJECT_ID` |
| 1 | **Dual-model LLM** (gpt-4.1 + Claude Sonnet in parallel) | ~3s | ~$0.006 | Averaged scores; catches model-specific blind spots |
| 2 | **Single-model LLM** (gpt-4.1 only) | ~1s | ~$0.003 | Fallback when Anthropic is unavailable |
| 3 | **Keyword heuristic** (word overlap) | <50ms | Free | Last resort when all APIs are down |

The pipeline will not hard-block a response when agents did real work;
instead it appends a verification caveat. On exception, it logs and
continues rather than replacing the response.

Config: `src/ira/brain/guardrails.py`. Prompt: `prompts/faithfulness_check.txt`.

## Timeout Model

Bounded execution ensures Ira returns the best possible answer within
a time budget. See `docs/TIMEOUT_MODEL.md` for full details.

| Level | Config | Default | Meaning |
|:------|:-------|:--------|:--------|
| **Total** | `APP__PIPELINE_TIMEOUT` | 600s | Full request; presets: 30s / 2m / 5m / 10m / 20m |
| **Sub-agent slot** | `APP__AGENT_TIMEOUT` | 90s | Per parallel sub-agent; best answer within this |
| **Parallel cap** | `APP__MAX_PARALLEL_AGENTS` | 5 | Up to this many sub-agents at once (semaphore) |
| **Athena synthesis** | `APP__ATHENA_SYNTHESIS_TIMEOUT` | 90s | Time to package final answer for Cursor/API |
| **ReAct rounds** | `APP__REACT_MAX_ITERATIONS` | 8 | Max think-act-observe cycles per agent |

Metis (stability monitor) tracks response quality and can auto-adjust
`react_max_iterations` when quality is below threshold.

## Cursor-Native Experience

Inside Cursor, Ira runs using the **agentic flow** by default:

1. **Explore** — Search codebase, data, docs (SemanticSearch, Grep, Read)
2. **Think** — Reason in plain language; decide next step
3. **Act** — Run commands, call Ira CLI/stream, read more files
4. **Loop** — If incomplete, think again → explore or act again
5. **Result** — Final answer with confidence/freshness/sources

All output is formatted for the Cursor chat tab. No external UI required.
CLI (`ira ask`) is the backend; the experience is Cursor-native.

Rules: `.cursor/rules/ira-cursor-native.mdc`, `ira-cursor-agentic-mode.mdc`.
Docs: `docs/CURSOR_AGENTIC_LOOP.md`, `docs/CURSOR_EMAIL_SCOPE.md`.

## Email in Cursor

| Path | Speed | When to use |
|:-----|:------|:------------|
| **Qdrant (highway)** | Sub-second | Historical context, "what do we know about X" |
| **Live Gmail** | 1-5s | "Latest email from X", real-time inbox state |

The pipeline classifies each query's email scope (`live_email`,
`imported_email`, `both`, `no_email`) and agents respect it.
Send is only allowed on explicit user instruction ("send" / "send it").

Playbooks: `docs/stable_modes.md` (6 documented flows).

## Qdrant Resilience

- **Filter fallback**: If a filtered search fails (missing payload index),
  retries without the filter so the user still gets results.
- **Auto-indexes**: `ensure_collection()` creates payload indexes for
  commonly filtered fields (`source_category`, `doc_type`, `source`, etc.)
  — required by Qdrant Cloud.
- **Graceful counts**: `count_by_source_category` returns 0 instead of
  crashing when the index is missing.

## API Endpoints

Queries are normally run via the CLI (`ira ask`, `ira task`). The API is used when the server is explicitly started (e.g. for the web UI or MCP).

| Method | Path | Description |
|:-------|:-----|:------------|
| POST | `/api/query` | Send a message to Ira |
| POST | `/api/query/stream` | SSE streaming query with live progress events |
| POST | `/api/feedback` | Submit a correction |
| GET | `/api/health` | Quick health check |
| GET | `/api/deep-health` | Detailed service-by-service health |
| GET | `/api/pipeline` | Sales pipeline summary |
| GET | `/api/agents` | List agents and status |
| POST | `/api/ingest` | Ingest a document |
| POST | `/api/crm/sync-apollo` | Sync CRM with Apollo (contacts + companies enrichment) |
| POST | `/api/reingest-scanned` | Re-OCR scanned PDFs via Document AI |
| POST | `/api/board-meeting` | Trigger a board meeting |
| GET | `/api/dream-report` | Trigger dream cycle and return report |
| POST | `/api/task/stream` | Multi-phase task execution with SSE streaming |
| POST | `/api/task/clarify` | Resume a task after clarification |
| POST | `/api/email/search` | Search Gmail with filters (from, subject, date) |
| GET | `/api/email/thread/{id}` | Fetch full email thread by Gmail thread ID |
| POST | `/api/email/draft` | Draft an email via Calliope |
| POST | `/api/email/send` | Send an email (only when user explicitly said "send"; requires OPERATIONAL mode) |
| POST | `/api/email/rescan` | Deep historical scan with SSE progress streaming |
| GET | `/api/email/rescan` | Check status of running/last rescan |
| GET | `/api/corrections` | List recent corrections (filterable by status) |
| GET | `/api/reingest-scanned` | Check reingest status |
| GET | `/api/vendors` | List all vendors |
| POST | `/api/vendors` | Create a vendor |
| GET | `/api/vendors/payables` | Payables summary across all vendors |
| GET | `/api/vendors/overdue` | Overdue vendor payables |
| POST | `/api/vendors/payables` | Record a new vendor payable/invoice |

## MCP Tools (Cursor Integration)

The MCP server (`src/ira/interfaces/mcp_server.py`) exposes 35+ tools for
use in Cursor, Claude Desktop, or any MCP-compatible client:

| Category | Tools |
|:---------|:------|
| **Pipeline** | `query_ira`, `search_knowledge`, `search_crm`, `get_pipeline_summary`, `ask_agent` |
| **Email** | `search_emails`, `read_email_thread`, `draft_email` |
| **Memory** | `recall_memory`, `store_memory`, `get_conversation_history`, `check_relationship`, `check_goals` |
| **CRM** | `get_deal`, `list_deals`, `create_contact`, `update_deal`, `get_stale_leads`, `sync_crm_apollo` |
| **Knowledge Graph** | `find_related_entities`, `find_company_contacts`, `find_company_quotes` |
| **Corrections** | `submit_correction` — log factual corrections for Nemesis to process during Dream Mode |
| **Dream Mode** | `trigger_dream_mode` — run the 12-stage memory consolidation cycle on demand (includes cursor session learning) |
| **Board Meeting** | `convene_board_meeting` — multi-agent strategic debate with Athena synthesis |
| **Metacognition** | `get_knowledge_gaps` — see what Ira doesn't know so you can upload the right documents |
| **System Health** | `get_system_status` — service health (Qdrant, Neo4j, PostgreSQL, OpenAI, Voyage) + agent power levels |
| **Web** | `web_search`, `scrape_url` |
| **Projects** | `get_project_status`, `get_overdue_milestones` |
| **Agent Loop** | `plan_task`, `execute_phase`, `generate_report` |

## Web UI

A Next.js web interface lives in `web-ui/` for team members who don't use
Cursor or Telegram. It connects to the FastAPI backend via SSE streaming.

```bash
cd web-ui
npm install
npm run dev   # → http://localhost:3000
```

Set `CORS_ORIGINS=http://localhost:3000` in the backend `.env`. If the
backend has `API_SECRET_KEY` set, add `NEXT_PUBLIC_IRA_API_KEY=<key>` to
`web-ui/.env.local`.

Pages:

- `/chat` — Pantheon Chat with agent selector, SSE streaming, feedback buttons
- `/crm` — Pipeline kanban, vendor payables table, email search
- `/board-meeting` — Multi-agent strategic discussions with split-screen results
- `/corrections` — Corrections log with stats and filtering

Features: shadcn/ui components, SWR data fetching, real-time SSE progress
indicators, Markdown/GFM table rendering, toast notifications, authenticated
API calls.

## Important Rules

- **Never fabricate Ira's responses.** When testing via the API, always use
  real curl output. Do not invent answers.
- **Never commit `.env` or credentials.** Use `.env.example` for templates.
- **Keep agents bounded.** If a new capability overlaps with an existing
  agent, extend that agent. Do not create overlapping agents.
- **No heavy frameworks.** No LangChain, LlamaIndex, or CrewAI. LLMClient
  for LLM calls (with Langfuse tracing), custom ReAct loop, custom retrieval.
- **Prompts are config.** System prompts live in `prompts/`, not in Python
  source. Use `load_prompt()`.
- **The body metaphor is real.** Body systems enforce separation of concerns.
  Don't merge them. If something doesn't fit, create a new system.
