<p align="center">
  <img src="docs/assets/ira-logo.png" alt="Ira" width="200">
</p>

<h1 align="center">Ira v3</h1>

<p align="center">
  <strong>The AI that runs a manufacturing company. No, seriously.</strong>
</p>

<p align="center">
  <a href="https://github.com/doshirush1901/ira-v3/actions/workflows/ci.yml"><img src="https://github.com/doshirush1901/ira-v3/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Code style: ruff"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-proprietary-red.svg" alt="License: Proprietary"></a>
</p>

---

## Guides

| Guide | Description |
|:------|:------------|
| **[Why Ira?](docs/WHY_IRA.md)** | What Ira does, why it exists, and real use cases — email intelligence, agent loop, board meetings, dream cycles |
| **[Getting Started](docs/GETTING_STARTED.md)** | Step-by-step setup: prerequisites, installation, configuration, and first interactions |
| **[Cursor rules & workflows](docs/CURSOR_WORKFLOWS.md)** | Index of all custom workflows: start/query/task, email reply flow, feedback, ingest, fallback, stable modes, lead engagement |

## Table of Contents

- [Wait, What Is This?](#wait-what-is-this)
- [The 5-Minute Setup (Cursor + Gmail = Email Intelligence)](#the-5-minute-setup-cursor--gmail--email-intelligence)
- [How It Actually Works](#how-it-actually-works)
- [The Agent Loop](#the-agent-loop)
- [The Pantheon](#the-pantheon)
- [The Brain](#the-brain)
- [Memory Architecture](#memory-architecture)
- [The Body Systems](#the-body-systems)
- [Shared Identity](#shared-identity)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Cursor rules & workflows](docs/CURSOR_WORKFLOWS.md)
- [API Endpoints](#api-endpoints)
- [Running Tests](#running-tests)
- [Contributing](#contributing)
- [Architecture Deep Dive](#architecture-deep-dive)
- [Changelog](#changelog)

---

## Wait, What Is This?

Let's start with a problem you already have.

You run a business. Or you work at one. Every day, emails come in. Leads asking about pricing. Vendors confirming delivery dates. A client from six months ago resurfacing with "hey, are you still doing that thing we discussed?" Your inbox is a firehose of context that you're supposed to *just remember*.

Now, most people solve this one of two ways:

**Option A: The Human Way.** You read every email. You mentally file it. You remember that Erik from Acme Packaging asked about a thermoforming machine in March, that the quote was EUR 180k, that he went quiet in April, and that his colleague Lars mentioned they're expanding their Hamburg facility. You remember all of this because you are a superhuman with infinite working memory. (You are not.)

**Option B: The CRM Way.** You buy Salesforce. You hire someone to enter data into Salesforce. Nobody enters data into Salesforce. You now have a very expensive database of nothing.

**Option C: This repo.**

Ira is a multi-agent AI system built for [Machinecraft](https://machinecraft.org) — an industrial machinery company that designs and manufactures thermoforming, panel forming, and packaging machines. But here's the thing that makes it different from every other "AI assistant" repo on GitHub:

**Ira doesn't just answer questions. It reads your email, remembers your relationships, knows your products, tracks your deals, and gets smarter every day.** It has 27 specialist AI agents — each named after a figure from Greek mythology, each with a specific job — and they collaborate through an 11-stage pipeline that mimics how a real organization processes information.

Think of it like this: you don't walk into a company and ask the receptionist to design your machine, draft your quote, check your invoice, *and* write your marketing email. You talk to the right person. Ira figures out who that person is, briefs them, and delivers the result.

The best part? **You can set this up in Cursor in about 5 minutes and turn your IDE into an email intelligence system.**

## The 5-Minute Setup (Cursor + Gmail = Email Intelligence)

Here's the thing nobody tells you about AI coding assistants: they can do a lot more than write code. Cursor has a shell, it can make HTTP requests, it can follow rules, and — critically — it supports MCP (Model Context Protocol) tools. So we gave it 30 of them.

When you open this repo in Cursor, three things happen automatically:

1. **Cursor becomes Ira.** The `.cursor/rules/` directory teaches Cursor how to run Ira **without starting the API server**: start Docker (databases only), run `ira ask` and `ira task` from the CLI so the full agent stack and RAG run locally, and fall back to a codebase-and-data workflow if the CLI fails. The `.cursor/agents/ira.md` file registers Ira as a Cursor subagent with 30 MCP tools. No uvicorn required.

2. **You get natural language access to your entire business.** Say "wake up Ira" in Cursor chat (Cursor starts Docker for Postgres, Qdrant, Neo4j, Redis). Then ask things like:
   - *"@Ira find all emails from Erik at Acme Packaging"*
   - *"@Ira what's the latest on the PF1 quote for GlobalPack?"*
   - *"@Ira draft a follow-up to the vendor who hasn't replied about the servo motors"*
   - *"@Ira prepare a quarterly business review covering sales, production, and finance"*

3. **Every answer is grounded in real data.** Ira doesn't hallucinate your email history. It searches Gmail directly, pulls the actual threads, cross-references them with your knowledge base and CRM, and gives you an answer with receipts. For complex requests, the Agent Loop breaks work into phases, executes them through specialist agents, and compiles professional deliverables.

### Quick Start

```
Step 1:  Clone this repo and open it in Cursor
Step 2:  Copy .env.example → .env, add your API keys
Step 3:  Type "wake up Ira" in Cursor chat (Cursor starts Docker for DBs only)
Step 4:  Ask Ira anything — Cursor runs ira ask "<question>" --json or the fallback workflow
Step 5:  For complex tasks ("full analysis", "prepare a report"), Cursor runs ira task "<goal>" --json
```

That's it. Cursor reads `.cursor/rules/ira-api.mdc` and `.cursor/rules/ira-cursor-workflow.mdc`, starts Docker (no API server), runs the CLI when you ask, and falls back to codebase/data search if the CLI isn't available. You just talk to it.

### What It Looks Like in Practice

```
You:     @Ira show me all emails from acme-packaging.com in the last 3 months

Ira:     Found 7 emails from acme-packaging.com:
         - [2026-01-15] Erik Janssen — RE: PF1 Thermoforming Quote
         - [2026-01-22] Erik Janssen — Delivery timeline question
         - [2026-02-03] Lars Andersen — Hamburg facility expansion
         ...

You:     @Ira what's the status of the Acme Packaging deal?

Ira:     [Prometheus consulted]
         Acme Packaging (Erik Janssen) — NEGOTIATION stage
         Quote: EUR 180,000 for PF1-C thermoforming machine
         Last contact: Feb 3 — Lars mentioned Hamburg expansion
         Risk: 45 days since last response from Erik
         Suggested action: Follow up referencing the expansion plans

You:     @Ira draft that follow-up

Ira:     [Calliope consulted]
         Subject: PF1 for Hamburg — quick check-in
         ...
```

Every agent that contributed is named. Every fact traces to a real email or document. If Ira isn't sure, it says so.

> **Note:** Email mode defaults to TRAINING — Ira reads your inbox and creates drafts but never sends anything without your explicit approval. Set `IRA_EMAIL_MODE=OPERATIONAL` in `.env` only when you're ready for live sending.

## How It Actually Works

Every message — whether it comes from the CLI or the REST API — flows through an **11-stage pipeline** that mimics how a human organization processes a request:

```
  You say something
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                      REQUEST PIPELINE                         │
│                                                              │
│   1. PERCEIVE       → Who are you? What's your mood?         │
│   2. REMEMBER       → What have we talked about before?      │
│   3. ROUTE (Fast)   → Keyword match → agent (deterministic)  │
│      TRUTH HINTS    → Short-circuit with cached fact?        │
│   4. ROUTE (Proc)   → Match learned response patterns        │
│   5. ROUTE (LLM)    → Athena picks the right specialist      │
│      ENRICH         → Adaptive style, learnings, hormones    │
│   6. EXECUTE        → Agent does the work (ReAct loop)       │
│   7. ASSESS         → How confident are we in this answer?   │
│   8. REFLECT        → Post-response self-reflection          │
│   9. SHAPE          → Format for your channel & preferences  │
│  10. LEARN          → Store memories, update CRM, goals      │
│  11. RETURN         → Final shaped response                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
  You get a response that actually knows what it's talking about
```

Routing is a three-tier cascade: a fast **deterministic router** catches obvious intents (keywords → agent), **procedural memory** matches learned patterns, and if neither fires, **Athena** (the orchestrator agent) uses LLM reasoning to pick the right specialist. A **truth hints** cache can short-circuit the whole pipeline for common factual queries.

## The Agent Loop

The 11-stage pipeline handles single-turn questions. But what about complex, multi-step tasks — "prepare a quarterly business review," "analyze the European pipeline and draft a proposal," "investigate quality issues and recommend fixes"?

For these, Ira uses an **Agent Loop** — an iterative Plan-Execute-Observe-Compile cycle that wraps the pipeline:

```
  Complex request
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                        AGENT LOOP                            │
│                                                              │
│   1. PLAN      → Athena breaks request into phases,          │
│                  assigns specialist agents to each            │
│                                                              │
│   2. EXECUTE   → Run one phase at a time through agents      │
│                  (each agent uses the 11-stage pipeline)      │
│                                                              │
│   3. OBSERVE   → Athena evaluates results:                   │
│                  continue | replan | clarify | complete       │
│                                                              │
│   4. COMPILE   → Calliope synthesizes all findings into      │
│                  a professional report                        │
│                                                              │
│   Loop back to EXECUTE (or PLAN if replanning)               │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
  Professional deliverable with executive summary,
  data tables, and recommendations
```

The observe step is the key differentiator: after each phase, Athena reviews results and can re-plan if new information changes the approach, request clarification from the user, or mark the task complete early. This is exposed via three MCP tools (`plan_task`, `execute_phase`, `generate_report`) and via SSE streaming at `/api/task/stream`.

## The Pantheon

Twenty-seven agents. Each with a name from Greek mythology, a specific role, and their own set of tools.

### The C-Suite

| Agent | Role | What They Do |
|:------|:-----|:-------------|
| **Athena** | CEO / Orchestrator | Routes requests, delegates to specialists, synthesizes multi-agent responses |
| **Prometheus** | Sales (CRO) | Manages the CRM, tracks deals, analyzes the pipeline |
| **Hermes** | Marketing (CMO) | Drip campaigns, regional outreach, lead intelligence |
| **Plutus** | Finance (CFO) | Pricing, quotes, financial analysis |
| **Hephaestus** | Production (CPO) | Machine specs, production timelines, technical knowledge |
| **Themis** | HR (CHRO) | Employee data, policies, org charts |
| **Tyche** | Forecasting | Pipeline forecasts, win/loss analysis, revenue projections |

### The Specialists

| Agent | Role | What They Do |
|:------|:-----|:-------------|
| **Clio** | Researcher | Deep research across Qdrant, Neo4j, web, and the archive |
| **Calliope** | Writer | Drafts and polishes emails, proposals, reports |
| **Vera** | Fact Checker | Verifies claims against the knowledge base |
| **Sphinx** | Gatekeeper | Catches vague queries, asks clarifying questions |
| **Quotebuilder** | Quote Builder | Generates structured quotes with specs and pricing; auto-creates CRM deals |
| **Mnemosyne** | Memory Keeper | Long-term memory storage and retrieval |
| **Nemesis** | Trainer | Correction ingestion, adversarial testing, sleep training |
| **Iris** | Intelligence | Web search, news monitoring, company research |
| **Delphi** | Oracle | Email classification, communication style simulation |
| **Sophia** | Reflector | Post-interaction reflection and quality scoring |
| **Alexandros** | Librarian | Raw document archive — the fallback when everything else is empty |
| **Arachne** | Content Scheduler | Newsletter assembly, LinkedIn scheduling |
| **Cadmus** | Case Studies | Builds case studies from project data |
| **Chiron** | Sales Trainer | Maintains sales patterns, provides coaching notes |
| **Atlas** | Project Manager | Project logbook, production schedules, milestone tracking |
| **Asclepius** | Quality | Punch lists, installation tracking, quality dashboards |
| **Hera** | Procurement | Vendor management, component taxonomy, lead times |
| **Mnemon** | Memory Guardian | Correction authority — maintains the correction ledger, overrides stale data |
| **Gapper** | Gap Resolver | Finds and fills missing data using email, documents, KB, and web search |
| **Artemis** | Lead Hunter | Mailbox intelligence, historical email scanning, missed lead detection |

Every agent runs a **ReAct loop** (Reason → Act → Observe) with up to 8 iterations, calling tools, reading results, and reasoning about next steps until they have a complete answer. Default tools include knowledge search, memory recall, inter-agent delegation, and — when Gmail is connected — `search_emails` and `read_email_thread` for pulling real email data into any agent's reasoning.

## The Brain

Ira doesn't just generate text — it *knows things*. The brain is a multi-backend retrieval system:

```
            ┌─────────────────────────────────┐
            │       UnifiedRetriever           │
            │   (single entry point for all    │
            │    knowledge retrieval)           │
            └──────┬──────┬──────┬────────────┘
                   │      │      │
          ┌────────┘      │      └────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │  Qdrant  │   │  Neo4j   │   │   Mem0   │
    │ (vectors)│   │ (graph)  │   │ (memory) │
    └──────────┘   └──────────┘   └──────────┘
    Semantic        Entities &     Long-term
    search over     relationships  conversational
    documents       (companies,    memory
          │         people,
          │         machines)
          ▼
    ┌──────────────────────────────────┐
    │  Reranking                       │
    │  Voyage Rerank (primary)         │
    │  FlashRank (local fallback)      │
    └──────────────────────────────────┘
          │
          ▼
    ┌──────────────────────────────────┐
    │  Redis Cache                     │
    │  Response dedup + caching        │
    └──────────────────────────────────┘

    ┌──────────────────────────────────┐
    │  Entity Extractor (GLiNER)       │
    │  Zero-shot NER for contacts,     │
    │  companies, machines             │
    └──────────────────────────────────┘

    ┌──────────────────────────────────┐
    │  Guardrails                      │
    │  Input validation + output       │
    │  safety checks                   │
    └──────────────────────────────────┘
```

All three backends are searched **in parallel**, results are **reranked** with Voyage Rerank (FlashRank as local fallback), and if nothing comes back, the system falls back to **Alexandros** (the librarian) who searches the raw document archive. Redis caches responses and deduplicates repeated queries. The **entity extractor** (GLiNER for local zero-shot NER, complemented by LLM extraction) identifies contacts, companies, and machines in queries for entity-aware routing. **Guardrails AI** validates outputs for PII and toxicity (via Vera), while **Google Cloud DLP** handles broader PII redaction for NDA-safe content (via Cadmus).

## Memory Architecture

This is where it gets interesting. Ira has **ten memory subsystems**, modeled loosely after how human memory works:

| Memory | Storage | What It Remembers |
|:-------|:--------|:------------------|
| **Conversation** | SQLite | Per-user, per-channel chat history |
| **Long-Term** | Mem0 | Semantic facts extracted from interactions |
| **Episodic** | SQLite + Mem0 | Narratives of significant interactions |
| **Relationship** | SQLite | Contact warmth, preferences, communication style |
| **Procedural** | SQLite | Learned response patterns ("when X happens, do Y") |
| **Goals** | SQLite | Active goals with slot-filling tracking |
| **Emotional** | SQLite | Emotion tracking across conversations |
| **Inner Voice** | Runtime | Post-response self-reflection |
| **Metacognition** | Runtime | Confidence scoring and knowledge gap detection |

### Dream Mode

Every night (or on demand), Ira runs an **11-stage dream cycle** — consolidating memories, extracting insights, pruning stale data, checking for price conflicts, generating follow-up campaigns, and producing a morning summary. It's the AI equivalent of sleeping on it.

## The Body Systems

The codebase uses a **biological metaphor** for its subsystems:

### Core Body Systems

| System | Metaphor | Purpose |
|:-------|:---------|:--------|
| **Sensory** | Eyes & ears | Contact resolution, emotion detection, metadata extraction |
| **Digestive** | Stomach | Email processing, document summarization, nutrient extraction |
| **Circulatory** | Bloodstream | Cross-system data synchronization, heartbeat scheduling |
| **Immune** | Immune system | Hallucination detection, fact verification, safety filters |
| **Respiratory** | Lungs | Background health checks, system monitoring, vital signs |
| **Voice** | Vocal cords | Output shaping for channel and recipient |

### Extended Systems

| System | Purpose |
|:-------|:--------|
| **Redis Cache** | Response dedup, message stream persistence, fast key-value caching |
| **Document AI** | OCR for scanned PDFs, invoice/form parsing via Google Document AI |
| **DLP** | PII redaction and sensitive-data scanning via Google Cloud DLP |
| **Google Docs** | Read, write, and export Google Docs (case studies, reports) |
| **PDF.co** | HTML-to-PDF generation and text extraction for quotes and exports |
| **Learning Hub** | Feedback processing, knowledge gap analysis, procedure suggestion |
| **Board Meeting** | Multi-agent collaborative discussions on a topic |
| **Drip Engine** | Automated multi-step email campaigns |
| **Data Event Bus** | Typed event system for cross-store synchronization |
| **CRM Enricher** | Multi-agent CRM enrichment pipeline |
| **CRM Populator** | Contact classification and import from Gmail, KB, Neo4j |

Endocrine (behavioral modifiers like urgency and formality) and Musculoskeletal (action recording) are wired into the pipeline as lightweight service-key integrations rather than standalone system files.

## Shared Identity

Every agent in the pantheon shares a common foundation. At startup, `prompt_loader.load_soul_preamble()` extracts the **Identity**, **Voice**, and **Behavioral Boundaries** sections from [`SOUL.md`](SOUL.md) and `BaseAgent.run()` prepends them to every system prompt. This means all 27 agents speak with the same voice, respect the same hard boundaries, and know who they are — without duplicating the rules in 27 separate prompt files.

Project priorities and architectural guardrails live in [`VISION.md`](VISION.md).

## Tech Stack

| Layer | Technology |
|:------|:-----------|
| Language | Python 3.11+ |
| Package Manager | Poetry |
| LLM | OpenAI (primary) + Anthropic (fallback) via LLMClient |
| LLM Observability | Langfuse (tracing, cost tracking) |
| Embeddings | Voyage AI |
| Vector Database | Qdrant |
| Knowledge Graph | Neo4j |
| Relational Database | PostgreSQL (CRM via asyncpg) |
| Cache | Redis (response dedup, stream persistence) |
| Memory | Mem0 + SQLite |
| NER / Entity Extraction | GLiNER (local, zero-shot) + LLM (complementary) |
| Document Processing | Docling + Chonkie (chunking), Google Document AI, PDF.co |
| Web Crawling | crawl4ai |
| Input/Output Safety | guardrails-ai (Vera) + Google Cloud DLP (Cadmus/NDA) |
| Evaluation | deepeval + promptfoo |
| Privacy | Google Cloud DLP (PII redaction) |
| Integrations | Google Docs, Gmail |
| API Framework | FastAPI |
| CLI | Typer + Rich |
| MCP Server | FastMCP (Model Context Protocol — 30 tools for Cursor/Claude) |
| Reranking | Voyage Rerank (primary) + FlashRank (local fallback) |
| Migrations | Alembic |
| Containerization | Docker |

## Project Structure

```
ira-v3/
├── .cursor/
│   ├── agents/ira.md        # Cursor subagent definition (30 MCP tools)
│   ├── rules/               # Cursor rules for Ira API, agent loop, conventions
│   └── skills/              # Cursor skills: research, email, reports, sales pipeline
├── src/ira/
│   ├── agents/              # 27 specialist agents + base_agent.py
│   ├── brain/               # Knowledge retrieval, embeddings, graph, pricing,
│   │                        #   entity extraction (GLiNER + LLM), guardrails (32 modules)
│   ├── memory/              # 10 memory subsystems + dream mode + goal sweep
│   ├── systems/             # Body systems + extended systems (21 modules)
│   ├── interfaces/          # CLI, FastAPI server, MCP server,
│   │                        #   email processor, dashboard, cursor feedback
│   ├── services/            # LLMClient (OpenAI + Anthropic SDK with Langfuse tracing)
│   ├── schemas/             # Pydantic models for structured LLM outputs
│   ├── skills/              # Skill matrix + tool handlers
│   ├── middleware/          # Auth + request context
│   ├── data/                # CRM models, quote models
│   ├── pipeline.py          # 11-stage request pipeline
│   ├── pipeline_loop.py     # Agent Loop: Plan-Execute-Observe-Compile orchestration
│   ├── pantheon.py          # Agent orchestrator
│   ├── config.py            # Pydantic settings (all config from env)
│   ├── context.py           # Unified context manager
│   └── message_bus.py       # Inter-agent messaging
├── prompts/                 # LLM prompt templates (71 files)
├── scripts/                 # Operational scripts + training
├── tests/                   # Test suite (28 files, ~13,700 lines)
├── alembic/                 # Database migrations
├── docs/                    # Architecture and audit documentation
├── SOUL.md                  # Ira's identity, voice, and behavioral boundaries
├── VISION.md                # Project priorities and architectural guardrails
├── promptfooconfig.yaml     # Prompt regression testing config
├── docker-compose.yml       # Production stack
├── docker-compose.local.yml # Local development stack
├── Dockerfile               # Container build
└── pyproject.toml           # Dependencies and project metadata (v3.3.0)
```

## Getting Started

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Docker & Docker Compose
- API keys: OpenAI, Voyage AI (embeddings), and optionally Anthropic, Mem0, Google OAuth

### 1. Clone and Install

```bash
git clone https://github.com/doshirush1901/ira-v3.git
cd ira-v3
poetry install
```

### 2. Start Infrastructure

```bash
docker compose -f docker-compose.local.yml up -d
```

This starts Qdrant (vector DB), Neo4j (knowledge graph), PostgreSQL (CRM), and Redis (caching).

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys. At minimum you need:
- `OPENAI_API_KEY`
- `VOYAGE_API_KEY`
- `NEO4J_PASSWORD`

### 4. Run Database Migrations

```bash
alembic upgrade head
```

### 5. Launch

**Primary — CLI (no server):** Cursor or your terminal runs Ira via the CLI. Full stack (agents, RAG, Postgres, Qdrant, Neo4j, Mem0) runs in-process.

**CLI (interactive chat):**
```bash
poetry run ira chat
```

**CLI (single query):** Use `--json` for Cursor/scripts (stdout only).
```bash
poetry run ira ask "What's the lead time for a PF1 machine?"
poetry run ira ask "What's the lead time for a PF1 machine?" --json
```

**CLI (complex multi-phase task):**
```bash
poetry run ira task "Full analysis of Acme deal and draft a proposal" --json
```

**Optional — REST API:** Only when you want the web UI or HTTP integrations.
```bash
poetry run uvicorn ira.interfaces.server:app --reload
```

**Optional — MCP Server (for Cursor / Claude):**
```bash
poetry run ira mcp
```

**Optional — Web UI (for the team):** Requires the API server to be running.
```bash
cd web-ui && npm install && npm run dev
```
Open http://localhost:3000. Set `CORS_ORIGINS=http://localhost:3000` in the
backend `.env`. The web UI features an agent selector, SSE streaming with
live progress indicators, and full Markdown/GFM rendering.

### Other CLI Commands

```bash
ira dream          # Run the dream cycle (memory consolidation)
ira board          # Run a board meeting with key agents
ira ingest <path>  # Ingest documents into the knowledge base
ira train          # Run sleep training from corrections
ira health         # Check system vital signs
ira agents         # List all agents and their power levels
ira pipeline       # Show pipeline stage timings
ira feedback "..." # Record a correction for Ira to learn from
```

## API Endpoints

The **primary** way to query Ira is via the CLI (`ira ask`, `ira task`). The API is optional when you start the server (e.g. for the web UI or external integrations).

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| POST | `/api/query` | Send a message to Ira |
| POST | `/api/query/stream` | Send a message with SSE progress streaming |
| POST | `/api/task/stream` | Start a complex multi-phase task (Agent Loop with SSE) |
| POST | `/api/task/clarify` | Resume a paused task with user clarification |
| POST | `/api/feedback` | Submit a correction |
| GET | `/api/health` | Quick health check |
| GET | `/api/deep-health` | Detailed service-by-service health |
| GET | `/api/pipeline` | Sales pipeline summary |
| GET | `/api/agents` | List all agents and their status |
| POST | `/api/ingest` | Ingest a document into the knowledge base |
| POST | `/api/reingest-scanned` | Re-OCR scanned PDFs via Document AI |
| POST | `/api/board-meeting` | Trigger a board meeting |
| GET | `/api/dream-report` | Trigger dream cycle and return report |
| POST | `/api/email/search` | Search Gmail with filters (from, subject, date) |
| GET | `/api/email/thread/{id}` | Fetch a full email thread by Gmail thread ID |
| POST | `/api/email/draft` | Draft an email via Calliope |
| POST | `/api/email/rescan` | Deep historical email scan with SSE progress |
| GET | `/api/email/rescan` | Check status of running/last email rescan |
| GET | `/api/corrections` | List recent corrections (filterable) |
| GET | `/api/vendors` | List all vendors |
| POST | `/api/vendors` | Create a vendor |
| GET | `/api/vendors/payables` | Payables summary across all vendors |
| GET | `/api/vendors/overdue` | Overdue vendor payables |
| POST | `/api/vendors/payables` | Record a vendor payable/invoice |
| GET | `/dashboard/` | Web dashboard (browser) |

## Running Tests

```bash
poetry run pytest                    # full suite
poetry run pytest --cov=ira          # with coverage
poetry run pytest -k "test_clio"     # specific test
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup instructions, code style, and how to create new agents.

## Architecture Deep Dive

For detailed architecture documentation, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

For a comprehensive system audit and production readiness assessment, see [`docs/SYSTEM_AUDIT.md`](docs/SYSTEM_AUDIT.md).

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for version history.

## Security

To report a vulnerability, see [`SECURITY.md`](SECURITY.md).

## License

Proprietary. All rights reserved by Machinecraft. See [`LICENSE`](LICENSE).
