# Ira v3 Architecture

## Overview

Ira is a multi-agent AI system built for Machinecraft. It processes user
requests through an 11-stage pipeline, delegates work to a pantheon of 24
specialist agents, and maintains persistent memory across conversations.

```
User Input (CLI / API / Email)
    │
    ▼
┌───────────────────┐
│  RequestPipeline  │  11 linear stages
└───────────────────┘
    │
    ▼
┌───────────────────┐
│    Pantheon        │  Orchestrator + 24 agents (ReAct loops)
└───────────────────┘
    │         │         │
    ▼         ▼         ▼
┌────────┐ ┌────────┐ ┌────────────┐
│  Brain │ │ Memory │ │ Body       │
│        │ │        │ │ Systems    │
└────────┘ └────────┘ └────────────┘
    │         │         │
    ▼         ▼         ▼
 Qdrant    SQLite     Redis (cache/streams)
 Neo4j     Mem0       Gmail (email tools)
           PostgreSQL  Google Docs / Doc AI / DLP / PDF.co
```

## Pipeline (`src/ira/pipeline.py`)

Every inbound message flows through `RequestPipeline.process_request`.
The pipeline is intentionally linear so each step can be individually
logged, timed, and tested.

| Stage | System | Purpose |
|:------|:-------|:--------|
| 1. PERCEIVE | SensorySystem | Resolve contact identity, emotional state, metadata |
| 2. REMEMBER | ConversationMemory, RelationshipMemory, GoalManager | Fetch history, relationship warmth, active goals, coreference resolution |
| 3. ROUTE (Fast) | DeterministicRouter | Keyword-matched intent to agent names |
| 3.5 TRUTH HINTS | TruthHintsEngine | Short-circuit with cached factual answer |
| 4. ROUTE (Procedure) | ProceduralMemory | Match learned response patterns |
| 5. ROUTE (LLM) | Athena | Open-ended LLM-based routing |
| 5.5 ENRICH | Multiple | Adaptive style, realtime learnings, endocrine state, power levels |
| 6. EXECUTE | Routed agent(s) | Run selected agents; synthesise multi-agent responses |
| 7. ASSESS | Metacognition | Confidence scoring, knowledge gap detection |
| 8. REFLECT | InnerVoice | Optional self-reflection |
| 9. SHAPE | VoiceSystem | Format for channel, recipient, behavioural modifiers |
| 10. LEARN | Multiple | Record to ConversationMemory, CRM, GoalManager, ProceduralMemory |
| 11. RETURN | -- | Final shaped response |

## Agent Architecture (`src/ira/agents/`)

### BaseAgent

All 24 agents inherit from `BaseAgent` (~870 lines), which provides:

- **Shared identity** -- `SOUL.md` preamble (Identity, Voice, Behavioral
  Boundaries) is prepended to every agent's system prompt via
  `prompt_loader.load_soul_preamble()`.
- **ReAct loop** via `self.run()` -- up to `max_iterations` (default 8)
  iterations of Reason-Act-Observe. Each iteration calls the LLM, parses
  a tool selection from the response, executes the tool, appends the
  observation to a scratchpad, and repeats until the LLM emits a
  `final_answer`.
- **Default tools** registered lazily based on available services:
  `search_knowledge`, `recall_memory`, `store_memory`,
  `get_conversation_history`, `check_relationship`, `check_goals`,
  `recall_episodes`, `ask_agent`, `search_emails`, `read_email_thread`.
- **Dual LLM support** -- OpenAI and Anthropic via `LLMClient`
  (`src/ira/services/llm_client.py`), with Langfuse tracing and automatic
  Anthropic fallback on OpenAI failure.
- **Knowledge retriever** -- `self._retriever` (UnifiedRetriever) for
  Qdrant + Neo4j + Mem0 search.
- **Email tools** -- when the email processor is injected, all agents
  gain `search_emails` and `read_email_thread` for Gmail access.

### The Pantheon

`Pantheon` (`src/ira/pantheon.py`) initialises all agents, the message
bus, and brain services. It routes queries through the deterministic
router (fast path) or Athena (LLM path) and supports board-meeting mode
where multiple agents collaborate.

Services are injected into agents via `pantheon.inject_services()`,
which calls `agent.inject_services()` on each agent. This enables the
ReAct tools that depend on memory, CRM, and other shared services.

### Agent Roster

| Agent | Role | Custom Tools |
|:------|:-----|:-------------|
| Athena | Orchestrator | delegate_to_agent, convene_board_meeting, get_system_health |
| Alexandros | Librarian | search_archive, browse_folder, read_file, get_archive_stats |
| Arachne | Content Scheduler | search_linkedin_data, draft_newsletter |
| Asclepius | Quality | log_punch_item, get_punch_list, quality_dashboard |
| Atlas | Project Manager | get_project_status, log_project_event, get_overdue_milestones |
| Cadmus | CMO / Case Studies | find_case_studies, build_case_study, draft_linkedin_post |
| Calliope | Writing | draft_proposal, polish_text, translate_text |
| Chiron | Sales Trainer | log_pattern, get_coaching_notes, get_sales_guidance |
| Clio | Research | search_qdrant, ask_alexandros, ask_iris, verify_with_vera |
| Delphi | Oracle | classify_email, classify_contact, run_shadow_sim |
| Hephaestus | Production | lookup_machine_spec, estimate_production_time, search_manuals |
| Hera | Vendor/Procurement | check_vendor_status, get_component_lead_time, classify_component |
| Hermes | Marketing | search_market_research, draft_email, create_drip_sequence |
| Iris | External Intelligence | web_search, fetch_news, search_internal_knowledge |
| Mnemosyne | Memory | recall_long_term, store_long_term, get_episodic_memory |
| Nemesis | Trainer | ingest_correction, run_training, create_adversarial_scenario |
| Plutus | Finance | estimate_price, get_quote, search_financial_docs |
| Prometheus | Sales | search_contacts, get_deal, get_pipeline_summary |
| Quotebuilder | Quote Builder | lookup_machine_specs, calculate_pricing, generate_quote_document; auto-creates CRM deals |
| Sophia | Reflector | get_correction_history, suggest_improvement |
| Sphinx | Gatekeeper | analyze_query, suggest_clarifications |
| Themis | HR | lookup_employee, search_hr_policies, generate_org_chart |
| Tyche | Forecasting | get_pipeline_data, get_revenue_data |
| Vera | Fact Checker | search_qdrant, ask_iris, structured fact-check with KB cross-referencing |

## Memory Systems (`src/ira/memory/`)

| System | Backing Store | Purpose |
|:-------|:-------------|:--------|
| ConversationMemory | SQLite | Per-user, per-channel message history; coreference resolution |
| LongTermMemory | Mem0 REST API | Persistent semantic memory (facts, insights) |
| EpisodicMemory | SQLite + Mem0 | Narrative summaries of significant interactions |
| RelationshipMemory | SQLite | Contact warmth levels, memorable moments, learned preferences |
| GoalManager | SQLite | Slot-filling goal tracking per contact |
| ProceduralMemory | SQLite | Learned response patterns from past interactions |
| EmotionalIntelligence | SQLite | Emotion detection and tracking |
| InnerVoice | -- | Post-response self-reflection |
| Metacognition | -- | Confidence scoring and knowledge gap logging |

## Brain Services (`src/ira/brain/`)

| Service | Purpose |
|:--------|:--------|
| UnifiedRetriever | Qdrant + Neo4j + Mem0 hybrid search with query decomposition and reranking (Voyage Rerank primary, FlashRank fallback) |
| QdrantManager | Vector store management (CRUD, chunking, embedding) |
| KnowledgeGraph | Neo4j entity/relationship CRUD and graph queries |
| EmbeddingService | Voyage AI embeddings via raw HTTP |
| EntityExtractor | GLiNER-based zero-shot NER for contacts, companies, and machines |
| Guardrails | Input validation and output safety checks (guardrails-ai) |
| DeterministicRouter | Entity-aware keyword-to-agent intent matching |
| PricingEngine | Machine price estimation from knowledge base |
| SalesIntelligence | Lead qualification, customer health, re-engagement |
| MachineIntelligence | Machine comparison and recommendation |
| DocumentIngestor | PDF/DOCX/Excel ingestion via docling + chonkie chunking; re-OCR via Document AI for scanned PDFs |
| AdaptiveStyleTracker | Per-contact communication style profiling with async-safe updates |
| PowerLevelTracker | Agent performance scoring (success/failure/training boosts) |
| TruthHints | Cached factual answers for common queries |

## Body Systems (`src/ira/systems/`)

Ira uses a biological metaphor for its subsystems. Core body systems
handle the request lifecycle; extended systems provide integrations and
operational capabilities.

### Core Body Systems

| System | Purpose |
|:-------|:--------|
| Sensory | Perception -- contact resolution, emotion detection, channel detection |
| Digestive | Document ingestion -- breaks documents into knowledge nutrients |
| Circulatory | Cross-system data synchronization, heartbeat scheduling |
| Immune | Input validation, hallucination detection, safety filters |
| Respiratory | Background health checks and system monitoring |
| Voice | Response shaping for channel and recipient |

### Extended Systems

| System | Purpose |
|:-------|:--------|
| Redis Cache | Response dedup, message stream persistence, fast key-value caching |
| Document AI | OCR for scanned PDFs, invoice/form parsing via Google Document AI |
| DLP | PII redaction and sensitive-data scanning via Google Cloud DLP |
| Google Docs | Read, write, and export Google Docs (case studies, reports) |
| PDF.co | HTML-to-PDF generation and text extraction for quotes and exports |
| Learning Hub | Feedback processing, knowledge gap analysis, procedure suggestion |
| Board Meeting | Multi-agent collaborative discussions on a topic |
| Drip Engine | Automated multi-step email campaigns |
| Data Event Bus | Typed event system for cross-store synchronization |
| CRM Enricher | Multi-agent CRM enrichment pipeline |
| CRM Populator | Contact classification and import from Gmail, KB, Neo4j |

Endocrine (behavioral modifiers) and Musculoskeletal (action recording)
are wired into the pipeline as lightweight service-key integrations.

## Infrastructure Dependencies

| Service | Image | Purpose |
|:--------|:------|:--------|
| Qdrant | `qdrant/qdrant:latest` | Vector database for document embeddings |
| Neo4j | `neo4j:5.15.0-community` | Knowledge graph (entities, relationships) |
| PostgreSQL | `postgres:16` | CRM relational data (companies, contacts, deals, quotes) |
| Redis | `redis:7-alpine` | Response dedup, message stream persistence, caching |

Local development: `docker-compose.local.yml`
Production: `docker-compose.yml` (with health checks, resource limits, restart policies)

Database migrations are managed by Alembic (`alembic/`) targeting the
PostgreSQL CRM schema.

## Interfaces (`src/ira/interfaces/`)

| Interface | Purpose |
|:----------|:--------|
| `server.py` | FastAPI REST API (primary production interface) |
| `cli.py` | Interactive CLI and single-query mode via Typer + Rich |
| `email_processor.py` | Gmail inbox processing, email search, thread reading, draft sending |
| `dashboard.py` | Web dashboard (HTML, served at `/dashboard/`) |

## Data Flow

1. User sends a message via CLI, email, or the FastAPI server.
2. The interface layer constructs a `RequestPipeline` and calls
   `process_request()`.
3. The pipeline runs 11 stages, delegating to the Pantheon at the
   EXECUTE stage.
4. The Pantheon routes to one or more agents. Each agent runs a ReAct
   loop, using its custom tools and the default memory/KB/email tools.
5. The pipeline shapes the response for the output channel and records
   the interaction in memory and CRM.
6. Redis caches the response for dedup; the MessageBus persists events
   to Redis Streams for cross-system observability.
