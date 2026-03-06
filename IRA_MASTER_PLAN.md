# The Ira Dream: Definitive Cursor Implementation Plan

**Author:** Manus AI
**Date:** 2026-03-06
**For:** Machinecraft Company — Fresh Cursor Workspace on New Mac Mini

---

## Executive Summary

This document is the complete, step-by-step implementation plan for building Ira v3 — the full-vision AI agent system for Machinecraft. It is designed to be executed sequentially within Cursor's agent mode on a fresh Mac Mini. Every architectural concept from the original dream is preserved: the Agent Pantheon, the biological body systems, the multi-layered brain, the advanced memory architecture, the autonomous drip marketing engine, and the learning feedback loops.

The plan is organized into **8 development phases**, each producing a testable milestone. Within each phase, steps are ordered so that each one builds on the previous. The "Cursor Prompt" column provides the exact prompt you should paste into Cursor's agent to build that component.

**What this plan is NOT:** This is not code. This is a strategic blueprint and a set of precise instructions for Cursor's AI agent to generate the code for you, one module at a time, with full context and architectural awareness.

---

## How to Use This Plan in Cursor

1.  Open the `ira-v3` workspace folder in Cursor.
2.  Copy the `.cursor/rules/` files and `AGENTS.md` from the deliverables into your workspace **before** starting Phase 0.
3.  For each step, open a **new Cursor agent conversation** (to keep context clean).
4.  Use **Plan Mode** (`Shift+Tab`) for complex steps. Let the agent plan, review, then approve.
5.  After each phase, run `poetry run pytest` to verify everything works before moving on.
6.  Commit after each phase with the suggested commit message.

---

## Pre-Requisites: Mac Mini Setup

Before opening Cursor, run these commands in your terminal to install the necessary system-level tools.

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install core tools
brew install python@3.12 poetry docker docker-compose git

# Start Docker Desktop (for Qdrant, Neo4j, PostgreSQL)
open -a Docker

# Verify installations
python3 --version   # Should be 3.12.x
poetry --version    # Should be 2.x
docker --version    # Should be 24.x or later
```

---

## Phase 0: The Foundation — Project Scaffold & Cursor Configuration

**Goal:** Create the project skeleton, install all dependencies, configure Cursor rules, and define the core data models that every other module will use.

**Estimated Time:** 1-2 hours.

**New Cursor Conversation for each step below.**

### Step 0.1: Create the Project

**Terminal Command (not Cursor):**
```bash
mkdir ira-v3 && cd ira-v3
poetry init --name ira --python "^3.12" --no-interaction
```

### Step 0.2: Install All Dependencies

**Terminal Command:**
```bash
# Core
poetry add fastapi uvicorn[standard] httpx python-dotenv pydantic pydantic-settings

# AI / LLM
poetry add openai anthropic voyageai

# Vector DB & Graph
poetry add qdrant-client neo4j

# Database
poetry add sqlalchemy[asyncio] alembic asyncpg aiosqlite

# Memory
poetry add mem0ai

# Telegram
poetry add "python-telegram-bot[ext]"

# Google Workspace
poetry add google-api-python-client google-auth-httplib2 google-auth-oauthlib

# RAG & NLP
poetry add flashrank tiktoken

# Document Processing
poetry add pypdf openpyxl python-docx

# Utilities
poetry add structlog apscheduler

# Dev dependencies
poetry add --group dev pytest pytest-asyncio ruff mypy
```

### Step 0.3: Create the Complete Directory Structure

**Cursor Prompt:**
```
Create the following directory structure for a Python project. Create an empty __init__.py in every Python package directory. Do not add any code yet, just the structure:

src/ira/__init__.py
src/ira/config.py
src/ira/agents/__init__.py
src/ira/agents/base_agent.py
src/ira/agents/athena.py          # CEO / Orchestrator
src/ira/agents/clio.py            # Researcher
src/ira/agents/prometheus.py      # Sales / CRO
src/ira/agents/plutus.py          # Finance / CFO
src/ira/agents/hermes.py          # Marketing / CMO
src/ira/agents/hephaestus.py      # Production / CPO
src/ira/agents/themis.py          # HR / CHRO
src/ira/agents/calliope.py        # Writer
src/ira/agents/tyche.py           # Pipeline Forecaster
src/ira/agents/delphi.py          # Email Classifier
src/ira/agents/sphinx.py          # Gatekeeper / Clarifier
src/ira/agents/vera.py            # Fact Checker
src/ira/agents/sophia.py          # Reflector / Learner
src/ira/agents/iris.py            # External Intelligence
src/ira/agents/mnemosyne.py       # Memory Keeper
src/ira/agents/nemesis.py         # Trainer / Adversarial
src/ira/agents/arachne.py         # Newsletter / Content
src/ira/brain/__init__.py
src/ira/brain/embeddings.py
src/ira/brain/qdrant_manager.py
src/ira/brain/knowledge_graph.py
src/ira/brain/retriever.py
src/ira/brain/document_ingestor.py
src/ira/brain/machine_intelligence.py
src/ira/brain/pricing_engine.py
src/ira/brain/sales_intelligence.py
src/ira/brain/deterministic_router.py
src/ira/systems/__init__.py
src/ira/systems/digestive.py
src/ira/systems/respiratory.py
src/ira/systems/immune.py
src/ira/systems/endocrine.py
src/ira/systems/musculoskeletal.py
src/ira/systems/sensory.py
src/ira/systems/voice.py
src/ira/systems/board_meeting.py
src/ira/systems/drip_engine.py
src/ira/memory/__init__.py
src/ira/memory/conversation.py
src/ira/memory/long_term.py
src/ira/memory/episodic.py
src/ira/memory/procedural.py
src/ira/memory/metacognition.py
src/ira/memory/dream_mode.py
src/ira/memory/inner_voice.py
src/ira/memory/emotional_intelligence.py
src/ira/memory/relationship.py
src/ira/memory/goal_manager.py
src/ira/data/__init__.py
src/ira/data/models.py
src/ira/data/crm.py
src/ira/data/quotes.py
src/ira/interfaces/__init__.py
src/ira/interfaces/telegram_bot.py
src/ira/interfaces/email_processor.py
src/ira/interfaces/cli.py
src/ira/interfaces/server.py
src/ira/message_bus.py
src/ira/pantheon.py
src/ira/skills/__init__.py
tests/__init__.py
tests/test_brain.py
tests/test_agents.py
tests/test_systems.py
tests/test_memory.py
tests/test_crm.py
tests/test_interfaces.py
scripts/run_ingestion.py
scripts/run_dream.py
scripts/migrate_from_v1.py
docs/ARCHITECTURE.md
data/imports/
.cursor/rules/
.cursor/commands/
```

### Step 0.4: Create the `.env.example` File

**Cursor Prompt:**
```
Create a .env.example file with the following environment variables. Add comments explaining each one:

# LLM APIs
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_MODEL=gpt-4.1
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Embeddings
VOYAGE_API_KEY=
VOYAGE_MODEL=voyage-3

# Vector Database
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=ira_knowledge_v3

# Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# Relational Database (PostgreSQL for CRM)
DATABASE_URL=postgresql+asyncpg://ira:ira@localhost:5432/ira_crm

# Memory
MEM0_API_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=

# Google Workspace (for ira@machinecraft.org)
GOOGLE_CREDENTIALS_PATH=credentials.json
GOOGLE_TOKEN_PATH=token.json
IRA_EMAIL=ira@machinecraft.org

# External APIs
NEWSDATA_API_KEY=

# Application
LOG_LEVEL=INFO
ENVIRONMENT=development
```

### Step 0.5: Create the Configuration Module

**Cursor Prompt:**
```
Create src/ira/config.py. Use pydantic_settings.BaseSettings to load all environment variables from the .env file. Group them into nested classes:

- LLMConfig: openai_api_key, anthropic_api_key, openai_model, anthropic_model
- EmbeddingConfig: voyage_api_key, voyage_model
- QdrantConfig: url, collection
- Neo4jConfig: uri, user, password
- DatabaseConfig: url
- TelegramConfig: bot_token, admin_chat_id
- GoogleConfig: credentials_path, token_path, ira_email
- AppConfig: log_level, environment

Create a top-level Settings class that composes all of these. Provide a cached get_settings() function. All fields should have sensible defaults where possible. Use model_config with env_file=".env".
```

### Step 0.6: Create Core Data Models

**Cursor Prompt:**
```
Create src/ira/data/models.py. Define Pydantic BaseModel classes for the core data structures used across the entire application. These are NOT database models — they are transfer objects:

1. KnowledgeItem: id (UUID), source (str), source_category (str from the 22 import categories), content (str), metadata (dict), created_at (datetime)
2. Email: id (str), from_address (str), to_address (str), subject (str), body (str), received_at (datetime), thread_id (str optional), labels (list[str])
3. Contact: id (UUID), name (str), email (str), company (str optional), region (str optional), industry (str optional), source (str), score (float default 0.0), created_at (datetime)
4. Deal: id (UUID), contact_id (UUID), title (str), value (float), currency (str default "USD"), stage (DealStage enum: NEW, CONTACTED, ENGAGED, QUALIFIED, PROPOSAL, NEGOTIATION, WON, LOST), created_at (datetime), updated_at (datetime)
5. Interaction: id (UUID), contact_id (UUID), channel (Channel enum: EMAIL, TELEGRAM, PHONE, MEETING, WEB), direction (Direction enum: INBOUND, OUTBOUND), summary (str), content (str optional), created_at (datetime)
6. AgentMessage: from_agent (str), to_agent (str), query (str), context (dict), response (str optional), created_at (datetime)
7. BoardMeetingMinutes: topic (str), participants (list[str]), contributions (dict[str, str]), synthesis (str), action_items (list[str]), created_at (datetime)
8. DripCampaignStep: lead_id (UUID), step_number (int), email_subject (str), email_body (str), sent_at (datetime optional), reply_received (bool default False)
9. DreamReport: cycle_date (date), memories_consolidated (int), gaps_identified (list[str]), creative_connections (list[str]), campaign_insights (list[str])
10. KnowledgeState (enum): KNOW_VERIFIED, KNOW_UNVERIFIED, PARTIAL, UNCERTAIN, CONFLICTING, UNKNOWN
11. EmotionalState (enum): NEUTRAL, POSITIVE, STRESSED, FRUSTRATED, CURIOUS, URGENT, GRATEFUL, UNCERTAIN
12. WarmthLevel (enum): STRANGER, ACQUAINTANCE, FAMILIAR, WARM, TRUSTED

Include proper docstrings for every model and field descriptions.
```

### Step 0.7: Create `docker-compose.yml`

**Cursor Prompt:**
```
Create a docker-compose.yml file at the project root with three services:

1. qdrant: image qdrant/qdrant:latest, port 6333:6333, volume ./data/qdrant:/qdrant/storage
2. neo4j: image neo4j:5, ports 7474:7474 and 7687:7687, environment NEO4J_AUTH=neo4j/<your-neo4j-password>, volume ./data/neo4j:/data
3. postgres: image postgres:16, port 5432:5432, environment POSTGRES_USER=ira, POSTGRES_PASSWORD=<your-postgres-password>, POSTGRES_DB=ira_crm, volume ./data/postgres:/var/lib/postgresql/data

Add a shared network called ira-network.
```

### Step 0.8: Copy Cursor Rules and AGENTS.md

Copy the provided `.cursor/rules/` files and `AGENTS.md` into the workspace. These files are included in the deliverables package.

### Step 0.9: Initial Git Commit

**Terminal Command:**
```bash
git init
echo "data/qdrant/\ndata/neo4j/\ndata/postgres/\n.env\n__pycache__/\n*.pyc\n.venv/" > .gitignore
git add .
git commit -m "Phase 0: Project foundation — structure, config, models, Cursor rules"
```

**Phase 0 Outcome:** A fully scaffolded, dependency-complete Python project with Cursor rules in place. Every file exists (empty or with stubs). The architectural guardrails are set. You are ready to build.

---

## Phase 1: The Brain — RAG Pipeline, Knowledge Graph, and Document Intelligence

**Goal:** Build the complete knowledge backbone — from document ingestion through embedding, storage, hybrid retrieval, reranking, and knowledge graph relationships. After this phase, Ira can answer any question about Machinecraft's documents.

**Estimated Time:** 3-5 hours.

**Start Docker services first:** `docker-compose up -d`

### Step 1.1: Voyage AI Embedding Service

**Cursor Prompt:**
```
Create src/ira/brain/embeddings.py.

Implement an EmbeddingService class that wraps the Voyage AI API. It should:
1. Initialize with the voyage_api_key and voyage_model from config.
2. Have an async method embed_texts(texts: list[str]) -> list[list[float]] that calls the Voyage AI embed endpoint.
3. Have an async method embed_query(query: str) -> list[float] for single query embedding.
4. Handle batching internally — Voyage AI has a limit of 128 texts per batch. If the input exceeds this, split into batches and concatenate results.
5. Include retry logic with exponential backoff for API failures.
6. Cache embeddings using a simple in-memory LRU cache (functools.lru_cache won't work for lists, so use a dict with hash of text as key).

Add a module-level docstring explaining that this is the primary embedding service for all vector operations in the system.
```

### Step 1.2: Qdrant Vector Store Manager

**Cursor Prompt:**
```
Create src/ira/brain/qdrant_manager.py.

Implement a QdrantManager class that wraps the qdrant_client library. It should:
1. Initialize with the Qdrant URL from config and the EmbeddingService from step 1.1.
2. Have an async method ensure_collection(name: str, vector_size: int = 1024) that creates a collection if it doesn't exist, configured for cosine distance.
3. Have an async method upsert_items(collection: str, items: list[KnowledgeItem]) that:
   a. Generates embeddings for all items using EmbeddingService.
   b. Creates PointStruct objects with the item's UUID as id, the embedding as vector, and all other fields as payload.
   c. Upserts in batches of 100.
4. Have an async method search(collection: str, query: str, limit: int = 10) -> list[dict] that:
   a. Embeds the query using EmbeddingService.embed_query().
   b. Performs a vector search against the collection.
   c. Returns the results as a list of dicts with 'content', 'score', 'source', and 'metadata' keys.
5. Have an async method hybrid_search(collection: str, query: str, limit: int = 10) that combines dense vector search with Qdrant's built-in keyword filtering for hybrid retrieval.

Use the async qdrant_client (AsyncQdrantClient). Add comprehensive error handling and logging.
```

### Step 1.3: Document Ingestion Pipeline

**Cursor Prompt:**
```
Create src/ira/brain/document_ingestor.py.

Implement a DocumentIngestor class that processes all 22 categories of documents from the data/imports directory. It should:

1. Initialize with QdrantManager and EmbeddingService instances.
2. Have a method discover_files(base_path: str = "data/imports") -> list[dict] that walks the directory tree and returns a list of dicts with 'path', 'category' (derived from folder name like '01_Quotes_and_Proposals'), 'extension', and 'size'.
3. Have file reader methods for each supported format:
   - read_pdf(path) -> str (using pypdf)
   - read_xlsx(path) -> str (using openpyxl, converting each sheet to text)
   - read_docx(path) -> str (using python-docx)
   - read_txt(path) -> str
   - read_csv(path) -> str
4. Have a method chunk_text(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str] that splits text into overlapping chunks using tiktoken for accurate token counting.
5. Have an async method ingest_file(file_info: dict) -> int that reads the file, chunks it, creates KnowledgeItem objects (with source_category set from the folder name), and upserts them into Qdrant. Returns the number of chunks created.
6. Have an async method ingest_all(base_path: str = "data/imports") -> dict that processes all files and returns a summary dict with total_files, total_chunks, and per-category counts.
7. Track already-ingested files using a simple SQLite table (ingested_files with columns: path, hash, chunk_count, ingested_at) to avoid re-processing.

Add detailed logging for each file processed. Handle errors gracefully — a single bad file should not stop the entire ingestion.
```

### Step 1.4: Knowledge Graph (Neo4j)

**Cursor Prompt:**
```
Create src/ira/brain/knowledge_graph.py.

Implement a KnowledgeGraph class that manages the Neo4j graph database. It should:

1. Initialize with the Neo4j URI, user, and password from config using the neo4j async driver.
2. Have an async method ensure_indexes() that creates uniqueness constraints and indexes on key node types (Company.name, Person.email, Machine.model).
3. Have async methods to add entities:
   - add_company(name, region, industry, website)
   - add_person(name, email, company_name, role)
   - add_machine(model, category, description)
   - add_quote(quote_id, company_name, machine_model, value, date, status)
4. Have async methods to add relationships:
   - link_person_to_company(person_email, company_name, role)
   - link_quote_to_company(quote_id, company_name)
   - link_quote_to_machine(quote_id, machine_model)
5. Have async query methods:
   - find_company_contacts(company_name) -> list of persons
   - find_company_quotes(company_name) -> list of quotes
   - find_machine_customers(machine_model) -> list of companies
   - find_related_entities(entity_name, max_hops: int = 2) -> subgraph dict
   - run_cypher(query: str, params: dict) -> list[dict] for custom queries
6. Have an async method extract_entities_from_text(text: str) -> dict that uses an LLM (OpenAI) to extract companies, people, machines, and relationships from a block of text. Return a structured dict.

Use MERGE statements to avoid duplicate nodes. All methods should be async.
```

### Step 1.5: Unified Retriever with Hybrid Search and Reranking

**Cursor Prompt:**
```
Create src/ira/brain/retriever.py.

Implement a UnifiedRetriever class that is the SINGLE entry point for all knowledge retrieval in the system. No agent should query Qdrant or Neo4j directly — they all go through this retriever. It should:

1. Initialize with QdrantManager, KnowledgeGraph, and optionally a Mem0 client.
2. Have an async method search(query: str, sources: list[str] = None, limit: int = 10) -> list[dict] that:
   a. Performs a hybrid search on Qdrant (dense + sparse/keyword).
   b. Queries the Neo4j knowledge graph for related entities.
   c. Optionally queries Mem0 for relevant memories.
   d. Merges all results into a single ranked list.
   e. Applies FlashRank reranking to the merged results to get the most relevant items at the top.
   f. Returns the top `limit` results, each as a dict with 'content', 'score', 'source', 'source_type' (qdrant/neo4j/mem0), and 'metadata'.
3. Have an async method decompose_and_search(complex_query: str, limit: int = 10) -> list[dict] that:
   a. Uses an LLM to decompose a complex query into 2-4 simpler sub-queries.
   b. Runs search() for each sub-query in parallel using asyncio.gather().
   c. Deduplicates and re-ranks the combined results.
4. Have an async method search_by_category(query: str, category: str, limit: int = 5) that filters Qdrant results to a specific source_category (e.g., "01_Quotes_and_Proposals").

Import and use flashrank for the reranking step. The FlashRank Ranker should be initialized once and reused.
```

### Step 1.6: Machine Intelligence Module

**Cursor Prompt:**
```
Create src/ira/brain/machine_intelligence.py.

Implement a MachineIntelligence class that provides deep knowledge about Machinecraft's machines. It should:

1. Initialize with the UnifiedRetriever.
2. Maintain a MACHINE_CATALOG dict that maps machine model names (e.g., "PF1-C", "AM-Series", "PF2") to their basic metadata (category, description, key_features list).
3. Have an async method get_machine_specs(model: str) -> dict that retrieves detailed specifications from the knowledge base by searching the "04_Machine_Manuals_and_Specs" category.
4. Have an async method recommend_machine(requirements: dict) -> list[dict] that takes customer requirements (material, thickness, output_rate, budget) and uses the machine catalog + LLM reasoning to recommend the best matching machines with explanations.
5. Have an async method compare_machines(model_a: str, model_b: str) -> str that generates a detailed comparison table.
6. Have a TRUTH_HINTS dict that stores hard-coded business rules (e.g., "AM series max thickness: 12mm", "PF1-C lead time: 16-20 weeks"). These override any conflicting information from the knowledge base.

The MACHINE_CATALOG and TRUTH_HINTS should be loaded from a YAML or JSON file in data/ so they can be easily updated without code changes.
```

### Step 1.7: Pricing Engine

**Cursor Prompt:**
```
Create src/ira/brain/pricing_engine.py.

Implement a PricingEngine class that handles all pricing and quote-related intelligence. It should:

1. Initialize with the UnifiedRetriever and the CRM database (from Phase 4, but define the interface now).
2. Have an async method estimate_price(machine_model: str, configuration: dict) -> dict that:
   a. Searches historical quotes for similar configurations using the retriever.
   b. Extracts pricing patterns from the results.
   c. Uses an LLM to generate a price estimate with a confidence range (low, mid, high).
   d. Returns a dict with estimated_price, confidence, similar_quotes (list), and reasoning.
3. Have an async method analyze_quote_history(filters: dict) -> dict that provides aggregate statistics (average deal size, win rate, average discount) filtered by region, machine, time period, etc.
4. Have an async method generate_quote_content(contact: Contact, machine_model: str, configuration: dict) -> dict that generates the text content for a formal quote (not the PDF itself — that's a separate step).
```

### Step 1.8: Sales Intelligence Module

**Cursor Prompt:**
```
Create src/ira/brain/sales_intelligence.py.

Implement a SalesIntelligence class that provides sales-specific analytical capabilities. It should:

1. Initialize with the UnifiedRetriever and the CRM database interface.
2. Have an async method qualify_lead(contact: Contact, inquiry_text: str) -> dict that:
   a. Analyzes the inquiry text for buying signals.
   b. Checks the contact's history in the CRM.
   c. Enriches with knowledge graph data (company size, industry, past purchases).
   d. Returns a qualification score (0-100), a qualification_level (HOT, WARM, COLD), and reasoning.
3. Have an async method score_customer_health(contact_id: UUID) -> dict that calculates a health score based on engagement frequency, response latency, sentiment of recent interactions, and conversion history.
4. Have an async method identify_stale_leads(days_threshold: int = 14) -> list[dict] that finds leads in the CRM that haven't been contacted in the given number of days and suggests re-engagement strategies.
5. Have an async method generate_lead_intelligence(company_name: str) -> dict that uses web search and news APIs to gather real-time context about a company (recent news, industry trends, key personnel changes).
```

### Step 1.9: Deterministic Router

**Cursor Prompt:**
```
Create src/ira/brain/deterministic_router.py.

Implement a DeterministicRouter class that provides fast, pattern-based routing for common query types before falling back to LLM-based routing. It should:

1. Define an IntentCategory enum with values: SALES_PIPELINE, FINANCE_REVIEW, HR_OVERVIEW, MACHINE_SPECS, PRODUCTION_STATUS, CUSTOMER_SERVICE, MARKETING_CAMPAIGN, RESEARCH, QUOTE_REQUEST, GENERAL.
2. Define a ROUTING_TABLE dict that maps each IntentCategory to:
   - required_agents: list of agent names that MUST be consulted.
   - optional_agents: list of agent names that MAY be consulted.
   - required_tools: list of tool names that should be used.
3. Have a method classify_intent(query: str) -> IntentCategory that uses keyword patterns and regex to quickly classify common queries. For example:
   - "pipeline", "deals", "leads", "CRM" -> SALES_PIPELINE
   - "price", "quote", "cost" -> QUOTE_REQUEST
   - "machine", "specs", "PF1", "AM" -> MACHINE_SPECS
4. Have a method get_routing(intent: IntentCategory) -> dict that returns the routing configuration for the given intent.
5. If keyword matching fails (confidence below threshold), return None to signal that LLM-based routing should be used instead.

This is a performance optimization — it allows common queries to bypass the LLM routing step entirely.
```

### Step 1.10: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_brain.py with pytest-asyncio tests for:

1. EmbeddingService: Test that embed_texts returns vectors of the correct dimension. Test batching logic with >128 texts. (Mock the Voyage API call.)
2. QdrantManager: Test ensure_collection, upsert_items, and search. (Use a test Qdrant collection.)
3. DocumentIngestor: Test chunk_text with known input/output. Test that read_pdf handles a simple PDF.
4. UnifiedRetriever: Test that search merges results from multiple sources. Test decompose_and_search. (Mock the underlying services.)
5. DeterministicRouter: Test classify_intent for each IntentCategory with sample queries.

Use pytest fixtures for shared setup. Use unittest.mock.AsyncMock for mocking async services.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_brain.py -v
git add . && git commit -m "Phase 1: Brain complete — RAG, Knowledge Graph, Machine Intelligence, Pricing, Sales Intelligence"
```

**Phase 1 Outcome:** A complete knowledge backbone. Ira can ingest documents, embed them, store them in Qdrant, build a knowledge graph in Neo4j, and retrieve information using hybrid search with reranking. She also has specialized intelligence modules for machines, pricing, and sales.

---

## Phase 2: The Pantheon — Multi-Agent Architecture with Full Org Chart

**Goal:** Build the complete multi-agent framework — the BaseAgent class, the MessageBus for inter-agent communication, and every single agent in the Pantheon with their specific tools and personalities. After this phase, agents can talk to each other and collaborate on complex tasks.

**Estimated Time:** 4-6 hours.

### Step 2.1: The Message Bus

**Cursor Prompt:**
```
Create src/ira/message_bus.py.

Implement an async MessageBus class that is the backbone of all agent-to-agent communication. It should:

1. Use asyncio.Queue internally for message passing.
2. Have a method register_agent(agent_name: str, handler: Callable) that registers an agent's handler function for receiving messages.
3. Have an async method send(message: AgentMessage) -> AgentMessage that:
   a. Logs the message (from_agent, to_agent, query) to a conversation trace.
   b. Looks up the target agent's handler.
   c. Calls the handler with the message.
   d. Returns the response message.
4. Have an async method broadcast(from_agent: str, query: str, target_agents: list[str]) -> dict[str, str] that sends the same query to multiple agents in parallel using asyncio.gather() and returns a dict of agent_name -> response.
5. Have a method get_trace() -> list[AgentMessage] that returns the full conversation trace for debugging and logging.
6. Have a method clear_trace() to reset the trace.

The bus should be a singleton — there is only one bus in the entire application. Use a module-level instance.

This is intentionally simple. No external message brokers. No Redis. Just clean async Python. The power comes from the agents, not the plumbing.
```

### Step 2.2: The BaseAgent Class

**Cursor Prompt:**
```
Create src/ira/agents/base_agent.py.

Implement a BaseAgent class that ALL agents in the Pantheon inherit from. This is the most important class in the system. It should:

1. Constructor takes: name (str), role (str — this is the system prompt), tools (list[dict] — OpenAI function calling format), model (str — defaults to config openai_model), temperature (float — defaults to 0.3).
2. Have an async method execute(self, query: str, context: dict = None) -> str that:
   a. Builds the messages list: system message (from self.role), then user message (from query + context).
   b. Calls the OpenAI Chat Completions API with the messages and self.tools.
   c. Enters an agentic tool-calling loop:
      - If the response contains tool_calls, execute each tool by looking up the function in a tool_registry dict.
      - Append the tool results to the messages.
      - Call the API again with the updated messages.
      - Repeat until the model returns a final text response (no more tool calls).
   d. Returns the final text response.
3. Have a _tool_registry dict that maps tool function names to actual Python callables. This is populated during agent initialization.
4. Have a method register_tool(self, name: str, func: Callable) that adds a tool to the registry.
5. Have a property conversation_history that stores the last N interactions for context continuity.
6. Log every API call, tool invocation, and response using structlog.

The tool-calling loop is the heart of the agent. It must handle:
- Multiple sequential tool calls in one response.
- Errors in tool execution (catch, log, return error message to the model).
- A maximum iteration limit (default 10) to prevent infinite loops.
```

### Step 2.3: Athena — The CEO / Orchestrator

**Cursor Prompt:**
```
Create src/ira/agents/athena.py.

Implement the Athena agent by creating a function create_athena(message_bus: MessageBus) -> BaseAgent that:

1. Defines Athena's role (system prompt). She is the CEO and orchestrator. Her prompt should:
   - Explain that she leads a team of specialist agents.
   - List every agent by name, with a one-line description of their expertise.
   - Instruct her to ALWAYS delegate to the appropriate specialist rather than answering directly.
   - Tell her to synthesize responses from multiple agents when a query spans domains.
   - Tell her she can delegate to multiple agents in parallel for complex queries.

2. Defines her tools (OpenAI function calling format):
   - delegate_to_agent(agent_name: str, query: str, context: str = "") -> str
     Description: "Delegate a task to a specialist agent. Use this for EVERY query."
   - consult_multiple_agents(agents: list[dict with agent_name and query]) -> dict
     Description: "Consult multiple agents in parallel. Use when a query spans multiple domains."
   - request_clarification(question: str) -> str
     Description: "Ask the user a clarifying question before proceeding."

3. Implements the tool functions:
   - delegate_to_agent: Uses message_bus.send() to route the query to the named agent.
   - consult_multiple_agents: Uses message_bus.broadcast() to query multiple agents in parallel.
   - request_clarification: Returns a formatted clarification request.

4. Returns a BaseAgent instance with these tools registered.

Athena should NEVER answer a question herself. She is a pure orchestrator.
```

### Step 2.4: Clio — The Researcher

**Cursor Prompt:**
```
Create src/ira/agents/clio.py.

Implement create_clio(retriever: UnifiedRetriever, knowledge_graph: KnowledgeGraph) -> BaseAgent.

Clio is the Research Director. Her role prompt should explain that she is responsible for finding and synthesizing information from all knowledge sources. She is thorough, methodical, and always cites her sources.

Her tools:
1. search_knowledge(query: str, limit: int = 10) -> str
   Calls retriever.search() and formats results as a numbered list with source citations.
2. deep_research(query: str) -> str
   Calls retriever.decompose_and_search() for complex, multi-faceted queries.
3. search_by_category(query: str, category: str) -> str
   Calls retriever.search_by_category() for targeted searches (e.g., only in quotes, only in manuals).
4. query_knowledge_graph(cypher_query: str) -> str
   Calls knowledge_graph.run_cypher() for relationship-based queries.
5. find_related_entities(entity_name: str) -> str
   Calls knowledge_graph.find_related_entities() and formats the subgraph.
```

### Step 2.5: Prometheus — The CRO (Sales)

**Cursor Prompt:**
```
Create src/ira/agents/prometheus.py.

Implement create_prometheus(crm_db, sales_intel: SalesIntelligence) -> BaseAgent.

Prometheus is the Chief Revenue Officer. His role prompt should explain that he owns the entire sales pipeline, from lead generation to deal closure. He is data-driven, strategic, and always focused on revenue growth.

His tools:
1. get_pipeline_summary(filters: dict = None) -> str
   Queries the CRM for a summary of the current pipeline (deals by stage, total value, expected close dates).
2. get_lead_details(contact_id: str) -> str
   Retrieves full details for a specific lead including all interactions.
3. qualify_lead(contact_email: str, inquiry_text: str) -> str
   Calls sales_intel.qualify_lead() and returns the qualification result.
4. get_stale_leads(days: int = 14) -> str
   Calls sales_intel.identify_stale_leads() and formats the results.
5. update_deal_stage(deal_id: str, new_stage: str, notes: str) -> str
   Updates a deal's stage in the CRM and logs the interaction.
6. log_interaction(contact_email: str, channel: str, direction: str, summary: str) -> str
   Logs a new interaction in the CRM.
```

### Step 2.6: Plutus — The CFO (Finance)

**Cursor Prompt:**
```
Create src/ira/agents/plutus.py.

Implement create_plutus(pricing_engine: PricingEngine, crm_db) -> BaseAgent.

Plutus is the Chief Financial Officer. His role prompt should explain that he is responsible for all financial analysis, pricing strategy, and quote management. He is precise, analytical, and conservative in his estimates.

His tools:
1. estimate_price(machine_model: str, configuration: dict) -> str
   Calls pricing_engine.estimate_price() and formats the result with confidence ranges.
2. analyze_quotes(filters: dict) -> str
   Calls pricing_engine.analyze_quote_history() for aggregate statistics.
3. get_revenue_summary(period: str = "quarter") -> str
   Queries the CRM for revenue data (won deals) grouped by period.
4. generate_quote(contact_email: str, machine_model: str, configuration: dict) -> str
   Calls pricing_engine.generate_quote_content() and returns the formatted quote text.
5. compare_pricing(machine_model: str, regions: list[str]) -> str
   Analyzes pricing differences across regions for the same machine.
```

### Step 2.7: Hermes — The CMO (Marketing)

**Cursor Prompt:**
```
Create src/ira/agents/hermes.py.

Implement create_hermes(drip_engine, sales_intel: SalesIntelligence, retriever: UnifiedRetriever) -> BaseAgent.

Hermes is the Chief Marketing Officer. His role prompt should explain that he is responsible for all outbound marketing, drip campaigns, lead nurturing, and brand communication. He is creative, persuasive, and data-informed.

His tools:
1. get_campaign_status() -> str
   Returns the current status of all active drip campaigns (leads in pipeline, emails sent, reply rates).
2. draft_outreach_email(contact_email: str, context: str, tone: str = "professional") -> str
   Drafts a personalized outreach email for a specific lead, using their history and context.
3. get_lead_intelligence(company_name: str) -> str
   Calls sales_intel.generate_lead_intelligence() to get real-time context about a company.
4. suggest_campaign_improvements() -> str
   Analyzes recent campaign performance and suggests improvements.
5. prepare_board_meeting_brief(topic: str) -> str
   Researches a topic and prepares a brief for a board meeting discussion.
```

### Step 2.8: Remaining C-Suite Agents

**Cursor Prompt:**
```
Create the following agent files, each following the same pattern as the previous agents (create_<name> function returning a BaseAgent):

1. src/ira/agents/hephaestus.py — Chief Production Officer
   Role: Knows everything about Machinecraft's machines, production processes, inventory, and purchasing.
   Tools: get_machine_specs(model), recommend_machine(requirements), get_production_status(), check_inventory(item), compare_machines(model_a, model_b)
   Uses: MachineIntelligence module.

2. src/ira/agents/themis.py — Chief HR Officer
   Role: Manages all HR data, employee information, skills matrix, hiring, and company culture.
   Tools: get_employee_info(name), get_team_overview(), get_skills_matrix(), search_hr_policies(query)
   Uses: UnifiedRetriever (searching HR category documents).

3. src/ira/agents/calliope.py — Head of Communications / Writer
   Role: Drafts and polishes all external communication. Expert in Machinecraft's brand voice.
   Tools: draft_email(recipient, subject, key_points, tone), polish_text(text, style), draft_linkedin_post(topic), format_report(data, template)
   Uses: LLM only (no external tools needed — she IS the tool).

4. src/ira/agents/tyche.py — Pipeline Forecaster
   Role: Analyzes the sales pipeline to provide revenue forecasts, win/loss analysis, and deal velocity metrics.
   Tools: forecast_revenue(period), analyze_win_rate(filters), get_deal_velocity(), get_conversion_funnel()
   Uses: CRM database.

Each agent should have a detailed, personality-rich system prompt that defines their expertise, communication style, and decision-making approach.
```

### Step 2.9: Specialist Agents

**Cursor Prompt:**
```
Create the following specialist agent files:

1. src/ira/agents/delphi.py — Email Oracle / Classifier
   Role: Classifies inbound emails by intent and urgency. The first line of defense for the email processor.
   Tools: classify_email(subject, body, from_address) -> dict with intent (NEW_LEAD, CUSTOMER_QUESTION, FOLLOW_UP, INTERNAL, SPAM), urgency (HIGH, MEDIUM, LOW), and suggested_agent.

2. src/ira/agents/sphinx.py — Gatekeeper / Clarifier
   Role: Intercepts vague or ambiguous queries and asks clarifying questions before routing to specialists.
   Tools: assess_clarity(query) -> dict with is_clear (bool), missing_info (list), clarifying_questions (list).

3. src/ira/agents/vera.py — Fact Checker
   Role: Verifies facts, figures, and claims before they are included in responses. Cross-references multiple sources.
   Tools: verify_claim(claim, context) -> dict with verified (bool), confidence (float), sources (list), conflicts (list).
   Uses: UnifiedRetriever.

4. src/ira/agents/sophia.py — Reflector / Learner
   Role: Performs post-interaction analysis. Extracts lessons, identifies patterns, and scores conversation quality.
   Tools: reflect_on_interaction(conversation_log) -> dict with quality_score (0-100), lessons (list), improvement_suggestions (list).

5. src/ira/agents/iris.py — External Intelligence
   Role: Gathers intelligence from external sources (web, news, social media).
   Tools: search_web(query), get_company_news(company_name), monitor_industry(industry_name).
   Uses: httpx for web requests, NewsData API.

6. src/ira/agents/mnemosyne.py — Memory Keeper
   Role: Manages the CRM, contact records, and conversation history. The custodian of all relational data.
   Tools: upsert_contact(contact_data), log_interaction(interaction_data), get_contact_history(email), search_contacts(query).
   Uses: CRM database.

7. src/ira/agents/nemesis.py — Trainer / Adversarial Tester
   Role: Processes corrections, runs adversarial tests, and manages the sleep training pipeline.
   Tools: process_correction(original, corrected, context), run_stress_test(agent_name, test_queries), get_correction_log().

8. src/ira/agents/arachne.py — Content Creator
   Role: Creates newsletter content, LinkedIn posts, and other marketing materials.
   Tools: draft_newsletter(topic, audience), draft_linkedin_post(topic), create_content_calendar(period).
```

### Step 2.10: The Pantheon Registry

**Cursor Prompt:**
```
Create src/ira/pantheon.py.

This is the master file that initializes the entire agent organization. Implement:

1. An async function initialize_pantheon(config: Settings) -> dict[str, BaseAgent] that:
   a. Initializes all shared services (EmbeddingService, QdrantManager, KnowledgeGraph, UnifiedRetriever, MachineIntelligence, PricingEngine, SalesIntelligence, DeterministicRouter).
   b. Creates the MessageBus singleton.
   c. Creates every agent using their create_<name> functions, passing the appropriate services.
   d. Registers every agent's handler on the MessageBus.
   e. Returns a dict mapping agent names to agent instances.

2. A get_athena() convenience function that returns the Athena (orchestrator) agent.

3. A get_agent(name: str) convenience function that returns any agent by name.

4. A list_agents() function that returns a formatted table of all agents with their names and roles.

The initialization order matters — services first, then agents that depend on those services. Use dependency injection throughout.
```

### Step 2.11: Board Meetings

**Cursor Prompt:**
```
Create src/ira/systems/board_meeting.py.

Implement a BoardMeeting class that orchestrates collaborative discussions between multiple agents. It should:

1. Initialize with the MessageBus and a list of default board members (agent names).
2. Have an async method run_meeting(topic: str, participants: list[str] = None) -> BoardMeetingMinutes that:
   a. If participants is None, use the default board (Athena, Prometheus, Plutus, Hermes, Hephaestus, Themis).
   b. Sends the topic to each participant agent via message_bus.broadcast().
   c. Collects all responses into a contributions dict.
   d. Passes all contributions to an LLM to synthesize a meeting summary, identify key themes, resolve disagreements, and generate action items.
   e. Returns a BoardMeetingMinutes object.
3. Have an async method run_focused_meeting(topic: str, lead_agent: str, supporting_agents: list[str]) -> BoardMeetingMinutes that:
   a. First gets the lead agent's detailed analysis.
   b. Then shares the lead's analysis with supporting agents for their input.
   c. Synthesizes the final result.
4. Store meeting minutes in a local SQLite database (board_meetings.db) with full text search capability.
5. Have a method get_past_meetings(topic_filter: str = None, limit: int = 10) -> list[BoardMeetingMinutes].

Board meetings are a key differentiator of this system. They allow complex, multi-perspective analysis that no single agent could provide.
```

### Step 2.12: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_agents.py with pytest-asyncio tests for:

1. BaseAgent: Test that execute() calls the OpenAI API and handles tool calls correctly. Mock the API.
2. Athena: Test that she delegates a sales query to Prometheus. Mock the MessageBus.
3. MessageBus: Test send(), broadcast(), and get_trace().
4. DeterministicRouter: Test that it correctly classifies queries for each IntentCategory.
5. BoardMeeting: Test that run_meeting() collects contributions from all participants and produces a synthesis.

Use pytest fixtures for shared setup.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_agents.py -v
git add . && git commit -m "Phase 2: Pantheon complete — 16 agents, MessageBus, Board Meetings, Deterministic Router"
```

**Phase 2 Outcome:** A complete multi-agent organization. Athena can delegate to any of 15 specialist agents. Agents can consult each other. Board meetings can synthesize multi-perspective analysis. The Deterministic Router provides fast-path routing for common queries.

---

## Phase 3: The Body — Biological Systems

**Goal:** Implement the full suite of biological metaphor systems that give Ira her operational rhythm, self-healing capabilities, adaptive behavior, and sensory integration. These systems transform Ira from a reactive chatbot into a living, breathing agent.

**Estimated Time:** 3-4 hours.

### Step 3.1: Digestive System (Data Ingestion & Nutrient Extraction)

**Cursor Prompt:**
```
Create src/ira/systems/digestive.py.

Implement a DigestiveSystem class that orchestrates the full data ingestion pipeline using a biological metaphor. It should:

1. Initialize with DocumentIngestor, KnowledgeGraph, and EmbeddingService.
2. Have an async method ingest(raw_data: str, source: str, source_category: str) -> dict that runs the full pipeline:
   a. MOUTH: Receive raw data (text, email body, document content).
   b. STOMACH (Enrichment): Use an LLM to extract structured "nutrients" from the raw data:
      - "protein" (high-value facts, figures, names, dates, decisions)
      - "carbs" (general context, background information)
      - "waste" (noise, pleasantries, signatures, disclaimers)
   c. SMALL INTESTINE (Absorption): Take only the "protein" and "carbs", chunk them, embed them, and upsert into Qdrant.
   d. LIVER (Entity Extraction): Extract entities and relationships from the protein content and add them to the Neo4j knowledge graph.
   e. Return a dict with nutrients_extracted (counts), chunks_created, entities_found, and processing_time.

3. Have an async method ingest_email(email: Email) -> dict that:
   a. Extracts the email body and any attachment text.
   b. Runs the full ingest() pipeline.
   c. Additionally extracts: sender info, company mentions, machine mentions, pricing mentions, dates/deadlines.
   d. Returns enriched metadata alongside the standard ingest results.

4. Have an async method batch_ingest(items: list[dict]) -> dict that processes multiple items, logging progress and handling errors gracefully.

The key insight: not all data is equal. The nutrient extraction step ensures we only store high-value information, keeping the knowledge base clean and relevant.
```

### Step 3.2: Respiratory System (Operational Cadence)

**Cursor Prompt:**
```
Create src/ira/systems/respiratory.py.

Implement a RespiratorySystem class that manages Ira's operational rhythm using asyncio background tasks and APScheduler. It should:

1. Initialize with references to DigestiveSystem, DreamMode (from Phase 4), DripEngine (from Phase 5), and ImmuneSystem.

2. HEARTBEAT (every 5 minutes):
   - Log that Ira is alive with a timestamp.
   - Record basic vitals: memory usage, active connections, queue sizes.
   - If any vital is unhealthy, trigger the ImmuneSystem.

3. INHALE CYCLE (configurable, default 6:00 AM daily):
   - Trigger the DigestiveSystem to ingest any new documents in data/imports/.
   - Trigger the EmailProcessor to fetch and process new emails.
   - Log a summary of what was ingested.

4. EXHALE CYCLE (configurable, default 10:00 PM daily):
   - Trigger DreamMode.run_dream_cycle().
   - Trigger the DripEngine to evaluate campaign performance.
   - Generate a daily summary report and send it to the admin Telegram chat.

5. BREATH TIMING (per-request):
   - Have a context manager `async with respiratory.breath():` that measures the processing time of each request and logs it as a "breath duration" metric.
   - Track average breath duration over time as a health indicator.

6. Have start() and stop() methods to manage the background task lifecycle.
7. Use APScheduler for the scheduled tasks (Inhale, Exhale) and asyncio.create_task for the Heartbeat.
```

### Step 3.3: Immune System (Error Handling & Self-Healing)

**Cursor Prompt:**
```
Create src/ira/systems/immune.py.

Implement an ImmuneSystem class that provides comprehensive error monitoring, health checking, and self-healing capabilities. It should:

1. Initialize with references to all external service clients (Qdrant, Neo4j, PostgreSQL, OpenAI, Voyage).

2. STARTUP VALIDATION:
   - Have an async method run_startup_validation() -> dict that checks every external service:
     a. Qdrant: Ping and verify collections exist.
     b. Neo4j: Run a simple Cypher query.
     c. PostgreSQL: Execute a simple SELECT.
     d. OpenAI API: Make a minimal API call.
     e. Voyage API: Make a minimal embed call.
   - Return a dict with service_name -> {status: "healthy"/"unhealthy", latency_ms, error}.
   - If any critical service is unhealthy, raise a SystemHealthError with details.

3. ERROR LOGGING:
   - Have a method log_error(error: Exception, context: dict) that logs errors with full context using structlog.
   - Track error frequency per service and per error type.
   - If error frequency exceeds a threshold (e.g., 5 errors in 1 minute for the same service), trigger an ALERT.

4. ALERTING:
   - Have an async method send_alert(message: str, severity: str) that sends a Telegram message to the admin chat.

5. KNOWLEDGE HEALTH:
   - Have an async method check_knowledge_health() -> dict that:
     a. Checks Qdrant collection sizes and last update timestamps.
     b. Identifies stale data (not updated in >30 days).
     c. Checks for orphaned entities in Neo4j.
   - Return a health report.

6. SELF-HEALING:
   - Have an async method attempt_recovery(service_name: str) that tries basic recovery actions:
     a. For Qdrant: Reconnect.
     b. For Neo4j: Reconnect.
     c. For PostgreSQL: Reconnect and run pending migrations.
   - Log all recovery attempts and outcomes.
```

### Step 3.4: Endocrine System (Adaptive Behavior)

**Cursor Prompt:**
```
Create src/ira/systems/endocrine.py.

Implement an EndocrineSystem class that manages Ira's adaptive behavior through "hormone" levels that influence response style and decision-making. It should:

1. Define hormone levels as float values (0.0 to 1.0):
   - confidence: How confident Ira is in her current knowledge (affected by successful/failed retrievals).
   - energy: How responsive Ira should be (affected by system load and time of day).
   - growth_signal: How much Ira is learning (affected by new data ingestion and corrections).
   - stress: How much error pressure the system is under (affected by error rates).

2. Have methods to adjust levels:
   - boost(hormone: str, amount: float) — increase a level (capped at 1.0).
   - reduce(hormone: str, amount: float) — decrease a level (floored at 0.0).
   - decay_all(factor: float = 0.95) — gradually decay all levels toward baseline (called periodically).

3. Have a method get_behavioral_modifiers() -> dict that translates hormone levels into concrete behavioral adjustments:
   - High confidence + low stress → more assertive, shorter responses.
   - Low confidence + high stress → more cautious, includes caveats, suggests human review.
   - High growth_signal → more curious, asks more follow-up questions.
   - Low energy → shorter responses, defers complex tasks.

4. These modifiers should be injected into agent system prompts as additional context.
```

### Step 3.5: Musculoskeletal System (Action-to-Learning Feedback)

**Cursor Prompt:**
```
Create src/ira/systems/musculoskeletal.py.

Implement a MusculoskeletalSystem class that tracks every action Ira takes and extracts learning signals ("myokines") from the outcomes. It should:

1. Define an ActionRecord model: action_type (EMAIL_SENT, QUOTE_GENERATED, DEAL_UPDATED, LEAD_QUALIFIED, etc.), target (who/what), details (dict), timestamp, outcome (PENDING, SUCCESS, FAILURE, NO_RESPONSE).

2. Have an async method record_action(action: ActionRecord) that stores the action in a database table.

3. Have an async method update_outcome(action_id: UUID, outcome: str, outcome_details: dict) that updates an action's outcome when it becomes known (e.g., email got a reply, quote was accepted).

4. Have an async method extract_myokines(period_days: int = 7) -> dict that analyzes recent actions and extracts learning signals:
   - Email reply rates by tone/style/time-of-day.
   - Quote conversion rates by machine/region/price-point.
   - Lead qualification accuracy (predicted score vs actual outcome).
   - Most effective outreach strategies.

5. These myokines should feed into the DreamMode for overnight consolidation and into the EndocrineSystem to adjust behavior.
```

### Step 3.6: Sensory System (Cross-Channel Integration)

**Cursor Prompt:**
```
Create src/ira/systems/sensory.py.

Implement a SensorySystem class that provides unified perception across all input channels. It should:

1. Define a PerceptionEvent model: channel (TELEGRAM, EMAIL, CLI, API), raw_input (str), sender_id (str), sender_name (str optional), timestamp, metadata (dict).

2. Have an async method perceive(event: PerceptionEvent) -> dict that:
   a. Resolves the sender's identity across channels (same person on Telegram and Email should be recognized as one entity). Use email address as the primary key, with a mapping table for Telegram user IDs.
   b. Retrieves the sender's conversation history and relationship context.
   c. Detects the emotional state of the message (using the EmotionalIntelligence module from Phase 4).
   d. Returns a unified perception dict with: resolved_contact, emotional_state, conversation_history, channel_context.

3. Have a method resolve_identity(channel: str, sender_id: str) -> Contact that looks up or creates a contact record.

4. This unified perception is passed as context to Athena for every incoming message, regardless of channel.
```

### Step 3.7: Voice System (Response Shaping)

**Cursor Prompt:**
```
Create src/ira/systems/voice.py.

Implement a VoiceSystem class that shapes Ira's responses based on channel, recipient, and behavioral modifiers. It should:

1. Define channel-specific formatting rules:
   - TELEGRAM: Max 2000 chars, use Markdown formatting, concise and direct.
   - EMAIL: Formal tone, proper greeting/closing, can be longer and more detailed.
   - CLI: Technical, detailed, can include code blocks and tables.
   - API: JSON-structured, no formatting.

2. Have an async method shape_response(raw_response: str, channel: str, recipient: Contact, behavioral_modifiers: dict) -> str that:
   a. Applies channel-specific formatting rules.
   b. Adjusts tone based on the recipient's relationship warmth level (STRANGER → formal, TRUSTED → casual).
   c. Applies behavioral modifiers from the EndocrineSystem (e.g., if confidence is low, add caveats).
   d. Enforces length limits for the channel.
   e. Returns the shaped response.

3. Have a method detect_preferred_style(contact: Contact) -> dict that analyzes past interactions to determine the contact's preferred communication style (formal/casual, detailed/brief, technical/simple).
```

### Step 3.8: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_systems.py with pytest-asyncio tests for:

1. DigestiveSystem: Test that ingest() correctly separates protein/carbs/waste from a sample email. Mock the LLM call.
2. RespiratorySystem: Test that start() creates background tasks and stop() cancels them.
3. ImmuneSystem: Test run_startup_validation() with mocked healthy and unhealthy services.
4. EndocrineSystem: Test that boost/reduce/decay work correctly and behavioral modifiers are generated.
5. SensorySystem: Test identity resolution across channels.
6. VoiceSystem: Test that responses are correctly shaped for different channels.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_systems.py -v
git add . && git commit -m "Phase 3: Body complete — Digestive, Respiratory, Immune, Endocrine, Musculoskeletal, Sensory, Voice systems"
```

**Phase 3 Outcome:** Ira now has a complete biological infrastructure. She ingests data intelligently (Digestive), operates on a daily rhythm (Respiratory), monitors her own health (Immune), adapts her behavior (Endocrine), learns from her actions (Musculoskeletal), perceives across channels (Sensory), and shapes her voice (Voice).

---

## Phase 4: The Mind — Advanced Memory Architecture

**Goal:** Implement the complete memory system — from short-term conversation memory through long-term Mem0 storage, episodic consolidation, procedural learning, meta-cognition, emotional intelligence, inner voice, relationship tracking, and dream mode.

**Estimated Time:** 4-5 hours.

### Step 4.1: Conversation Memory (Short-Term)

**Cursor Prompt:**
```
Create src/ira/memory/conversation.py.

Implement a ConversationMemory class that manages per-user, per-channel conversation history. It should:

1. Store conversations in a SQLite database (conversations.db) with tables:
   - conversations: id, user_id, channel, started_at, last_message_at
   - messages: id, conversation_id, role (user/assistant/system), content, timestamp

2. Have an async method add_message(user_id: str, channel: str, role: str, content: str) that appends a message to the current conversation.

3. Have an async method get_history(user_id: str, channel: str, limit: int = 20) -> list[dict] that retrieves the most recent messages for a user.

4. Have an async method extract_entities(message: str) -> list[dict] that uses an LLM to extract entities (people, companies, machines, dates, amounts) from a message.

5. Have an async method resolve_coreferences(message: str, history: list[dict]) -> str that resolves pronouns and references ("he", "that machine", "the quote") to their actual entities using conversation context.

6. Have a method should_start_new_conversation(user_id: str, channel: str) -> bool that returns True if the last message was more than 30 minutes ago (indicating a new topic).
```

### Step 4.2: Long-Term Memory (Mem0)

**Cursor Prompt:**
```
Create src/ira/memory/long_term.py.

Implement a LongTermMemory class that wraps the Mem0 API for persistent, semantic memory storage. It should:

1. Initialize with the Mem0 API key from config.

2. Have an async method store(content: str, user_id: str = "global", metadata: dict = None) that stores a memory in Mem0 with metadata tags.

3. Have an async method search(query: str, user_id: str = "global", limit: int = 5) -> list[dict] that performs semantic search across stored memories.

4. Have an async method store_correction(original: str, corrected: str, context: str) that stores a user correction as a high-priority memory with a "correction" tag.

5. Have an async method store_preference(user_id: str, preference_type: str, value: str) that stores a user preference (e.g., communication style, technical level).

6. Have an async method get_user_preferences(user_id: str) -> dict that retrieves all stored preferences for a user.

7. Have an async method store_fact(fact: str, source: str, confidence: float) that stores a verified fact with source attribution.

8. Implement memory decay: have a method apply_decay(days_old: int) -> float that returns a relevance multiplier based on the Ebbinghaus forgetting curve. Memories that are frequently accessed should decay slower.
```

### Step 4.3: Episodic Memory

**Cursor Prompt:**
```
Create src/ira/memory/episodic.py.

Implement an EpisodicMemory class that converts raw conversations into structured episodic memories — narrative summaries of significant interactions. It should:

1. Have an async method consolidate_episode(conversation: list[dict], user_id: str) -> dict that:
   a. Uses an LLM to summarize the conversation into a narrative episode.
   b. Extracts: key_topics, decisions_made, commitments, emotional_tone, relationship_impact.
   c. Stores the episode in both Mem0 (for semantic search) and a local SQLite table (for structured queries).
   d. Returns the episode dict.

2. Have an async method weave_episodes(user_id: str, topic: str = None) -> str that:
   a. Retrieves related episodes for a user (optionally filtered by topic).
   b. Uses an LLM to weave them into a coherent narrative ("The story so far with this customer...").
   c. Returns the narrative.

3. Have an async method surface_relevant_episodes(query: str, user_id: str) -> list[dict] that finds episodes relevant to the current query, providing the agent with historical context.
```

### Step 4.4: Procedural Memory

**Cursor Prompt:**
```
Create src/ira/memory/procedural.py.

Implement a ProceduralMemory class that learns and stores procedures — optimized response patterns for recurring request types. It should:

1. Define a Procedure model: trigger_pattern (str), steps (list[str]), success_rate (float), times_used (int), last_used (datetime).

2. Have an async method learn_procedure(query: str, successful_response_path: list[str]) that:
   a. Analyzes the query to extract a generalizable trigger pattern.
   b. Stores the response path (which agents were consulted, which tools were used, in what order) as a procedure.
   c. If a similar procedure already exists, update its success rate and merge the steps.

3. Have a method find_procedure(query: str) -> Procedure or None that checks if there's a known procedure for this type of query.

4. Have a method get_top_procedures(limit: int = 10) -> list[Procedure] that returns the most frequently used and successful procedures.

5. Procedures should be used by Athena to optimize routing — if a known procedure exists, she can skip the LLM routing step and directly follow the procedure.
```

### Step 4.5: Meta-Cognition

**Cursor Prompt:**
```
Create src/ira/memory/metacognition.py.

Implement a Metacognition class that provides self-awareness about what Ira knows and doesn't know. It should:

1. Use the KnowledgeState enum from models.py (KNOW_VERIFIED, KNOW_UNVERIFIED, PARTIAL, UNCERTAIN, CONFLICTING, UNKNOWN).

2. Have an async method assess_knowledge(query: str, retrieved_context: list[dict]) -> dict that:
   a. Analyzes the retrieved context for relevance, recency, and source quality.
   b. Checks for conflicting information across sources.
   c. Determines the KnowledgeState.
   d. Returns a dict with: state (KnowledgeState), confidence (0.0-1.0), sources (list), conflicts (list if any), gaps (list of what's missing).

3. Have a method generate_confidence_prefix(state: KnowledgeState, confidence: float) -> str that returns a natural language prefix for the response:
   - KNOW_VERIFIED + high confidence: "Based on our machine manual..."
   - UNCERTAIN: "I'm not entirely certain, but based on available information..."
   - CONFLICTING: "I found conflicting information on this. Source A says X, while Source B says Y..."
   - UNKNOWN: "I don't have reliable information on this. I'd recommend checking with..."

4. Have an async method log_knowledge_gap(query: str, state: KnowledgeState) that records queries where Ira's knowledge was insufficient, feeding into Dream Mode's gap detection.
```

### Step 4.6: Emotional Intelligence

**Cursor Prompt:**
```
Create src/ira/memory/emotional_intelligence.py.

Implement an EmotionalIntelligence class that detects and responds to emotional states in communication. It should:

1. Use the EmotionalState enum from models.py.

2. Have an async method detect_emotion(text: str) -> dict that:
   a. First applies fast regex-based detection for obvious signals (exclamation marks, urgency words, gratitude words).
   b. If inconclusive, uses an LLM to analyze the emotional tone.
   c. Returns: state (EmotionalState), intensity (MILD/MODERATE/STRONG), indicators (list of detected signals).

3. Have a method get_response_adjustment(emotional_state: EmotionalState, intensity: str) -> dict that returns adjustments to apply to the response:
   - STRESSED/FRUSTRATED: More empathetic, acknowledge the difficulty, offer concrete help.
   - URGENT: Prioritize speed, be direct, skip pleasantries.
   - GRATEFUL: Warm acknowledgment, reinforce the relationship.
   - CURIOUS: Provide more detail, offer to explore further.

4. Track emotional patterns per user over time. Have a method get_emotional_profile(user_id: str) -> dict that returns the user's typical emotional patterns.
```

### Step 4.7: Inner Voice

**Cursor Prompt:**
```
Create src/ira/memory/inner_voice.py.

Implement an InnerVoice class that gives Ira a rich internal monologue and evolving personality. It should:

1. Define PersonalityTrait model: name (str), value (float 0.0-1.0), description (str).
   Default traits: warmth (0.7), directness (0.6), humor (0.3), curiosity (0.8), formality (0.5), empathy (0.7).

2. Define ReflectionType enum: OBSERVATION, OPINION, CELEBRATION, CURIOSITY, CONNECTION, CONCERN.

3. Have an async method reflect(context: str, trigger: str) -> dict that:
   a. Uses an LLM with a special "inner voice" system prompt that embodies Ira's personality traits.
   b. Generates an internal reflection about the current situation.
   c. Returns: reflection_type, content, should_surface (bool — whether this reflection should be included in the response to the user).

4. Have a method update_trait(trait_name: str, delta: float, reason: str) that adjusts a personality trait based on feedback:
   - Positive feedback on warm responses → increase warmth.
   - User prefers direct answers → increase directness.
   - Log every trait change with the reason.

5. Have a method get_personality_summary() -> str that returns a natural language description of Ira's current personality state.

6. Occasionally (configurable probability, default 10%), the inner voice should surface a reflection in the response — a personal observation, a connection to a past conversation, or a curious question. This makes Ira feel more human.
```

### Step 4.8: Relationship Memory

**Cursor Prompt:**
```
Create src/ira/memory/relationship.py.

Implement a RelationshipMemory class that tracks the depth and quality of Ira's relationships with each contact. It should:

1. Use the WarmthLevel enum from models.py (STRANGER → ACQUAINTANCE → FAMILIAR → WARM → TRUSTED).

2. Define a Relationship model: contact_id, warmth_level, interaction_count, memorable_moments (list), learned_preferences (dict), last_interaction (datetime).

3. Have an async method update_relationship(contact_id: str, interaction: Interaction) -> Relationship that:
   a. Increments the interaction count.
   b. Checks if the warmth level should be upgraded based on interaction frequency and quality.
   c. Extracts any memorable moments from the interaction (personal shares, celebrations, difficulties).
   d. Updates learned preferences.
   e. Returns the updated relationship.

4. Have a method get_relationship(contact_id: str) -> Relationship.

5. Have a method get_greeting_style(relationship: Relationship) -> str that returns the appropriate greeting style:
   - STRANGER: "Hello, thank you for reaching out to Machinecraft."
   - TRUSTED: "Hey [first name]! Great to hear from you."

6. Warmth progression rules:
   - STRANGER → ACQUAINTANCE: After 3+ interactions.
   - ACQUAINTANCE → FAMILIAR: After 10+ interactions over 2+ weeks.
   - FAMILIAR → WARM: After 20+ interactions with positive sentiment.
   - WARM → TRUSTED: Manual promotion only (admin decision).
```

### Step 4.9: Goal Manager

**Cursor Prompt:**
```
Create src/ira/memory/goal_manager.py.

Implement a GoalManager class that tracks goal-oriented dialogues — multi-turn conversations aimed at achieving a specific outcome. It should:

1. Define GoalType enum: LEAD_QUALIFICATION, MEETING_BOOKING, QUOTE_PREPARATION, FOLLOW_UP_SCHEDULING, INFORMATION_GATHERING.

2. Define a Goal model: id, goal_type, contact_id, status (ACTIVE/COMPLETED/ABANDONED), required_slots (dict of slot_name -> value or None), progress (float 0.0-1.0), created_at, completed_at.

3. Have an async method detect_goal(query: str, context: dict) -> Goal or None that analyzes the conversation to detect if a goal-oriented dialogue should be initiated.

4. Have an async method update_goal(goal_id: UUID, new_info: dict) -> Goal that fills in slots based on new information from the conversation.

5. Have a method get_next_question(goal: Goal) -> str that determines what information is still needed and generates the next question to ask.

6. Have a method is_goal_complete(goal: Goal) -> bool that checks if all required slots are filled.

7. Goals should be used by Athena to steer conversations proactively. For example, if a new lead emails, Athena should initiate a LEAD_QUALIFICATION goal and systematically gather: company name, industry, machine interest, volume requirements, timeline, budget range.
```

### Step 4.10: Dream Mode (Nightly Consolidation)

**Cursor Prompt:**
```
Create src/ira/memory/dream_mode.py.

Implement a DreamMode class that performs overnight memory consolidation, knowledge gap detection, and creative synthesis. This is one of the most important modules in the system. It should:

1. Initialize with LongTermMemory, EpisodicMemory, ConversationMemory, MusculoskeletalSystem, and UnifiedRetriever.

2. Have an async method run_dream_cycle() -> DreamReport that performs the full dream cycle:

   a. STAGE 1 — MEMORY CONSOLIDATION (Light Sleep):
      - Retrieve all conversations from the past 24 hours.
      - Consolidate each into episodic memories using EpisodicMemory.
      - Apply the Ebbinghaus forgetting curve to all memories, decaying old ones.
      - Strengthen memories that were accessed multiple times.

   b. STAGE 2 — KNOWLEDGE GAP DETECTION (Deep Sleep):
      - Retrieve all queries from the past 24 hours that resulted in UNCERTAIN, CONFLICTING, or UNKNOWN knowledge states (from Metacognition logs).
      - Group them by topic.
      - Generate a prioritized list of knowledge gaps that need to be filled.

   c. STAGE 3 — CREATIVE SYNTHESIS (REM Sleep):
      - Take the top 5 knowledge gaps and the most significant episodic memories.
      - Use an LLM with a creative prompt to find novel connections between disparate pieces of information.
      - Generate hypotheses and insights (e.g., "Customer X in Germany and Customer Y in India both asked about the same machine feature — this might indicate a broader market trend").

   d. STAGE 4 — CAMPAIGN REFLECTION (Dream Reflection):
      - Retrieve myokines from the MusculoskeletalSystem for the past 7 days.
      - Analyze drip campaign performance: which emails got replies, which didn't, what patterns emerge.
      - Generate campaign improvement suggestions.

   e. STAGE 5 — REPORT GENERATION:
      - Compile all findings into a DreamReport.
      - Store the report in the database.
      - Return the report.

3. Have a method get_dream_reports(limit: int = 7) -> list[DreamReport] for reviewing past dream cycles.
```

### Step 4.11: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_memory.py with pytest-asyncio tests for:

1. ConversationMemory: Test add_message and get_history. Test entity extraction with a sample message.
2. LongTermMemory: Test store and search. Mock the Mem0 API.
3. EpisodicMemory: Test consolidate_episode with a sample conversation. Mock the LLM.
4. Metacognition: Test assess_knowledge with high-confidence and low-confidence scenarios.
5. EmotionalIntelligence: Test detect_emotion with sample texts for each emotional state.
6. InnerVoice: Test reflect and update_trait.
7. RelationshipMemory: Test warmth level progression.
8. DreamMode: Test run_dream_cycle end-to-end. Mock all dependencies.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_memory.py -v
git add . && git commit -m "Phase 4: Mind complete — Conversation, Long-Term, Episodic, Procedural, Meta-Cognition, Emotional Intelligence, Inner Voice, Relationship, Goal Manager, Dream Mode"
```

**Phase 4 Outcome:** Ira now has a complete cognitive architecture. She remembers conversations, stores long-term facts, consolidates episodes, learns procedures, knows what she knows (and doesn't know), detects emotions, has an inner voice, tracks relationships, manages goals, and dreams at night to consolidate and improve.

---

## Phase 5: The Business — CRM, Drip Engine, and Quote Lifecycle

**Goal:** Build the complete business operations layer — the CRM database, the autonomous drip marketing engine, and the quote lifecycle management system.

**Estimated Time:** 3-4 hours.

### Step 5.1: CRM Database (PostgreSQL)

**Cursor Prompt:**
```
Create src/ira/data/crm.py.

Implement the CRM database using SQLAlchemy 2.0 with async support. Define the following SQLAlchemy ORM models:

1. Company: id (UUID), name (unique), region, industry, website, employee_count, notes, created_at, updated_at.
2. Contact: id (UUID), company_id (FK), name, email (unique), phone, role, source, lead_score (float), warmth_level (enum), tags (JSON), created_at, updated_at.
3. Deal: id (UUID), contact_id (FK), title, value (Decimal), currency, stage (enum: NEW, CONTACTED, ENGAGED, QUALIFIED, PROPOSAL, NEGOTIATION, WON, LOST), machine_model, expected_close_date, actual_close_date, notes, created_at, updated_at.
4. Interaction: id (UUID), contact_id (FK), deal_id (FK optional), channel (enum), direction (enum), subject, content, sentiment (float optional), created_at.
5. DripCampaign: id (UUID), name, target_segment (JSON), status (ACTIVE/PAUSED/COMPLETED), created_at.
6. DripStep: id (UUID), campaign_id (FK), contact_id (FK), step_number, email_subject, email_body, scheduled_at, sent_at, reply_received (bool), reply_content, opened (bool).

Implement a CRMDatabase class with:
- async create_tables() using the async engine.
- CRUD methods for each model (create, get_by_id, get_by_email, update, list with filters).
- async get_pipeline_summary(filters) -> dict with deals grouped by stage, total values, and counts.
- async get_stale_leads(days) -> list of contacts with no recent interaction.
- async get_deal_velocity() -> dict with average time in each stage.
- async search_contacts(query: str) -> list using ILIKE on name, email, company.

Use asyncpg as the async PostgreSQL driver. Use Alembic for migrations.
```

### Step 5.2: Quote Lifecycle Management

**Cursor Prompt:**
```
Create src/ira/data/quotes.py.

Implement a QuoteManager class that manages the full quote lifecycle. It should:

1. Define a Quote SQLAlchemy model: id (UUID), contact_id (FK), company_name, machine_model, configuration (JSON), estimated_value (Decimal), currency, status (DRAFT, SENT, FOLLOW_UP_1, FOLLOW_UP_2, FOLLOW_UP_3, WON, LOST, EXPIRED), created_at, sent_at, last_follow_up_at, closed_at, notes.

2. CRUD methods for quotes.

3. Have an async method create_quote_from_inquiry(contact: Contact, inquiry_text: str, pricing_engine: PricingEngine) -> Quote that:
   a. Extracts machine model and configuration from the inquiry.
   b. Gets a price estimate from the PricingEngine.
   c. Creates a Quote record in DRAFT status.

4. Have an async method advance_quote(quote_id: UUID, new_status: str, notes: str) that transitions a quote to the next status and logs the event.

5. Have an async method get_quotes_due_for_followup(days_since_last: int = 7) -> list[Quote] that finds quotes in SENT or FOLLOW_UP_N status that haven't been followed up recently.

6. Have an async method link_quote_to_deal(quote_id: UUID, deal_id: UUID) that connects a quote to a CRM deal.

7. Have an async method get_quote_analytics(filters: dict) -> dict with conversion rates, average deal size, time-to-close, and win/loss reasons.
```

### Step 5.3: Autonomous Drip Engine

**Cursor Prompt:**
```
Create src/ira/systems/drip_engine.py.

Implement an AutonomousDripEngine class that manages multi-step email outreach campaigns. This is the "farmer" functionality — Ira as a persistent, intelligent sales development representative. It should:

1. Initialize with CRMDatabase, QuoteManager, MessageBus (to delegate to Hermes for email drafting), and the Gmail sending capability.

2. Have an async method create_campaign(name: str, target_segment: dict, steps: list[dict]) -> DripCampaign that:
   a. Creates a campaign with defined steps (e.g., Step 1: Introduction, Step 2: Value prop, Step 3: Case study, Step 4: Meeting request).
   b. Selects matching contacts from the CRM based on the target_segment filters (region, industry, lead_score range, warmth_level).
   c. Creates DripStep records for each contact × step combination.

3. Have an async method run_campaign_cycle() that:
   a. Finds all DripSteps that are due to be sent (based on scheduled_at and not yet sent).
   b. For each step:
      - Gathers context about the contact (company, past interactions, machine interests).
      - Delegates to Hermes agent to draft a personalized email.
      - Sends the email via Gmail API.
      - Updates the DripStep record with sent_at.
      - Logs the interaction in the CRM.
   c. Checks for replies to previously sent drip emails and updates reply_received.

4. Have an async method evaluate_campaign(campaign_id: UUID) -> dict that:
   a. Calculates open rates, reply rates, and conversion rates per step.
   b. Identifies which email styles/topics got the best engagement.
   c. Generates improvement suggestions using an LLM.

5. Have an async method auto_adjust_campaign(campaign_id: UUID) that:
   a. Based on evaluation results, adjusts future email content and timing.
   b. Pauses outreach to contacts who have explicitly opted out or shown negative sentiment.

6. EUROPEAN DRIP CAMPAIGN: Include a pre-built campaign template specifically for European leads, with:
   - Culturally appropriate messaging.
   - GDPR compliance checks.
   - Timezone-aware scheduling.
```

### Step 5.4: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_crm.py with pytest-asyncio tests for:

1. CRMDatabase: Test CRUD operations for contacts, deals, and interactions. Use an in-memory SQLite database for testing.
2. QuoteManager: Test create_quote_from_inquiry and advance_quote lifecycle.
3. AutonomousDripEngine: Test create_campaign and run_campaign_cycle. Mock the Gmail sending and Hermes agent.
4. Test get_pipeline_summary returns correct aggregations.
5. Test get_stale_leads identifies the correct contacts.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_crm.py -v
git add . && git commit -m "Phase 5: Business complete — CRM, Quote Lifecycle, Autonomous Drip Engine"
```

**Phase 5 Outcome:** Ira now has a complete business operations layer. She can manage contacts, track deals through the pipeline, handle the full quote lifecycle, and autonomously run multi-step drip marketing campaigns that learn and improve over time.

---

## Phase 6: The Interfaces — Telegram, Email, CLI, and API Server

**Goal:** Build all the user-facing interfaces and the main application server that ties everything together.

**Estimated Time:** 3-4 hours.

### Step 6.1: Email Processor (ira@machinecraft.org)

**Cursor Prompt:**
```
Create src/ira/interfaces/email_processor.py.

Implement an EmailProcessor class that manages the ira@machinecraft.org inbox. It should:

1. Initialize with Google Workspace credentials, the Pantheon (for agent access), DigestiveSystem, and CRMDatabase.

2. Have an async method fetch_new_emails(max_results: int = 20) -> list[Email] that:
   a. Connects to Gmail API using the service account or OAuth credentials.
   b. Fetches unread emails from the inbox.
   c. Parses them into Email model objects.
   d. Marks them as read.

3. Have an async method process_email(email: Email) -> dict that runs the full processing pipeline:
   a. CLASSIFY: Delegate to Delphi agent to classify the email (intent, urgency, suggested_agent).
   b. DIGEST: Pass the email through the DigestiveSystem for nutrient extraction.
   c. RESOLVE IDENTITY: Use the SensorySystem to resolve the sender to a CRM contact (create if new).
   d. ROUTE: Based on classification, route to the appropriate agent via Athena:
      - NEW_LEAD: Route to Prometheus for lead qualification, then to Hermes for response drafting.
      - CUSTOMER_QUESTION: Route to Clio for research, then to Calliope for response drafting.
      - QUOTE_REQUEST: Route to Plutus for pricing, then to Calliope for response drafting.
      - FOLLOW_UP: Route to Mnemosyne to check history, then to appropriate agent.
      - SPAM: Log and archive.
   e. DRAFT RESPONSE: Get the response from the routing step and create a Gmail draft (not send — human review first).
   f. LOG: Record the interaction in the CRM.
   g. NOTIFY: Send a Telegram notification to the admin with a summary.
   h. Return a processing summary dict.

4. Have an async method poll_inbox(interval_seconds: int = 300) that continuously polls for new emails.

5. Have an async method send_email(to: str, subject: str, body: str, thread_id: str = None) that sends an email via Gmail API, optionally as a reply in a thread.
```

### Step 6.2: Telegram Bot

**Cursor Prompt:**
```
Create src/ira/interfaces/telegram_bot.py.

Implement a TelegramBot class using the python-telegram-bot library (v20+ with async). It should:

1. Initialize with the bot token from config, the Pantheon, SensorySystem, VoiceSystem, and CRMDatabase.

2. Command handlers:
   - /start: Welcome message explaining Ira's capabilities.
   - /help: List all available commands.
   - /ask <query>: Route a question to Athena and return the response.
   - /inbox: Show a summary of recent emails processed.
   - /pipeline: Show the current sales pipeline summary (delegate to Prometheus).
   - /team: Show the list of all agents and their roles.
   - /vitals: Show system health (delegate to ImmuneSystem).
   - /board <topic>: Run a board meeting on the given topic.
   - /dream: Trigger a manual dream cycle and show the report.
   - /campaign <name>: Show the status of a specific drip campaign.
   - /clear: Clear the current conversation context.

3. Message handler (for plain text messages):
   a. Create a PerceptionEvent and pass it through the SensorySystem.
   b. Route the enriched perception to Athena.
   c. Shape the response through the VoiceSystem (channel=TELEGRAM).
   d. Send the response back to the user.
   e. Show typing indicators while processing.

4. Document handler: Accept uploaded documents (PDF, XLSX, etc.) and pass them to the DigestiveSystem for ingestion.

5. Admin notifications: Have a method send_admin_notification(message: str) that sends a message to the admin chat ID.

6. Inline keyboard support for interactive elements (e.g., "Approve this draft?" with Yes/No buttons).
```

### Step 6.3: CLI Interface

**Cursor Prompt:**
```
Create src/ira/interfaces/cli.py.

Implement a CLI using the typer library with the following commands:

1. ira chat: Start an interactive chat session with Ira. Use rich library for formatted output. Show which agents are being consulted in real-time.

2. ira ask "<query>": Send a single query and print the response.

3. ira server: Start the FastAPI server with all background services.

4. ira ingest [path]: Run the document ingestion pipeline on a specific path or the default data/imports directory.

5. ira dream: Trigger a manual dream cycle and print the report.

6. ira board "<topic>": Run a board meeting and print the minutes.

7. ira pipeline: Print the current sales pipeline summary.

8. ira health: Run the immune system health check and print results.

9. ira agents: List all agents with their roles and status.

Use rich.console for formatted output, rich.table for tabular data, and rich.progress for progress bars during long operations.
```

### Step 6.4: FastAPI Server (The Glue)

**Cursor Prompt:**
```
Create src/ira/interfaces/server.py.

Implement a FastAPI application that is the main entry point for the entire Ira system. It should:

1. STARTUP EVENT (on_startup):
   a. Load configuration.
   b. Initialize all services (EmbeddingService, QdrantManager, KnowledgeGraph, etc.).
   c. Initialize the Pantheon (all agents).
   d. Initialize all body systems (Digestive, Respiratory, Immune, Endocrine, Musculoskeletal, Sensory, Voice).
   e. Initialize all memory systems (Conversation, LongTerm, Episodic, Procedural, Metacognition, Emotional, InnerVoice, Relationship, Goal, Dream).
   f. Initialize the CRM, QuoteManager, and DripEngine.
   g. Run the ImmuneSystem startup validation.
   h. Start the RespiratorySystem background tasks.
   i. Start the EmailProcessor polling.
   j. Start the TelegramBot.
   k. Log "Ira is awake" with a summary of all initialized components.

2. SHUTDOWN EVENT (on_shutdown):
   a. Stop the RespiratorySystem.
   b. Stop the EmailProcessor.
   c. Stop the TelegramBot.
   d. Close all database connections.
   e. Log "Ira is going to sleep."

3. API ENDPOINTS:
   - POST /api/query: Accept a query and optional context, route to Athena, return the response.
   - GET /api/health: Return the ImmuneSystem health check.
   - GET /api/pipeline: Return the CRM pipeline summary.
   - GET /api/agents: Return the list of all agents.
   - POST /api/ingest: Accept a file upload and pass it to the DigestiveSystem.
   - POST /api/board-meeting: Accept a topic and run a board meeting.
   - GET /api/dream-report: Return the latest dream report.

4. MIDDLEWARE:
   - Add a global exception handler that logs errors through the ImmuneSystem.
   - Add a request timing middleware that uses the RespiratorySystem's breath timing.
   - Add CORS middleware for potential future web dashboard.

Use lifespan context manager for startup/shutdown. Use dependency injection for shared services.
```

### Step 6.5: The Master Pipeline — Putting It All Together

**Cursor Prompt:**
```
Create src/ira/pipeline.py.

This is the master request processing pipeline that every incoming message goes through, regardless of channel. Implement an async function process_request(raw_input: str, channel: str, sender_id: str, metadata: dict = None) -> str that:

1. PERCEIVE: Pass through the SensorySystem to get unified perception (resolved identity, emotional state, history).

2. REMEMBER: Query ConversationMemory for recent history. Query RelationshipMemory for relationship context. Check GoalManager for active goals.

3. ROUTE (Fast Path): Try the DeterministicRouter first. If it matches, use the pre-defined routing.

4. ROUTE (Smart Path): If the DeterministicRouter doesn't match, check ProceduralMemory for a known procedure. If found, follow it.

5. ROUTE (LLM Path): If neither fast path nor procedure matches, delegate to Athena for LLM-based routing.

6. EXECUTE: The routed agent(s) execute the task, using their tools and the Brain for retrieval.

7. ASSESS: Pass the result through Metacognition to assess confidence and generate appropriate caveats.

8. REFLECT: Pass the result through the InnerVoice for potential reflection surfacing.

9. SHAPE: Pass through the VoiceSystem to format for the channel and recipient.

10. LEARN: Record the interaction in ConversationMemory, CRM (via Mnemosyne), and MusculoskeletalSystem. Trigger Sophia (Reflector) for post-interaction analysis.

11. RETURN: Return the final shaped response.

This pipeline is the single most important function in the system. Every message, from every channel, flows through it.
```

### Step 6.6: Tests and Commit

**Cursor Prompt:**
```
Create tests/test_interfaces.py with pytest-asyncio tests for:

1. EmailProcessor: Test process_email with a sample new lead email. Mock Gmail API and agents.
2. TelegramBot: Test that a text message is routed through the pipeline. Mock the bot API.
3. CLI: Test that `ira ask "test"` produces output.
4. Server: Test the /api/query endpoint. Test the /api/health endpoint.
5. Pipeline: Test process_request end-to-end with mocked services. Verify that all 11 steps are executed in order.
```

**Terminal Command:**
```bash
poetry run pytest tests/test_interfaces.py -v
git add . && git commit -m "Phase 6: Interfaces complete — Email, Telegram, CLI, API Server, Master Pipeline"
```

**Phase 6 Outcome:** Ira is now fully operational. She can be reached via Telegram, email, CLI, or API. Every message flows through the master pipeline, engaging the full power of the Brain, Pantheon, Body, and Mind.

---

## Phase 7: The Skills — Skills Matrix and Learning Feedback Loops

**Goal:** Implement the full skills matrix (24 skills) and the real-time and overnight learning feedback loops that allow Ira to continuously improve from user feedback.

**Estimated Time:** 2-3 hours.

### Step 7.1: Skills Framework

**Cursor Prompt:**
```
Create src/ira/skills/__init__.py and src/ira/skills/registry.py.

Implement a SkillRegistry class that manages all of Ira's skills. A skill is a higher-level capability that may involve multiple agents and tools working together. It should:

1. Define a Skill model: name (str), description (str), required_agents (list[str]), required_tools (list[str]), handler (Callable).

2. Have a method register_skill(skill: Skill) that adds a skill to the registry.

3. Have a method find_skill(query: str) -> Skill or None that uses keyword matching and semantic similarity to find the most relevant skill for a query.

4. Have a method execute_skill(skill_name: str, context: dict) -> str that runs the skill's handler.

5. Register all 24 skills from the original design:
   - answer_query: Core query answering (Clio + Retriever)
   - discover_knowledge: Knowledge exploration (Clio + KnowledgeGraph)
   - research_competitor: Competitor analysis (Iris + web search)
   - suggest_followup: Follow-up suggestions for stale leads (Prometheus + SalesIntelligence)
   - fact_checking: Fact verification (Vera + Retriever)
   - feedback_handler: Process user corrections (Nemesis + LongTermMemory)
   - store_memory: Store facts in Mem0 (Mnemosyne + LongTermMemory)
   - proactive_outreach: Automated lead follow-ups (Hermes + DripEngine)
   - reflection: Post-interaction reflection (Sophia + EpisodicMemory)
   - identify_user: Cross-channel identity resolution (SensorySystem)
   - generate_quote: PDF quote generation (Plutus + PricingEngine)
   - research: Deep multi-source research (Clio + Retriever + KnowledgeGraph)
   - check_health: System health check (ImmuneSystem)
   - run_dream_mode: Nightly consolidation (DreamMode)
   - deep_research: Extended research with web (Clio + Iris)
   - recall_memory: Memory retrieval (Mnemosyne + LongTermMemory)
   - detect_emotion: Emotional state detection (EmotionalIntelligence)
   - assess_confidence: Confidence calibration (Metacognition)
   - writing: Professional writing (Calliope)
   - draft_email: Email drafting (Calliope + VoiceSystem)
   - run_reflection: Auto post-interaction analysis (Sophia)
   - board_meeting: Run a board meeting (BoardMeeting)
   - campaign_management: Manage drip campaigns (Hermes + DripEngine)
   - machine_recommendation: Machine recommendation (Hephaestus + MachineIntelligence)

Skills are invoked by Athena when she recognizes that a query maps to a known skill, providing a more structured execution path than ad-hoc delegation.
```

### Step 7.2: Real-Time Learning Loop

**Cursor Prompt:**
```
Create src/ira/skills/learning.py.

Implement a LearningHub class that coordinates all real-time learning. It should:

1. REAL-TIME OBSERVER:
   - Have an async method observe_interaction(query: str, response: str, context: dict) that:
     a. Extracts facts, preferences, and patterns from the interaction.
     b. Stores new facts in LongTermMemory.
     c. Updates the contact's relationship in RelationshipMemory.
     d. Feeds the interaction to the MusculoskeletalSystem for action tracking.

2. CORRECTION HANDLER:
   - Have an async method handle_correction(original: str, corrected: str, context: str) that:
     a. Stores the correction in LongTermMemory with high priority.
     b. Updates any affected knowledge in Qdrant (if the correction contradicts stored data).
     c. Delegates to Nemesis for adversarial testing (does the correction break anything?).
     d. Adjusts the InnerVoice personality traits if the correction implies a style preference.

3. FEEDBACK HANDLER:
   - Have an async method handle_feedback(feedback_type: str, content: str, context: dict) that:
     a. Processes explicit feedback ("good answer", "wrong", "too long", etc.).
     b. Updates the EndocrineSystem (positive feedback → boost confidence, negative → reduce).
     c. Stores the feedback for DreamMode analysis.

4. PREDICTION LOGGER:
   - Have an async method log_prediction(prediction: str, actual: str, context: dict) that tracks prediction accuracy over time (e.g., lead qualification predictions vs actual outcomes).
```

### Step 7.3: Cursor Commands

**Cursor Prompt:**
```
Create the following Cursor command files in .cursor/commands/:

1. add_agent.md:
   "Create a new agent in src/ira/agents/. Follow the pattern in base_agent.py. The agent must have a name, role (system prompt), and tools. Register it in pantheon.py and add a delegation tool for Athena."

2. add_tool.md:
   "Add a new tool to an existing agent. Define the tool in OpenAI function calling format. Implement the handler function. Register it in the agent's tool registry."

3. add_skill.md:
   "Register a new skill in src/ira/skills/registry.py. Define the skill name, description, required agents, required tools, and handler function."

4. run_tests.md:
   "Run all tests with pytest: poetry run pytest -v. Fix any failures before proceeding."

5. run_dream.md:
   "Trigger a manual dream cycle by running scripts/run_dream.py. Review the DreamReport output."

6. deploy.md:
   "Build the Docker image and deploy: docker-compose build && docker-compose up -d. Verify health at /api/health."
```

### Step 7.4: Tests and Commit

**Cursor Prompt:**
```
Create tests for the skills and learning systems:

1. Test SkillRegistry: Verify that find_skill correctly matches queries to skills.
2. Test LearningHub: Test handle_correction stores the correction and triggers adversarial testing.
3. Test handle_feedback updates the EndocrineSystem.
```

**Terminal Command:**
```bash
poetry run pytest -v
git add . && git commit -m "Phase 7: Skills complete — 24 skills, real-time learning, Cursor commands"
```

**Phase 7 Outcome:** Ira now has a complete skills matrix and learning infrastructure. She learns from every interaction in real-time, processes corrections immediately, and has structured skill execution paths for common tasks.

---

## Phase 8: Deployment, Documentation, and Handover

**Goal:** Package the application for production deployment, write comprehensive documentation, and prepare the project for ongoing development and tuning.

**Estimated Time:** 2-3 hours.

### Step 8.1: Dockerfile and Docker Compose

**Cursor Prompt:**
```
Create a production Dockerfile for the Ira application:

1. Use python:3.12-slim as the base image.
2. Install Poetry in the build stage.
3. Copy pyproject.toml and poetry.lock, install dependencies (no dev deps).
4. Copy the src/ directory.
5. Expose port 8000.
6. CMD: uvicorn src.ira.interfaces.server:app --host 0.0.0.0 --port 8000

Update docker-compose.yml to add the ira service that builds from this Dockerfile, depends on qdrant, neo4j, and postgres, and mounts the data/ directory as a volume. Add environment variable passthrough from .env.
```

### Step 8.2: Data Migration Script

**Cursor Prompt:**
```
Create scripts/migrate_from_v1.py.

This script should migrate data from the old Ira v1 codebase to the new v3 system:

1. Read the old ira_crm.db SQLite database and import contacts, deals, and interactions into the new PostgreSQL CRM.
2. Read the old quotes.db and import quotes into the new QuoteManager.
3. Read the old employees.db and import HR data.
4. Copy the data/imports/ directory structure.
5. Re-run the document ingestion pipeline on all imported documents.
6. Print a migration summary with counts of imported records.

Handle schema differences gracefully. Log any records that couldn't be migrated.
```

### Step 8.3: Comprehensive README

**Cursor Prompt:**
```
Create a comprehensive README.md for the project with the following sections:

1. THE IRA DREAM: A brief, inspiring introduction to what Ira is and why she exists.
2. ARCHITECTURE OVERVIEW: High-level description of the four domains (Brain, Pantheon, Body, Mind) with a Mermaid diagram.
3. THE AGENT PANTHEON: Table of all 16 agents with their names, roles, and key tools.
4. THE BODY SYSTEMS: Table of all 7 biological systems with descriptions.
5. THE MEMORY ARCHITECTURE: Table of all 10 memory modules with descriptions.
6. GETTING STARTED:
   a. Prerequisites (Python 3.12, Poetry, Docker).
   b. Installation steps.
   c. Configuration (.env setup).
   d. Starting services (docker-compose up).
   e. Running Ira (ira server, ira chat, ira telegram).
7. USAGE GUIDE: How to interact with Ira via Telegram, Email, and CLI.
8. DEVELOPMENT GUIDE: How to add new agents, tools, and skills.
9. DEPLOYMENT: Docker deployment instructions.
10. THE SKILLS MATRIX: Table of all 24 skills.
```

### Step 8.4: Architecture Documentation

**Cursor Prompt:**
```
Create docs/ARCHITECTURE.md with detailed technical documentation:

1. System architecture diagram (Mermaid).
2. Data flow diagrams for key pipelines:
   a. Email ingestion pipeline.
   b. Query processing pipeline.
   c. Drip campaign pipeline.
   d. Dream mode pipeline.
3. Database schema diagrams.
4. Agent interaction patterns.
5. API reference for all endpoints.
```

### Step 8.5: Contributing Guide

**Cursor Prompt:**
```
Create CONTRIBUTING.md with:

1. Development workflow (branch, develop, test, PR).
2. How to add a new agent (step-by-step).
3. How to add a new tool to an existing agent.
4. How to add a new skill.
5. How to add a new body system.
6. Testing guidelines.
7. Code style guide (reference the Cursor rules).
```

### Step 8.6: Final Validation

**Terminal Commands:**
```bash
# Run all tests
poetry run pytest -v

# Run linting
poetry run ruff check .

# Run type checking
poetry run mypy src/ira/

# Build Docker image
docker-compose build

# Start everything
docker-compose up -d

# Run health check
curl http://localhost:8000/api/health

# Tag the release
git add .
git commit -m "Phase 8: Deployment and documentation complete"
git tag -a v3.0.0 -m "Ira v3.0.0: The Complete Dream"
```

**Phase 8 Outcome:** Ira v3 is fully deployed, documented, and ready for production use. The project is set up for ongoing development with clear contribution guidelines and Cursor rules.

---

## Appendix A: Complete Module Inventory

This is the definitive list of every file in the Ira v3 project, organized by domain. Every module from the original dream is accounted for.

### Brain (9 modules)

| File | Purpose | Phase |
|:---|:---|:---|
| `src/ira/brain/embeddings.py` | Voyage AI embedding generation with batching and caching | 1 |
| `src/ira/brain/qdrant_manager.py` | Qdrant vector store CRUD and hybrid search | 1 |
| `src/ira/brain/document_ingestor.py` | Multi-format document ingestion (PDF, XLSX, DOCX, TXT, CSV) | 1 |
| `src/ira/brain/knowledge_graph.py` | Neo4j entity and relationship management | 1 |
| `src/ira/brain/retriever.py` | Unified hybrid search with FlashRank reranking | 1 |
| `src/ira/brain/machine_intelligence.py` | Machine catalog, specs, recommendations, comparisons | 1 |
| `src/ira/brain/pricing_engine.py` | Historical pricing analysis and quote estimation | 1 |
| `src/ira/brain/sales_intelligence.py` | Lead qualification, customer health, stale lead detection | 1 |
| `src/ira/brain/deterministic_router.py` | Fast keyword-based intent classification and routing | 1 |

### Agents (17 modules)

| File | Agent Name | Role | Phase |
|:---|:---|:---|:---|
| `src/ira/agents/base_agent.py` | BaseAgent | Foundation class with agentic tool-calling loop | 2 |
| `src/ira/agents/athena.py` | Athena | CEO / Orchestrator — delegates to all agents | 2 |
| `src/ira/agents/clio.py` | Clio | Research Director — knowledge retrieval and synthesis | 2 |
| `src/ira/agents/prometheus.py` | Prometheus | CRO — sales pipeline, lead management, deal tracking | 2 |
| `src/ira/agents/plutus.py` | Plutus | CFO — finance, pricing, quotes, revenue analysis | 2 |
| `src/ira/agents/hermes.py` | Hermes | CMO — marketing, drip campaigns, outreach | 2 |
| `src/ira/agents/hephaestus.py` | Hephaestus | CPO — production, machines, inventory, purchasing | 2 |
| `src/ira/agents/themis.py` | Themis | CHRO — HR, employees, skills matrix, policies | 2 |
| `src/ira/agents/calliope.py` | Calliope | Head of Communications — writing, emails, content | 2 |
| `src/ira/agents/tyche.py` | Tyche | Pipeline Forecaster — revenue forecasting, deal velocity | 2 |
| `src/ira/agents/delphi.py` | Delphi | Email Oracle — email classification and routing | 2 |
| `src/ira/agents/sphinx.py` | Sphinx | Gatekeeper — clarification and disambiguation | 2 |
| `src/ira/agents/vera.py` | Vera | Fact Checker — cross-source verification | 2 |
| `src/ira/agents/sophia.py` | Sophia | Reflector — post-interaction analysis and learning | 2 |
| `src/ira/agents/iris.py` | Iris | External Intelligence — web search, news, social | 2 |
| `src/ira/agents/mnemosyne.py` | Mnemosyne | Memory Keeper — CRM custodian, contact history | 2 |
| `src/ira/agents/nemesis.py` | Nemesis | Trainer — corrections, adversarial testing, stress tests | 2 |

### Body Systems (7 modules)

| File | System | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/systems/digestive.py` | Digestive | Data ingestion with nutrient extraction (protein/carbs/waste) | 3 |
| `src/ira/systems/respiratory.py` | Respiratory | Operational cadence (heartbeat, inhale/exhale cycles) | 3 |
| `src/ira/systems/immune.py` | Immune | Health monitoring, error tracking, self-healing, alerts | 3 |
| `src/ira/systems/endocrine.py` | Endocrine | Adaptive behavior through hormone-like state variables | 3 |
| `src/ira/systems/musculoskeletal.py` | Musculoskeletal | Action tracking and learning signal extraction (myokines) | 3 |
| `src/ira/systems/sensory.py` | Sensory | Cross-channel perception and identity resolution | 3 |
| `src/ira/systems/voice.py` | Voice | Response shaping by channel, recipient, and behavioral state | 3 |

### Mind / Memory (10 modules)

| File | Module | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/memory/conversation.py` | Conversation | Short-term per-user conversation history | 4 |
| `src/ira/memory/long_term.py` | Long-Term | Mem0-backed persistent semantic memory | 4 |
| `src/ira/memory/episodic.py` | Episodic | Narrative episode consolidation from conversations | 4 |
| `src/ira/memory/procedural.py` | Procedural | Learned response procedures for recurring query types | 4 |
| `src/ira/memory/metacognition.py` | Meta-Cognition | Self-awareness of knowledge state and confidence | 4 |
| `src/ira/memory/emotional_intelligence.py` | Emotional Intelligence | Emotion detection and response adjustment | 4 |
| `src/ira/memory/inner_voice.py` | Inner Voice | Personality traits, internal reflections, evolving character | 4 |
| `src/ira/memory/relationship.py` | Relationship | Warmth tracking and relationship progression | 4 |
| `src/ira/memory/goal_manager.py` | Goal Manager | Goal-oriented dialogue tracking with slot filling | 4 |
| `src/ira/memory/dream_mode.py` | Dream Mode | Nightly consolidation, gap detection, creative synthesis | 4 |

### Business (3 modules)

| File | Module | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/data/crm.py` | CRM Database | PostgreSQL CRM with contacts, deals, interactions | 5 |
| `src/ira/data/quotes.py` | Quote Manager | Full quote lifecycle management | 5 |
| `src/ira/systems/drip_engine.py` | Drip Engine | Autonomous multi-step email outreach campaigns | 5 |

### Infrastructure (6 modules)

| File | Module | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/config.py` | Configuration | Pydantic-based environment variable management | 0 |
| `src/ira/data/models.py` | Data Models | Pydantic transfer objects used across the system | 0 |
| `src/ira/message_bus.py` | Message Bus | Async pub/sub for inter-agent communication | 2 |
| `src/ira/pantheon.py` | Pantheon | Agent registry and initialization | 2 |
| `src/ira/systems/board_meeting.py` | Board Meeting | Multi-agent collaborative discussion | 2 |
| `src/ira/pipeline.py` | Master Pipeline | 11-step request processing pipeline | 6 |

### Interfaces (4 modules)

| File | Interface | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/interfaces/email_processor.py` | Email | Gmail inbox monitoring, classification, draft generation | 6 |
| `src/ira/interfaces/telegram_bot.py` | Telegram | Interactive bot with commands and admin notifications | 6 |
| `src/ira/interfaces/cli.py` | CLI | Command-line interface with rich formatting | 6 |
| `src/ira/interfaces/server.py` | API Server | FastAPI server tying everything together | 6 |

### Skills & Learning (2 modules)

| File | Module | Purpose | Phase |
|:---|:---|:---|:---|
| `src/ira/skills/registry.py` | Skill Registry | 24 registered skills with handlers | 7 |
| `src/ira/skills/learning.py` | Learning Hub | Real-time observer, correction handler, feedback handler | 7 |

**Total: 58 Python modules** (down from 549 in v1, but with ALL functionality preserved and properly organized).

---

## Appendix B: Cursor Rules Summary

These files go in `.cursor/rules/` and guide Cursor's AI agent during development.

### `00_core_architecture.mdc`
- Use Poetry for dependency management.
- All code must be async (async/await throughout).
- Use Pydantic for all data models.
- Use SQLAlchemy 2.0 async for database access.
- Use structlog for all logging.
- Every file must have a module-level docstring.
- Follow SOLID principles.
- Never use `sys.path` manipulation.
- Never hardcode API keys or file paths.

### `01_pantheon_rules.mdc`
- All agents inherit from BaseAgent.
- Agents communicate ONLY through the MessageBus.
- Athena is the only agent that receives user queries directly.
- Each agent has a focused set of tools (max 6 per agent).
- Agent system prompts must define personality, expertise, and decision-making style.
- New agents must be registered in pantheon.py.

### `02_brain_rules.mdc`
- All knowledge retrieval goes through UnifiedRetriever.
- No agent should query Qdrant or Neo4j directly.
- Document ingestion always goes through the DigestiveSystem.
- Embeddings are always generated through EmbeddingService.
- The DeterministicRouter is checked before LLM routing.

### `03_memory_rules.mdc`
- Short-term memory: ConversationMemory (per-user, per-channel).
- Long-term memory: Mem0 (semantic, persistent).
- Episodic memory: Consolidated from conversations nightly.
- Procedural memory: Learned from successful interaction patterns.
- All memory writes must include source attribution.

### `04_testing_rules.mdc`
- Every module must have corresponding tests.
- Use pytest-asyncio for async tests.
- Mock external services (OpenAI, Voyage, Gmail, etc.).
- Use in-memory SQLite for database tests.
- Tests must pass before committing.

---

## Appendix C: Tuning and Training Guide

After the initial build, Ira needs to be tuned and trained with your feedback. Here is how to do it within Cursor.

### Day 1-7: Initial Training

1. **Document Ingestion**: Run `ira ingest` to process all documents in `data/imports/`. Monitor the output for errors.

2. **Knowledge Verification**: Ask Ira questions about known facts and verify the answers. Use corrections to train:
   ```
   You: What is the lead time for PF1-C?
   Ira: Based on available information, approximately 12-16 weeks.
   You: That's wrong. The lead time for PF1-C is 16-20 weeks.
   ```
   The correction handler will store this and Ira will learn.

3. **CRM Population**: Import your existing contacts and deals. Use the migration script or manually add via the CLI.

4. **Personality Tuning**: Give feedback on Ira's communication style:
   ```
   You: That response was too formal. Be more casual with me.
   ```
   The InnerVoice will adjust personality traits.

### Week 2-4: Active Use

1. **Email Processing**: Let Ira process your inbox. Review the drafts she creates. Approve good ones, correct bad ones.

2. **Drip Campaigns**: Set up your first campaign targeting European leads. Monitor reply rates.

3. **Board Meetings**: Run weekly board meetings on key topics. Review the minutes for quality.

4. **Dream Mode**: Let the nightly dream cycles run. Review the DreamReports for insights and knowledge gaps.

### Ongoing: Continuous Improvement

1. **Correction Loop**: Every correction you make improves Ira. Be specific: "The price for AM-200 in Europe is EUR 45,000, not USD 40,000."

2. **Feedback Loop**: Rate responses: "Good answer", "Too long", "Missing context about X".

3. **Skill Refinement**: If Ira consistently handles a type of query well, the ProceduralMemory will learn the pattern and optimize future responses.

4. **Agent Tuning**: If a specific agent (e.g., Hermes) isn't performing well, you can adjust its system prompt in Cursor:
   ```
   @Agent Update the system prompt for Hermes in src/ira/agents/hermes.py. Make him more data-driven and less flowery in his marketing copy.
   ```

5. **New Knowledge**: Drop new documents into `data/imports/` and run `ira ingest`. The DigestiveSystem will process them.

---

## Appendix D: OpenClaw Decision

Based on the audit, the recommendation is to **NOT use OpenClaw** for Ira v3. Here is why:

1. **Custom Pipeline Requirement**: Ira needs custom control over every step of the request processing pipeline — from email ingestion through nutrient extraction, multi-agent routing, confidence assessment, voice shaping, and learning. OpenClaw's pipeline is too rigid for this.

2. **Agent Communication**: Ira's agents need to communicate through a custom MessageBus with full trace logging and board meeting capabilities. OpenClaw's agent communication model doesn't support this.

3. **Biological Systems**: The Digestive, Respiratory, Immune, and other biological systems are unique to Ira and have no equivalent in OpenClaw.

4. **Memory Architecture**: Ira's 10-layer memory system (Conversation, Long-Term, Episodic, Procedural, Meta-Cognition, Emotional, Inner Voice, Relationship, Goal, Dream) is far more sophisticated than what OpenClaw provides.

5. **Simplicity**: Building on raw OpenAI API + Python gives you full control and understanding. No framework abstractions to fight against.

The only thing OpenClaw provided was the basic agent loop (call LLM → execute tools → repeat). This is trivially implemented in the BaseAgent class (Step 2.2) in about 80 lines of code.

---

## Appendix E: Cost and Token Optimization

To avoid repeating the $5,000 token spend from v1 development:

1. **Use Plan Mode in Cursor**: Always use `Shift+Tab` to enter Plan Mode for complex steps. Review the plan before approving execution. This prevents Cursor from generating unnecessary code.

2. **One Module at a Time**: Each Cursor conversation should focus on ONE module. Don't try to build multiple modules in one conversation.

3. **Reference Existing Code**: When building a new module, tell Cursor to reference existing modules for patterns: `@Agent Create src/ira/agents/plutus.py following the same pattern as src/ira/agents/prometheus.py`.

4. **Use the Cursor Rules**: The `.cursor/rules/` files prevent Cursor from generating code that violates the architecture. This reduces rework.

5. **Test Frequently**: Run tests after every module. Catching bugs early is cheaper than fixing them later.

6. **Use GPT-4.1-mini for Simple Tasks**: For straightforward modules (data models, CRUD operations), use a smaller model in Cursor to save tokens. Reserve GPT-4.1 or Claude for complex agent logic.

---

## Summary: The Full Dream, Built Right

This plan preserves **every single architectural concept** from the original Ira vision:

| Original Concept | Status in v3 | Phase |
|:---|:---|:---|
| Agent Pantheon (16 agents) | Preserved — all agents with proper BaseAgent inheritance | 2 |
| Agent-to-Agent Communication | Preserved — async MessageBus with trace logging | 2 |
| Board Meetings | Preserved — multi-agent collaborative discussions | 2 |
| RAG Pipeline (Qdrant + Voyage) | Preserved — hybrid search with FlashRank reranking | 1 |
| Knowledge Graph (Neo4j) | Preserved — entity extraction and relationship queries | 1 |
| Document Ingestion (22 categories) | Preserved — multi-format ingestion with deduplication | 1 |
| Digestive System (Nutrient Extraction) | Preserved — protein/carbs/waste classification | 3 |
| Respiratory System (Daily Rhythm) | Preserved — heartbeat, inhale/exhale cycles | 3 |
| Immune System (Self-Healing) | Preserved — health checks, error tracking, alerts | 3 |
| Endocrine System (Adaptive Behavior) | Preserved — hormone-based behavioral modifiers | 3 |
| Musculoskeletal System (Action Learning) | Preserved — myokine extraction from outcomes | 3 |
| Sensory System (Cross-Channel) | Preserved — unified perception and identity resolution | 3 |
| Voice System (Response Shaping) | Preserved — channel-aware, relationship-aware formatting | 3 |
| Inner Voice (Personality) | Preserved — evolving traits and surfaced reflections | 4 |
| Dream Mode (Nightly Consolidation) | Preserved — 5-stage dream cycle with creative synthesis | 4 |
| Meta-Cognition (Self-Awareness) | Preserved — knowledge state assessment and confidence | 4 |
| Emotional Intelligence | Preserved — emotion detection and response adjustment | 4 |
| Episodic Memory | Preserved — narrative consolidation from conversations | 4 |
| Procedural Memory | Preserved — learned response procedures | 4 |
| Relationship Memory | Preserved — warmth progression tracking | 4 |
| Goal Manager | Preserved — slot-filling goal-oriented dialogues | 4 |
| CRM (PostgreSQL) | Preserved — contacts, deals, interactions, pipeline | 5 |
| Quote Lifecycle | Preserved — draft through follow-up to close | 5 |
| Autonomous Drip Engine | Preserved — multi-step personalized email campaigns | 5 |
| Telegram Bot | Preserved — full command set with admin notifications | 6 |
| Email Processing (ira@machinecraft.org) | Preserved — classify, route, draft, notify | 6 |
| CLI Interface | Preserved — chat, ask, server, ingest, dream, board | 6 |
| Skills Matrix (24 skills) | Preserved — all skills registered with handlers | 7 |
| Real-Time Learning | Preserved — observer, correction handler, feedback handler | 7 |
| Machine Intelligence | Preserved — catalog, specs, recommendations, comparisons | 1 |
| Pricing Engine | Preserved — historical analysis and estimation | 1 |
| Sales Intelligence | Preserved — qualification, health scoring, stale detection | 1 |
| Deterministic Router | Preserved — fast-path keyword routing | 1 |

**The dream is intact. Every module. Every agent. Every system. No shortcuts. No cut corners.**

The difference from v1: it is now **organized into 58 clean modules** instead of 549 tangled files, with **proper dependency injection** instead of 186 `sys.path` hacks, with **real tests** instead of zero, and with **clear Cursor rules** that prevent architectural drift.

This is the plan. Open Cursor. Start at Phase 0. Build the dream.
