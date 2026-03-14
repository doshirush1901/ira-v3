# Neo4j: Making the graph dense and adding relationships

Your Neo4j is already on **Aura (cloud)** — no "sync to cloud" step. This doc is about **density** and **relationships**.

---

## Qdrant ↔ Neo4j linking (denser network)

Each ingested or backfilled chunk is explicitly linked to the graph:

- **Chunk nodes** — One Neo4j node per Qdrant point, with `qdrant_point_id`, `source`, `source_category`, `content_preview`.
- **DESCRIBES edges** — `(Chunk)-[:DESCRIBES]->(Company|Person|Machine|Quote)` so every chunk that mentions an entity is connected.
- **Qdrant payload** — Chunks store `graph_entity_ids` (e.g. `["Company:Acme", "Person:john@acme.com"]`) for retrieval-time expansion.

**At ingest:** Digestive system extracts entities, writes to Qdrant with `graph_entity_ids`, then creates a Chunk node and DESCRIBES edges for each upserted item.

**At backfill:** `ira graph backfill-from-qdrant` scrolls Qdrant (with `point_id`), extracts entities per chunk, writes entities and relationships, then calls `add_chunk_and_describes` so existing chunks get Chunk nodes and DESCRIBES edges.

**At retrieval:** Unified retriever stitches graph → vectors by (1) hybrid search on entity identifiers and (2) `get_chunk_point_ids_for_entity` → `get_points(ids)` so chunks that DESCRIBE the same entity are pulled in.

---

## Where relationships come from

| Source | What gets added |
|--------|------------------|
| **Ingest (takeout, documents)** | Person, Company, Machine nodes + relationships from LLM/GraphRAG extraction (`add_relationship`). **Chunk** nodes + **DESCRIBES** to each extracted entity; Qdrant payload gets `graph_entity_ids`. |
| **Backfill from Qdrant** | Same as above for existing chunks; each chunk gets a Chunk node and DESCRIBES edges. |
| **CRM / Circulatory** | Companies, deals; `INTERESTED_IN` between Company and Machine when deals have a machine model. |
| **Dream Stage 8 (graph consolidation)** | `CO_RELEVANT` edges between entities that appear **together in retrieval** (from `data/brain/retrieval_log.jsonl`). Pairs co-accessed ≥ 3 times get an edge. |

---

## How to make the cluster denser and add more relationships

### 1. Run graph consolidation (quick)

```bash
poetry run ira graph-consolidate
```

- Reads **retrieval log** (`data/brain/retrieval_log.jsonl`).
- Builds co-access pairs (which entities appeared in the same retrieval).
- Adds **CO_RELEVANT** between pairs that co-occur ≥ 3 times (and exist as labeled nodes).
- Marks **stale** nodes (not seen in the log) with `stale: true`.

**So:** More query traffic → more retrieval log entries → next `graph-consolidate` adds more edges. Run it periodically (e.g. after a few days of use) or after `ira dream`.

### 2. Run full dream (graph + memory + gaps)

```bash
poetry run ira dream
```

- Stage 8 is the same graph consolidation as above.
- Use this when you want memory consolidation, gap detection, and graph tuning in one go.

### 3. Backfill Neo4j from existing Qdrant chunks (sync Qdrant → Neo4j)

```bash
poetry run ira graph backfill-from-qdrant
```

- Scrolls all (or filtered) Qdrant chunks, runs entity/relationship extraction on each chunk's content, writes to Neo4j (same MERGE logic as ingest, idempotent).
- Options: `--max-chunks 1000` for a trial; `--source-category takeout_email_protein` for takeout only; `--batch-size 200`.
- **New ingestion** (takeout, docs, CRM) also creates **semantic** relationships at ingest time. The backfill above handles **existing** Qdrant content.

### 4. Ensure retrieval is logged


- Consolidation only sees what’s in the retrieval log. The retriever logs when it’s wired to `GraphConsolidation` (e.g. via dream/build). So running **queries** (CLI, API, or MCP) and then **graph-consolidate** or **dream** will gradually densify the graph.

---

## Summary

| Goal | Action |
|------|--------|
| Add edges from usage (co-retrieved entities) | `ira graph-consolidate` or `ira dream` |
| Add graph data from **existing** Qdrant chunks | `ira graph backfill-from-qdrant` |
| Add more semantic relationships from new text | More ingestion (takeout, docs, CRM) |
| Neo4j “in cloud” | Already on Aura; no extra sync step |

Run `ira graph backfill-from-qdrant` to sync Qdrant → Neo4j (use `--max-chunks 1000` for a trial). Run `ira graph-consolidate` to densify from the retrieval log; run `ira dream` for full consolidation.
