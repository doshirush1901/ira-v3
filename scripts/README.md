# `scripts/` — Operational & Training Scripts

Utility scripts for data backfill, benchmarking, training, and
infrastructure management.

## Scripts

| Script | Purpose |
|:-------|:--------|
| `pull_contact_email_history.py` | **Before drafting to any CRM/lead:** pull all past convos from mailbox, build interaction logic tree (timeline, proposals sent, their feedback), optionally `--store-memory`. Ira API required. |
| `draft_lead_email_enriched.py` | Draft lead email with full context: `GET /api/memory/recall` + optional contact history MD, then `POST /api/email/draft` with format/voice instructions. Use after pull_contact_email_history. |
| `check_lead_contact_history.py` | Check CRM + optional Gmail for prior contact (when we last wrote, did they reply). Use `--lead-id` or `--email`. |
| `backfill_relationships.py` | Backfill relationship memory from historical data |
| `benchmark.py` | Benchmark pipeline latency and retrieval quality |
| `crm_gmail_sync.py` | Sync CRM contacts with Gmail contacts |
| `enrich_graph.py` | Enrich Neo4j knowledge graph with extracted entities |
| `nap.py` | Trigger a quick dream-mode nap (subset of full dream) |
| `shadow_training.py` | Shadow training — run queries without affecting state |
| `generate_v4_asset_manifest.py` | Build file-level v4 migration manifest for new assets |
| `v4_readiness_gate.py` | Validate v4 migration gates (manifest, quarantine, governance) |
| `agent_audit.py` | Audit agent metadata, prompt coverage, and registry consistency |
| `neo4j_schema_v1.cypher` | Neo4j schema constraints/indexes for Ira graph v1 |
| `seed_neo4j_from_ingestion_log.py` | Seed `Document`/`Fact`/`Correction` lineage graph from local stores |
| `shakti_train.sh` | Fine-tuning workflow shell script |
| `entrypoint.sh` | Docker container entrypoint |
| `start-local.sh` | **Start Ira (local):** DBs only — Postgres, Qdrant, Neo4j, Redis. Run from repo root; works on any machine. |
| `start.sh` | Start Ira (production: infrastructure + server via docker-compose.prod.yml) |
| `stop.sh` | Stop Ira (production stack) |

For **local development**, run `./scripts/start-local.sh` from the repo root (or `docker compose -f docker-compose.local.yml up -d`), then use `ira ask`, `ira task`, or `ira chat` — no API server required. See root [README](../README.md) and [GETTING_STARTED](../docs/GETTING_STARTED.md).

## Usage

Most scripts are run via Poetry:

```bash
poetry run python scripts/benchmark.py
poetry run python scripts/enrich_graph.py
poetry run python scripts/seed_neo4j_from_ingestion_log.py --dry-run
```

Shell scripts are executable directly:

```bash
./scripts/start-local.sh   # local dev: DBs only
./scripts/start.sh
./scripts/stop.sh
```
