# Ira v3

**The AI that runs a manufacturing company. No, seriously.**

---

Most AI assistants answer questions. Ira runs a business.

Ira is a multi-agent AI system built for [Machinecraft](https://machinecraft.org) — an industrial machinery company that designs and manufactures thermoforming, panel forming, and packaging machines. Instead of one monolithic chatbot that tries to do everything and does nothing well, Ira delegates work to a **pantheon of 24 specialist AI agents**, each an expert in their domain — sales, production, finance, marketing, HR, quality, research, and more.

Think of it like this: you don't walk into a company and ask the receptionist to design your machine, draft your quote, check your invoice, *and* write your marketing email. You talk to the right person. Ira figures out who that person is, briefs them, and delivers the result.

## How It Actually Works

Every message — whether it comes from the CLI, Telegram, or the REST API — flows through an **11-stage pipeline** that mimics how a human organization processes a request:

```
  You say something
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│                    REQUEST PIPELINE                      │
│                                                         │
│  1. PERCEIVE    → Who are you? What's your mood?        │
│  2. REMEMBER    → What have we talked about before?     │
│  3. ROUTE       → Which agent(s) should handle this?    │
│  4. ENRICH      → Add context, style, learnings         │
│  5. EXECUTE     → Agent does the work (ReAct loop)      │
│  6. ASSESS      → How confident are we in this answer?  │
│  7. REFLECT     → What did we learn from this?          │
│  8. SHAPE       → Format for your channel & preferences │
│  9. LEARN       → Store memories, update CRM, goals     │
│                                                         │
└─────────────────────────────────────────────────────────┘
       │
       ▼
  You get a response that actually knows what it's talking about
```

The routing is a three-tier system: a fast **deterministic router** catches obvious intents (keywords → agent), a **procedural memory** matches learned patterns, and if neither fires, **Athena** (the orchestrator agent) uses LLM reasoning to pick the right specialist.

## The Pantheon

Twenty-four agents. Each with a name from Greek mythology, a specific role, and their own set of tools.

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
| **Quotebuilder** | Quote Builder | Generates structured quotes with specs and pricing |
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
                    people,
                    machines)
```

All three backends are searched **in parallel**, results are **reranked** with FlashRank, and if nothing comes back, the system falls back to **Alexandros** (the librarian) who searches the raw document archive.

## Memory Architecture

This is where it gets interesting. Ira has **nine memory subsystems**, modeled loosely after how human memory works:

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

| System | Metaphor | Purpose |
|:-------|:---------|:--------|
| **Sensory** | Eyes & ears | Contact resolution, emotion detection, metadata extraction |
| **Digestive** | Stomach | Email processing, document summarization, nutrient extraction |
| **Circulatory** | Bloodstream | Cross-system data synchronization |
| **Immune** | Immune system | Hallucination detection, fact verification |
| **Endocrine** | Hormones | System-wide state modifiers (urgency, formality) |
| **Respiratory** | Lungs | Health monitoring, vital signs |
| **Musculoskeletal** | Muscles | Task execution framework |
| **Voice** | Vocal cords | Output shaping for channel and recipient |
| **Redis Cache** | Short-term memory | Response dedup, message stream persistence, fast key-value caching |
| **Document AI** | Reading glasses | OCR for scanned PDFs, invoice/form parsing via Google Document AI |
| **DLP** | Privacy filter | PII redaction and sensitive-data scanning via Google Cloud DLP |
| **Google Docs** | Printing press | Read, write, and export Google Docs (case studies, reports) |
| **PDF.co** | Bookbinder | HTML-to-PDF generation and text extraction for quotes and exports |

## Shared Identity

Every agent in the pantheon shares a common foundation. At startup, `prompt_loader.load_soul_preamble()` extracts the **Identity**, **Voice**, and **Behavioral Boundaries** sections from [`SOUL.md`](SOUL.md) and `BaseAgent.run()` prepends them to every system prompt. This means all 24 agents speak with the same voice, respect the same hard boundaries, and know who they are — without duplicating the rules in 24 separate prompt files.

Project priorities and architectural guardrails live in [`VISION.md`](VISION.md).

## Tech Stack

| Layer | Technology |
|:------|:-----------|
| Language | Python 3.11+ |
| Package Manager | Poetry |
| LLM | OpenAI (primary) + Anthropic (fallback) |
| Embeddings | Voyage AI |
| Vector Database | Qdrant |
| Knowledge Graph | Neo4j |
| Relational Database | PostgreSQL (CRM via asyncpg) |
| Cache | Redis (response dedup, stream persistence) |
| Memory | Mem0 + SQLite |
| Document Processing | Google Document AI, PDF.co |
| Privacy | Google Cloud DLP (PII redaction) |
| Integrations | Google Docs, Gmail |
| API Framework | FastAPI |
| CLI | Typer + Rich |
| Messaging | python-telegram-bot |
| Reranking | FlashRank + Voyage Rerank |
| Migrations | Alembic |
| Containerization | Docker |

## Project Structure

```
ira-v3/
├── src/ira/
│   ├── agents/              # 24 specialist agents + base_agent.py
│   ├── brain/               # Knowledge retrieval, embeddings, graph, pricing
│   ├── memory/              # 9 memory subsystems + dream mode
│   ├── systems/             # Biological body systems
│   ├── interfaces/          # CLI, FastAPI server, Telegram bot
│   ├── skills/              # Skill matrix + tool handlers
│   ├── middleware/          # Auth + request context
│   ├── data/                # CRM models, quote models
│   ├── pipeline.py          # 11-stage request pipeline
│   ├── pantheon.py          # Agent orchestrator
│   ├── config.py            # Pydantic settings (all config from env)
│   ├── context.py           # Unified context manager
│   └── message_bus.py       # Inter-agent messaging
├── prompts/                 # LLM prompt templates (one per agent + utilities)
├── scripts/                 # Operational scripts (board meetings, health checks)
├── tests/                   # Test suite
├── alembic/                 # Database migrations
├── docs/                    # Architecture and audit documentation
├── SOUL.md                  # Ira's identity, voice, and behavioral boundaries
├── VISION.md                # Project priorities and architectural guardrails
├── docker-compose.yml       # Production stack
├── docker-compose.local.yml # Local development stack
├── Dockerfile               # Container build
└── pyproject.toml           # Dependencies and project metadata
```

## Getting Started

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Docker & Docker Compose
- API keys: OpenAI, Voyage AI (embeddings), and optionally Anthropic, Mem0, Telegram, Google OAuth

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

**CLI (interactive chat):**
```bash
poetry run ira chat
```

**CLI (single query):**
```bash
poetry run ira ask "What's the lead time for a PF1 machine?"
```

**REST API:**
```bash
poetry run uvicorn ira.interfaces.server:app --reload
```

**Telegram Bot:**
```bash
python -m ira.interfaces.telegram_bot
```

### Other CLI Commands

```bash
ira dream          # Run the dream cycle (memory consolidation)
ira board          # Run a board meeting with key agents
ira ingest <path>  # Ingest documents into the knowledge base
ira train          # Run sleep training from corrections
ira health         # Check system vital signs
ira agents         # List all agents and their power levels
ira pipeline       # Show pipeline stage timings
```

## API Endpoints

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| POST | `/api/query` | Send a message to Ira |
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
| GET | `/dashboard/` | Web dashboard (browser) |

## Running Tests

```bash
poetry run pytest
```

## Architecture Deep Dive

For detailed architecture documentation, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

For a comprehensive system audit and production readiness assessment, see [`docs/SYSTEM_AUDIT.md`](docs/SYSTEM_AUDIT.md).

## License

Proprietary. All rights reserved by Machinecraft.
