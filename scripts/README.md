# `scripts/` — Operational & Training Scripts

Utility scripts for data backfill, benchmarking, training, and
infrastructure management.

## Scripts

| Script | Purpose |
|:-------|:--------|
| `backfill_relationships.py` | Backfill relationship memory from historical data |
| `benchmark.py` | Benchmark pipeline latency and retrieval quality |
| `crm_gmail_sync.py` | Sync CRM contacts with Gmail contacts |
| `enrich_graph.py` | Enrich Neo4j knowledge graph with extracted entities |
| `nap.py` | Trigger a quick dream-mode nap (subset of full dream) |
| `shadow_training.py` | Shadow training — run queries without affecting state |
| `shakti_train.sh` | Fine-tuning workflow shell script |
| `entrypoint.sh` | Docker container entrypoint |
| `start.sh` | Start Ira (infrastructure + server) |
| `stop.sh` | Stop Ira (server + infrastructure) |

## Usage

Most scripts are run via Poetry:

```bash
poetry run python scripts/benchmark.py
poetry run python scripts/enrich_graph.py
```

Shell scripts are executable directly:

```bash
./scripts/start.sh
./scripts/stop.sh
```
