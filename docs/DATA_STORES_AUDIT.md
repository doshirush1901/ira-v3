# Ira data stores audit

**Run:** `poetry run python scripts/data_audit.py` from project root to refresh counts.

---

## 1. Where each “remembering” strategy stores data

| Store | Where it lives | Config (env) | What’s in it |
|--------|-----------------|--------------|----------------|
| **Qdrant** | Vector DB (local Docker or Qdrant Cloud per `QDRANT_URL`) | `QDRANT_URL`, `QDRANT_COLLECTION`, `QDRANT_API_KEY` | Chunk embeddings for KB + takeout; payload: `content`, `source`, `source_category`, `metadata`. Takeout chunks: `source_category=takeout_email_protein`. |
| **Neo4j** | Knowledge graph (local Docker or Neo4j Aura per `NEO4J_URI`) | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (or `NEO4J_AUTH`) | Companies, People, Machines, Quotes, relationships. Takeout ingest writes entities extracted from “protein” text. |
| **PostgreSQL** | Relational DB (local Docker per `DATABASE_URL`) | `DATABASE_URL` (default `postgresql+asyncpg://ira:ira@localhost:5432/ira_crm`) | CRM: contacts, companies, deals, interactions; quotes; vendors, vendor_payables. **Takeout does not write here.** |
| **Mem0** | Mem0 cloud (`https://api.mem0.ai`) | `MEM0_API_KEY` | Semantic long-term memory: facts and learned content. Takeout writes facts via `LongTermMemory.store_fact()` (no local copy). |
| **Redis** | Local Docker (optional cache) | `REDIS_URL` | Response dedup, message stream persistence, embedding cache. Ephemeral/cache, not primary memory. |
| **Local files** | `data/` on disk | — | Checkpoints, ingestion log, episodic/procedural JSON, SQLite (corrections, feedback, goals, etc.). See below. |

---

## 2. Where your Google Mail takeout data is stored

Takeout ingestion (`ira takeout ingest`) writes to **three** backends only:

| Backend | What’s written | Current status (from last audit run) |
|---------|----------------|--------------------------------------|
| **Qdrant** | Chunk embeddings with `source_category=takeout_email_protein` | **Local Qdrant:** 0 points (storage was reset; backup in `data/qdrant.bak.20260314092051` has the previous ~25k chunks). If `QDRANT_URL` points to Qdrant Cloud and dual-write was used at ingest time, cloud may have a copy. |
| **Neo4j** | Person, Company, Machine nodes and relationships from “protein” text | **Neo4j (Aura cloud in your setup):** 11,588 nodes (Machine 4,727, Company 4,113, Person 2,747, Quote 1). Takeout contributed to these. |
| **Mem0** | Facts from protein statements (`store_fact`) | **Mem0 cloud:** configured. Checkpoint reports **49,473** facts written from takeout (no per-store count API). |

Takeout does **not** write to: Postgres CRM, Redis, or local SQLite.

---

## 3. Last audit snapshot (from `scripts/data_audit.py`)

- **Qdrant:** `http://localhost:6333`, collection `ira_knowledge_v3` — **0** points total, **0** takeout points.
- **Neo4j:** `neo4j+s://...databases.neo4j.io` — **11,588** nodes (Machine, Company, Person, Quote).
- **Postgres:** `localhost:5432/ira_crm` — contacts **799**, companies **571**, deals **16**, interactions **1**, quotes **0**, vendors **0**.
- **Mem0:** API key set; no local count (checkpoint: **49,473** takeout facts).
- **Takeout checkpoint** (`data/brain/takeout_ingest_batch-takeout.json`): 19,745 messages processed, 18,340 with protein, **25,125** chunks created, **49,473** Mem0 facts, entities (companies 14,537, people 14,538, machines 6,062, relationships 23,194).

---

## 4. Local file storage (sizes)

| Path | Purpose |
|------|--------|
| `data/qdrant/` | Qdrant volume (current live DB). Empty/reset → use backup to restore. |
| `data/qdrant.bak.*/` | Backup of Qdrant storage (contains previous KB + takeout vectors). |
| `data/neo4j/` | Neo4j volume if using local Docker; not used when Neo4j URI is Aura. |
| `data/postgres/` | PostgreSQL volume (CRM, quotes, vendors). |
| `data/mem0_storage/` | Local episodic/procedural files (episodes, procedures); **not** Mem0 cloud data. |
| `data/brain/ingestion_log.json` | Log of file ingestions (imports, not takeout). |
| `data/brain/takeout_ingest_batch-takeout.json` | Takeout checkpoint: done_keys, stats (chunks_created, mem0_written, entities). |
| `data/brain/*.db` | SQLite: corrections, feedback, goals, agent_journals, atlas_logbook, etc. |

---

## 5. Summary

- **Takeout vector chunks (Qdrant):** Were in local Qdrant; that volume was replaced. Restore from `data/qdrant.bak.20260314092051` to get them back locally, or use Qdrant Cloud if dual-write was enabled at ingest.
- **Takeout entities (Neo4j):** In Neo4j (your setup: Aura cloud). **11,588** nodes.
- **Takeout facts (Mem0):** In Mem0 cloud. **49,473** facts per checkpoint.
- **CRM / pipeline (Postgres):** Contacts, companies, deals, etc. **Takeout does not write to Postgres.**

Run `poetry run python scripts/data_audit.py` anytime to refresh the numbers.
