# Ira — Agent Instructions

Guidelines for AI coding assistants and human developers working on the
Ira v3 codebase. For Ira's identity and behavioral principles, see
[SOUL.md](SOUL.md). For project direction, see [VISION.md](VISION.md).

## Repository Overview

Ira is a multi-agent AI system built for Machinecraft. It processes requests
through an 11-stage pipeline, delegates to 24 specialist agents, and maintains
persistent memory across conversations.

```
src/ira/
  agents/       # 24 specialist agents + BaseAgent
  brain/        # Retrieval, embeddings, graph, routing, pricing,
                #   entity extraction (GLiNER), guardrails (30 modules)
  memory/       # 9 memory subsystems + dream mode + goal sweep
  systems/      # Body-system metaphor (20 modules)
  interfaces/   # FastAPI server, CLI, Telegram, email processor, dashboard, cursor feedback
  data/         # CRM models, quote models
  middleware/   # Auth, request context
  skills/       # Shared skill handlers
  schemas/      # Pydantic models for structured LLM outputs
  services/     # LLMClient (OpenAI + Anthropic SDK wrapper with Langfuse tracing)
  pipeline.py   # 11-stage request pipeline
  pantheon.py   # Agent orchestrator + routing
  config.py     # Pydantic settings (all config from .env)
  message_bus.py # Inter-agent pub/sub messaging
prompts/        # LLM prompt templates (68 files)
tests/          # pytest test suite (23 files, ~10,600 lines)
alembic/        # PostgreSQL migrations
scripts/        # Operational + training scripts
docs/           # ARCHITECTURE.md, SYSTEM_AUDIT.md
```

## The Pantheon

| Agent | Role | Domain |
|:------|:-----|:-------|
| **Athena** | Orchestrator | Routes requests, delegates, synthesizes multi-agent responses |
| **Alexandros** | Librarian | Raw document archive (data/imports/), fallback when KB is empty |
| **Arachne** | Content Scheduler | Newsletter assembly, content calendar, LinkedIn scheduling |
| **Asclepius** | Quality | Punch lists, FAT/installation tracking, quality dashboards |
| **Atlas** | Project Manager | Project logbook, production schedules, payment milestones |
| **Cadmus** | CMO / Case Studies | Case studies, LinkedIn posts, NDA-safe content |
| **Calliope** | Writer | Emails, proposals, reports — all external communication |
| **Chiron** | Sales Trainer | Sales patterns, coaching notes for outreach |
| **Clio** | Researcher | Primary KB search via Qdrant/Neo4j/Mem0; falls back to Alexandros |
| **Delphi** | Oracle | Email classification, founder communication style simulation |
| **Hephaestus** | Production | Machine specs, manufacturing processes, production status |
| **Hera** | Procurement | Vendors, components, lead times, inventory |
| **Hermes** | Marketing | Drip campaigns, regional tone, lead intelligence |
| **Iris** | External Intel | Web search, news APIs, company intelligence |
| **Mnemosyne** | Memory | Long-term memory storage and retrieval via Mem0 |
| **Nemesis** | Trainer | Corrections, adversarial training, sleep training cycles |
| **Plutus** | Finance | Pricing, revenue, margins, budgets, quote analytics |
| **Prometheus** | Sales | CRM pipeline, deals, conversion rates, sales strategy |
| **Quotebuilder** | Quotes | Structured formal quotes with specs, pricing, delivery; auto-creates CRM deals |
| **Sophia** | Reflector | Post-interaction reflection, pattern detection, quality scoring |
| **Sphinx** | Gatekeeper | Detects vague queries, generates clarifying questions |
| **Themis** | HR | Employees, headcount, policies, salary data |
| **Tyche** | Forecasting | Pipeline forecasts, win/loss predictions, deal velocity |
| **Vera** | Fact Checker | Verifies claims against KB, detects hallucinations |

## Development Commands

```bash
# Install
poetry install

# Infrastructure (Qdrant, Neo4j, PostgreSQL, Redis)
docker compose -f docker-compose.local.yml up -d

# Database migrations
alembic upgrade head

# Run the server
poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000 --limit-concurrency 5 --timeout-keep-alive 30

# Interactive CLI
poetry run ira chat

# Single query
poetry run ira ask "What's the lead time for a PF1?"

# Tests
poetry run pytest
poetry run pytest tests/test_agents.py          # specific file
poetry run pytest -k "test_clio"                # specific test

# Other commands
poetry run ira dream      # memory consolidation
poetry run ira board      # board meeting
poetry run ira ingest     # document ingestion
poetry run ira health     # vital signs
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

## API Endpoints

| Method | Path | Description |
|:-------|:-----|:------------|
| POST | `/api/query` | Send a message to Ira |
| POST | `/api/feedback` | Submit a correction |
| GET | `/api/health` | Quick health check |
| GET | `/api/deep-health` | Detailed service-by-service health |
| GET | `/api/pipeline` | Sales pipeline summary |
| GET | `/api/agents` | List agents and status |
| POST | `/api/ingest` | Ingest a document |
| POST | `/api/reingest-scanned` | Re-OCR scanned PDFs via Document AI |
| POST | `/api/board-meeting` | Trigger a board meeting |
| GET | `/api/dream-report` | Trigger dream cycle and return report |
| POST | `/api/email/search` | Search Gmail with filters (from, subject, date) |
| GET | `/api/email/thread/{id}` | Fetch full email thread by Gmail thread ID |
| POST | `/api/email/draft` | Draft an email via Calliope |

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
