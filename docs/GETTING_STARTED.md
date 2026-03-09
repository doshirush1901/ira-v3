# Getting Started with Ira v3

Ira v3 is a multi-agent AI system — a "pantheon" of 24 specialized AI agents that operate as the digital brain of a manufacturing company. Each agent is an expert in a specific domain: sales, production, finance, marketing, HR, and more.

This guide walks you through local setup and first interactions.

## Prerequisites

| Requirement | Notes |
|:------------|:------|
| **Python 3.11+** | Core language |
| **Poetry** | Dependency management (`pip install poetry`) |
| **Docker & Docker Compose** | Runs the local infrastructure (databases) |
| **OpenAI API Key** | Core LLM reasoning |
| **Voyage AI API Key** | Text embeddings |

Optional: Anthropic API key (fallback LLM), Mem0 API key (long-term memory), Google OAuth credentials (Gmail integration), Langfuse keys (LLM observability/tracing).

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/doshirush1901/ira-v3.git
cd ira-v3
```

### 2. Install Dependencies

```bash
poetry install
```

### 3. Start Infrastructure

Ira relies on four services: **Qdrant** (vector search), **Neo4j** (knowledge graph), **PostgreSQL** (CRM data), and **Redis** (caching/dedup).

```bash
docker compose -f docker-compose.local.yml up -d
```

Docker must be running on your machine before this step.

### 4. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```
OPENAI_API_KEY=your_openai_key_here
VOYAGE_API_KEY=your_voyage_key_here
NEO4J_PASSWORD=set_a_secure_password
```

### 5. Run Database Migrations

```bash
alembic upgrade head
```

This creates the CRM schema in PostgreSQL.

## Using Ira

Once setup is complete, Ira routes your queries to the right specialist agent automatically.

### Option A: Interactive CLI Chat

The easiest way to experience Ira — a continuous conversation in your terminal.

```bash
poetry run ira chat
```

### Option B: Single Query

Ask a quick question without entering a chat session.

```bash
poetry run ira ask "What is the lead time for a new packaging machine?"
```

### Option C: REST API Server

Start the FastAPI server for integration with frontends or API testing.

```bash
poetry run uvicorn ira.interfaces.server:app --reload
```

API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs) once the server is running.

### Option D: Cursor IDE (Recommended)

Open this repo in [Cursor](https://cursor.sh). The `.cursor/rules/` directory teaches Cursor how to start, query, and manage Ira automatically.

```
Step 1:  Open ira-v3 in Cursor
Step 2:  Type "wake up Ira" in Cursor chat
Step 3:  Wait ~60 seconds for all services to boot
Step 4:  Ask anything — "@Ira what's the status of the Acme Packaging deal?"
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

## A Note on Data

Ira v3 is built specifically for Machinecraft. You can run the code and interact with all 27 agents, but the databases (Qdrant and Neo4j) start empty. Without ingesting Machinecraft's documents, product specs, and CRM data, agents won't have domain knowledge to draw from.

That said, running this repository is an excellent way to explore a production-grade multi-agent architecture — the routing, memory, ReAct loops, and body-system metaphor all work regardless of the data loaded.

To start populating the knowledge base:

```bash
poetry run ira ingest /path/to/your/documents/
```

Or via the API:

```bash
curl -X POST http://localhost:8000/api/ingest -F "file=@/path/to/document.pdf"
```

## Next Steps

- Read [Why Ira?](WHY_IRA.md) to understand the use cases and philosophy behind the system.
- See [ARCHITECTURE.md](ARCHITECTURE.md) for a deep dive into the technical design.
- See [SYSTEM_AUDIT.md](SYSTEM_AUDIT.md) for the production readiness assessment.
- Check the main [README](../README.md) for the full agent roster, memory architecture, and API reference.
