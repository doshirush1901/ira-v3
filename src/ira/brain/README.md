# `brain/` — Knowledge & Retrieval

32 modules that handle everything Ira "knows" — from document ingestion
to entity extraction to guardrails.

## Core Retrieval

| Module | Purpose |
|:-------|:--------|
| `retriever.py` | `UnifiedRetriever` — single entry point for all knowledge retrieval |
| `qdrant_manager.py` | Qdrant vector DB operations (upsert, search, delete) |
| `embeddings.py` | `EmbeddingService` — Voyage AI embeddings via httpx |
| `knowledge_graph.py` | Neo4j knowledge graph queries and entity linking |
| `imports_fallback_retriever.py` | Alexandros-style raw file search when KB is empty |
| `imports_metadata_index.py` | Metadata index for all files in `data/imports/` |

## Document Processing

| Module | Purpose |
|:-------|:--------|
| `document_ingestor.py` | Main ingestion pipeline (docling + chonkie chunking) |
| `ingestion_gatekeeper.py` | Dedup and validation before ingestion |
| `ingestion_log.py` | Track what has been ingested |
| `quality_filter.py` | Filter noise, keep high-value "protein" content |

## Routing & Fast Paths

| Module | Purpose |
|:-------|:--------|
| `deterministic_router.py` | Keyword → agent routing (entity-aware) |
| `fast_path.py` | Short-circuit common queries with cached answers |
| `truth_hints.py` | Hard-coded business facts (lead times, specs, etc.) |

## Intelligence & Learning

| Module | Purpose |
|:-------|:--------|
| `entity_extractor.py` | GLiNER-based NER for contacts, companies, machines |
| `pricing_engine.py` | Pricing estimation from configuration |
| `pricing_learner.py` | Learn pricing patterns from historical quotes |
| `sales_intelligence.py` | Lead scoring, inquiry qualification |
| `knowledge_discovery.py` | Novel connection discovery |
| `knowledge_health.py` | Qdrant collection health checks |
| `graph_consolidation.py` | Merge duplicate entities in Neo4j |

## Safety & Correction

| Module | Purpose |
|:-------|:--------|
| `guardrails.py` | Input validation + output safety checks |
| `correction_store.py` | Persistent correction ledger |
| `correction_learner.py` | Apply corrections to future responses |
| `adaptive_style.py` | Per-user communication style tracking |
| `power_levels.py` | Agent energy/confidence levels |

## Monitoring

| Module | Purpose |
|:-------|:--------|
| `error_monitor.py` | Track failure patterns |
| `realtime_observer.py` | Extract learnings from every conversation turn |
| `sleep_trainer.py` | Overnight training from corrections |
