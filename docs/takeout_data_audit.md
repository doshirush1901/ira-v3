# Takeout Data — Complete Audit and Review

**Generated:** 2026-03-13  
**Sources:** `data/takeout_ingest/`, `data/brain/takeout_ingest_*.json`, CLI `ira takeout`, `src/ira/interfaces/cli.py`

---

## 1. Executive Summary

| Item | Value |
|------|--------|
| **Source location** | `data/takeout_ingest/` |
| **Source size** | ~7.3 GB (41 × `.mbox` files) |
| **Active checkpoint** | `data/brain/takeout_ingest_batch-takeout.json` |
| **Profile** | `machinecraft_protein_strict` |
| **Last checkpoint update** | 2026-03-12T23:09:07Z |

**Ingestion outcome (from checkpoint):**

- **Messages processed (full pipeline):** 15,458  
- **Messages with protein (stored):** 14,063  
- **Chunks created (Qdrant):** 24,532  
- **Mem0 facts written:** 45,770  
- **Done keys (dedup):** 15,898  
- **Entities extracted:** companies 12,972; people 13,616; machines 5,726; relationships 21,571  

**Qdrant live count:** Not verified in this audit (Qdrant was unavailable / timeout). Run `poetry run ira takeout verify` with Docker up to confirm `source_category=takeout_email_protein` point count.

---

## 2. Connection settings and verification

Ingested takeout data lives in three backends. Config comes from `.env` (see `.env.example`). Defaults match `docker-compose.local.yml` where applicable.

| Service | Config (env prefix) | Default / example | Purpose |
|--------|----------------------|-------------------|---------|
| **Qdrant** | `QDRANT_` | `QDRANT_URL=http://localhost:6333`, `QDRANT_COLLECTION=ira_knowledge_v3`, `QDRANT_API_KEY=` (optional) | Vector store for chunk embeddings; takeout chunks have `source_category=takeout_email_protein`. |
| **Neo4j** | `NEO4J_` | `NEO4J_URI=bolt://localhost:7687`, `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=ira_knowledge_graph` (or `NEO4J_AUTH=neo4j/ira_knowledge_graph`) | Knowledge graph: companies, people, machines, relationships extracted from protein. |
| **Mem0** | `MEM0_` | `MEM0_API_KEY=` (required for Mem0). App also uses `mem0_timeout` (default 15s) in `AppConfig`. | Persistent memory: facts from takeout are stored via `LongTermMemory.store_fact()` against Mem0 cloud (`https://api.mem0.ai`). |

**Are they OK?**

- **Quick connectivity:** With the API server running, `GET /api/deep-health` checks core (Qdrant, Neo4j, PostgreSQL, OpenAI, Voyage, Langfuse) and Mem0 (if `MEM0_API_KEY` is set). All should report `healthy` or `ok`.
- **Qdrant takeout count:** `poetry run ira takeout verify` — prints number of points with `source_category=takeout_email_protein`. Requires Qdrant up; on large collections the count can timeout (increase timeout or run when idle).
- **Neo4j:** Same deep-health check; for local Docker use `NEO4J_PASSWORD=ira_knowledge_graph` as in `docker-compose.local.yml`.
- **Mem0:** If `MEM0_API_KEY` is empty, takeout ingest still runs but no facts are written to Mem0; CLI/server log “Mem0 API key not configured” or skip Mem0 init. Deep-health pings `https://api.mem0.ai/v1/ping/` when the key is set.

**Summary:** Set `QDRANT_URL`, `NEO4J_URI`/`NEO4J_PASSWORD`, and `MEM0_API_KEY` in `.env`. Start stack with `docker compose -f docker-compose.local.yml up -d` for Qdrant/Neo4j. Then run deep-health and `ira takeout verify` to confirm.

---

## 3. What to do after a big ingest (audit and re-arrange)

After a large takeout ingest, Ira can “audit and re-arrange” the new data in several ways. All are optional but recommended.

1. **Run a dream cycle**  
   Dream mode consolidates memory, merges graph nodes, runs gap analysis, and writes a morning summary. It uses the same Qdrant and Neo4j that now hold the takeout data.  
   - **CLI:** `poetry run ira dream`  
   - **API:** `GET /api/dream-report` (or with `?journal_last_24h=true` to journal last 24h of agent activity).  
   - **Stages that touch the new data:** Stage 0 (deferred ingestion), Stage 0.5 (Nemesis sleep training on corrections), Stage 2 (episodic consolidation), Stage 7 & 8 (quality review + **graph consolidation** — merges/cleans Neo4j), Stage 10 (morning summary).  
   - Run once after ingest; can be repeated periodically.

2. **Journal only (lightweight)**  
   If you only want to “save” recent agent activity without a full dream:  
   - **CLI:** `poetry run ira journal` or `ira journal --last-24h`  
   - **API:** `GET /api/journal` or `GET /api/journal?last_24h=true`.  
   - Does not reprocess Qdrant/Neo4j/Mem0; just writes agent reflections.

3. **Knowledge health check**  
   Audits Qdrant (point count, collection status) and Neo4j (node counts, orphaned nodes) and runs domain rules (e.g. `KnowledgeHealthMonitor`).  
   - **API:** Only when the Immune system is wired: deep-health’s `core` check does startup validation; for a full knowledge report the server would need an endpoint that calls `immune.check_knowledge_health()`.  
   - **Code:** `src/ira/systems/immune.py` → `check_knowledge_health()`; `src/ira/brain/knowledge_health.py` for domain checks.  
   - If you expose a “knowledge health” endpoint, call it after ingest to see collection size and any chronic issues.

4. **Verify takeout counts**  
   - `poetry run ira takeout verify` — confirm Qdrant point count for `takeout_email_protein` matches expectations (~24.5k from current checkpoint).  
   - Mem0 has no per-source count API in this codebase; the checkpoint’s `mem0_written` (45,770) is the only local record of how many facts were sent.

5. **Re-run dream periodically**  
   Running `ira dream` on a schedule (e.g. nightly) keeps graph consolidation and gap detection in sync with new data. No one-off “reindex takeout” step is required; retrieval already uses the same collection.

**Practical order:** (1) Ensure Docker + `.env` are correct and run `ira takeout verify` and/or deep-health. (2) Run `ira dream` once to consolidate and clean the graph. (3) Optionally run a knowledge health check if available. (4) Use `ira journal` when you want to capture recent agent activity without a full dream.

---

## 4. Source Data Inventory

### 4.1 Mbox files (41 total)

All files under `data/takeout_ingest/*.mbox`:

- **Client threads:** Machinecraft - Clients-ANP, Donite, DutchTides, Jaguar, L&K India, Mayur, NRC Canada, Nilkamal, Otter, Pinnacle, Proflex Canada, Saraswati, Soehner, Stas Russia, Thermic, Venkateshwara Hyderabad  
- **Sales inquiry:** Machinecraft Sales Inquiry-Dizet, EZG Netherlands, Gerwin Pelle Netherland, IHT Canada, Matt IHT Canada, Soehner, Thermic Energy  
- **Other:** FCS Houtai Press China, Events-Expos, France Market Dev, FRIMO-FIS 5TO Press, FRIMO-FRIMO Sales Leads, FRIMO-IAC, FVF Sales, GS Engineering, Materials, Machinecraft Machine Design-Illig UA 100g Dev, NL 2022, NPE2024, Press Lamination Dev, Remi PP Canada, RFQ Sales, Russian RFQs, Thermoforming Study, Thermoforming Study-Thermoforming Study  

Largest mboxes by line count (from `wc -l`) include `Russian RFQs.mbox` (~3M lines) and `Remi PP Canada.mbox` (~100k lines); exact message counts per file are not computed here (expensive for 7.3 GB).

### 4.2 Checkpoint and progress files

| File | Purpose |
|------|--------|
| `data/brain/takeout_ingest_batch-takeout.json` | Main checkpoint: `done_keys`, `stats`, `batch_name`, `updated_at`. ~1.1 MB. |
| `data/brain/takeout_ingest_progress.txt` | One-line progress (seen, processed, protein, chunks, mem0, noise, low_signal, updated). May lag checkpoint. |
| `data/brain/takeout_ingest_run.log` | Run log (progress lines, debug). |
| `data/brain/takeout_ingest_takeout-1-mail.json` | Older/smaller batch checkpoint (e.g. single-mail run). |
| `data/brain/takeout_mem0_backfill_batch_001.json` | Mem0 backfill batch state (separate from main ingest). |

---

## 5. Pipeline Review

### 5.1 Command and options

- **Ingest:** `poetry run ira takeout ingest`  
  - Options: `--source-dir`, `--batch-name`, `--profile`, `--max-messages`, `--dry-run`, `--verify-after`, `--cleanup-after`, `--notify-email`, `--concurrency`, `--verbose`.  
  - Default source: `data/takeout_ingest`; default batch: `batch_takeout` → checkpoint `takeout_ingest_batch-takeout.json`.  
  - Resumes from checkpoint automatically (skips messages whose key is in `done_keys`).

### 5.2 Flow (high level)

1. **Enumerate** `.mbox` under `source_dir`, sort.  
2. **For each message:** compute stable key (Message-ID or fallback); skip if key in checkpoint.  
3. **Extract body** (`_extract_message_body`): plain text from multipart or single payload.  
4. **Noise filter** (`_is_noise_message`): drop if sender has noreply/no-reply/etc.; subject has unsubscribe/newsletter/digest/promotion/sale; Precedence bulk/list; Auto-Submitted ≠ no; List-Unsubscribe set.  
5. **Protein signal filter** (`_has_machinecraft_protein_signal`): keep only if (sender + subject + body) contains any of: rfq, request for quote, quote, quotation, po, purchase order, inquiry, lead time, delivery, dispatch, pricing, price, machine, thermoform, vacuum form, tooling, spec, machinecraft, client, customer, payment terms, invoice.  
6. **Prepare body** (`_prepare_body_for_classification`): strip NUL, drop lines >1200 chars, cap 12k chars.  
7. **Digestive pipeline (per message):**  
   - `_extract_nutrients` (LLM protein/carbs/waste) → `_summarize_nutrients` → keep only protein statements.  
   - If no protein, skip storage.  
   - If protein: `_absorb` (chunks → Qdrant, `source_category="takeout_email_protein"`), entity extraction (Neo4j), up to 8 facts to Mem0 via `LongTermMemory.store_fact`.  
8. **Checkpoint** after each batch of concurrent tasks; progress file updated on same cadence.

### 5.3 Fallback on nutrient failure

If nutrient extraction fails (e.g. LLM error, circuit breaker), the code falls back to absorbing the raw body as a single protein chunk and stores one Mem0 fact (confidence 0.7). This avoids losing the message when the classifier fails.

### 5.4 Markup / token fixes (recent)

- Digestive skips LLM for windows that are mostly HTML/CSS/Office markup (`_is_mostly_markup`).  
- Nutrient prompt caps protein/carbs at 30 items each, waste at 10 with summary placeholders for long junk.  
- `NutrientClassification` schema truncates lists after parse (protein/carbs 30, waste 15).  
These reduce circuit-breaker and max_tokens issues during takeout ingest.

---

## 6. Data Quality and Completeness

### 6.1 What is stored

- **Qdrant:** Chunk embeddings with metadata `source_category="takeout_email_protein"`, `source` (mbox path + index), `source_id` (first 24 chars of message key).  
- **Neo4j:** Companies, people, machines, relationships extracted from protein text.  
- **Mem0:** Facts from protein statements (up to 8 per message), `source` and confidence (e.g. 0.85).  

### 6.2 What is not stored

- Messages skipped as **noise** (noreply, newsletters, etc.).  
- Messages skipped as **low_signal** (no Machinecraft protein keyword).  
- **Carbs** and **waste** from the nutrient model (only protein is absorbed).  
- Original raw bodies in the KB (only summarized/absorbed protein chunks).  

### 6.3 Completeness vs source

- Checkpoint **messages_seen** in the last run reflected in `takeout_ingest_progress.txt` was 150 (a short run). The **authoritative** totals are in the checkpoint: **15,458 processed**, **15,898 done_keys**.  
- Total message count across all 41 mboxes was **not** computed in this audit (large volume). To know “how many messages remain,” run ingest with `--dry-run` and `--max-messages 0` on a copy of the data, or add a script that iterates mboxes and counts messages without processing.  
- **Gaps:** Any mbox or message order change after the checkpoint will not re-process already-seen keys; new messages (new Message-IDs) will be processed on next run.

---

## 7. Verification and Operations

### 7.1 Commands

- **Verify Qdrant:** `poetry run ira takeout verify` → prints count of points with `source_category=takeout_email_protein`. Requires Qdrant (e.g. Docker) up; can timeout on large collections.  
- **Optimise (audit + backfill):** `poetry run ira takeout optimise` → ensures takeout data is in the **right place** (collection `ira_knowledge_v3`) and **right way** (payload has `content`, `source`, `source_category`, `metadata`). Optionally backfills `doc_type=takeout_email_protein` so retriever filters that match on `doc_type` also find takeout chunks. Use `--no-backfill-doc-type` for audit-only.  
- **Cleanup source:** `poetry run ira takeout cleanup [--source-dir ...]` → deletes contents of takeout folder (e.g. after ingest to free space).  
- **Notification when done:** `scripts/takeout_notify_when_done.py [--pid PID] [--to EMAIL]` — waits for process and/or sends report from checkpoint + `ira takeout verify`.

**Where takeout data lives:** Same Qdrant collection as the rest of the KB (`QDRANT_COLLECTION`, default `ira_knowledge_v3`). Points are distinguished by `source_category=takeout_email_protein` (and optionally `doc_type` after optimise). Neo4j holds extracted entities; Mem0 holds facts. No separate “takeout collection”.

### 7.2 Resume and re-run

- Same `--source-dir` and `--batch-name` → resume from existing checkpoint.  
- To **re-ingest from scratch:** delete or rename `data/brain/takeout_ingest_batch-takeout.json` (and optionally progress file), then run ingest again.  
- **Different batch:** use `--batch-name other` → new checkpoint `takeout_ingest_other.json`, no conflict with `batch_takeout`.

### 7.3 Related assets

- **Mem0 backfill:** `scripts/takeout_mem0_backfill.py` — backfills from staged takeout batches (e.g. `data/imports/takeout_batches/`), separate from the main mbox ingest.  
- **Asset manifest:** `docs/v4/asset_decision_manifest.csv` lists `data/takeout_ingest/takeout_ingest.py` (path may be historical) as data_governance/review, lifecycle policy medium, pending.

---

## 8. Recommendations

1. **Verify Qdrant when possible:** Run `ira takeout verify` with Docker up to confirm point count matches expectations (e.g. ~24.5k chunks from current stats).  
2. **Estimate remaining work:** Add a small script or `--dry-run` mode that reports total messages in mboxes and how many keys are already in checkpoint, to estimate remaining messages.  
3. **Progress file vs checkpoint:** Progress file can lag; treat checkpoint JSON as source of truth for stats and done_keys.  
4. **Retention:** If takeout data is deleted after ingest (`--cleanup-after` or manual), keep checkpoint and logs if you need to know what was ingested without re-reading mboxes.

---

## 9. Reference: Key Code and Config

- **CLI takeout commands:** `src/ira/interfaces/cli.py` (`takeout_app`, `takeout_ingest`, `takeout_verify`, `takeout_optimise`, `takeout_cleanup`).  
- **Helpers:** `_extract_message_body`, `_is_noise_message`, `_has_machinecraft_protein_signal`, `_prepare_body_for_classification` in same file.  
- **Digestive:** `src/ira/systems/digestive.py` (nutrient extraction, summarization, absorb); `src/ira/brain/document_ingestor.py` (chunking, Qdrant).  
- **Checkpoint path:** `data/brain/takeout_ingest_{batch_name_slug}.json`.
