# Deep ingestion: workflow, strategy, and LLM usage

This doc confirms **how** we ingest data from `data/imports/`, **what the workflow is**, **strategy**, and **how we use the LLM**. Use it when planning deep ingestion of folders (e.g. everything except 01 and 02, which may be running in other tabs).

---

## 1. High-level workflow

Ingestion is **two phases** that work together:

| Phase | Command | What it does |
|-------|---------|--------------|
| **A. Metadata index** | `ira index-imports [--force] [--include-prefix FOLDER]` | Scan files in imports; for each file, extract a text preview and call the **LLM** to produce structured metadata (summary, doc_type, entities, keywords). Persist to `data/brain/imports_metadata.json`. Powers Alexandros hybrid search and the gatekeeper. |
| **B. Digestive ingestion** | `ira ingest [--force] [--include-prefix FOLDER] [--exclude-prefix FOLDER]` | Gatekeeper compares the metadata index to the ingestion log; for each file that is new, changed, or from an older pipeline, **read full file → DigestiveSystem** (LLM steps below) → Qdrant + Neo4j + optional Mem0. Log written to `data/brain/ingestion_log.json`. |
| **C. Re-OCR scanned PDFs** | `ira reingest-scanned [--base-path PATH] [--min-size-mb N]` | Find large PDFs with little extractable text; run Document AI OCR; re-ingest those through the same DigestiveSystem. |

**Strategy:** Run **A** first so every file has rich metadata (and the gatekeeper knows what to ingest). Run **B** to actually digest files into Qdrant/Neo4j. Run **C** after a full ingest to improve coverage for image-based or scanned PDFs.

---

## 2. Where the LLM is used

### 2.1 Metadata index (Phase A) — `imports_metadata_index.py`

- **When:** During `ira index-imports` (with LLM enabled; use `--no-llm` to skip).
- **Input:** Filename + first ~2000 characters of text per file (from PDF/DOCX/XLSX/CSV/TXT/PPTX/etc.).
- **Model:** GPT-4.1-mini.
- **Output (structured):** `summary`, `doc_type`, `machines`, `topics`, `entities`, `keywords`, `intent_tags`, `counterparty_type`, `document_role`, `intent_confidence`.
- **Purpose:** Rich per-file metadata for Alexandros (hybrid search, filters) and for the ingestion gatekeeper (category, doc_type). No chunking or embedding here — only file-level metadata.

### 2.2 DigestiveSystem (Phase B) — `digestive.py`

Each file that the gatekeeper sends is run through the **full digestive pipeline**. The LLM is used in three places:

| Stage | Name | What the LLM does | Prompt (from `prompts/`) |
|-------|------|-------------------|--------------------------|
| **STOMACH** | Nutrient extraction | Classifies text into **protein** (high-value facts), **carbs** (supporting context), **waste** (boilerplate, junk). Long docs are split into overlapping windows; each window is classified. | `digestive_nutrient` |
| **DUODENUM** | Summarization | Rewrites raw protein + carbs items into **short, self-contained, searchable statements**. Improves embedding and retrieval quality. | `digestive_summarize` |
| **LIVER** | Entity extraction | From the protein text, extracts **companies, people, machines, relationships** and writes them into **Neo4j**. Chunks can be linked to these entities for better retrieval. | Knowledge graph uses its extraction prompt / GraphRAG when available. |

After that (no LLM):

- **SMALL INTESTINE:** Chunk the summarized protein + carbs, embed with **Voyage**, upsert to **Qdrant**. Optional quality filter. Metadata includes `source`, `source_category`, `source_id`, and optionally `graph_entity_ids`.
- **Ingestion log:** Record path, hash, pipeline version (`digestive_v2`), chunks created, entities found.

So for **each ingested file**, we use the LLM for: (1) nutrient classification, (2) summarization into statements, (3) entity extraction into the graph.

### 2.3 Re-OCR (Phase C)

- **When:** `ira reingest-scanned`. No extra LLM for OCR itself (Document AI). The **new text** from OCR is then fed through the **same DigestiveSystem** as in Phase B (STOMACH → DUODENUM → LIVER → SMALL INTESTINE), so the same LLM steps apply to the newly extracted text.

---

## 3. Strategy summary

1. **Index first:** Ensure every file (or every file in scope) has LLM-generated metadata in the imports index. Use `--force` to refresh all, or `--include-prefix` to limit to specific folders.
2. **Ingest through the gatekeeper:** Only files that are new, changed, or from an older pipeline get digested. Use `--force` to re-ingest everything in scope; use `--exclude-prefix` / `--include-prefix` to scope to folders (e.g. exclude 01 and 02 if they are running elsewhere).
3. **Parallelism:** Ingestion runs multiple files concurrently (e.g. `--workers 5`). Each file’s LLM calls are independent, so more workers ≈ faster total time.
4. **Re-OCR last:** After a full ingest, run `ira reingest-scanned` to find large, text-poor PDFs, OCR them, and re-ingest that content through the same DigestiveSystem.

---

## 4. Planning ingestion for “all folders except 01 and 02”

Since 01 and 02 may be running in other tabs:

- **Index:** Either:
  - Run `ira index-imports --force` once (indexes everything; 01/02 entries are just updated if already indexed), or
  - Run `ira index-imports --force` with multiple `--include-prefix` for each of the other folders (03, 04, 05, …) so 01 and 02 are never touched.
- **Ingest:** Use **exclude** so only non-01/02 files are digested:
  ```bash
  poetry run ira ingest --force \
    --exclude-prefix 01_Quotes_and_Proposals \
    --exclude-prefix 02_Orders_and_POs \
    --workers 5
  ```
- **Re-OCR:** Same scope if you want to limit to non-01/02:
  ```bash
  poetry run ira reingest-scanned --base-path data/imports
  ```
  (Re-OCR does not take exclude-prefix; it scans under `--base-path`. To avoid re-OCR on 01/02 you could run it with a script that only passes certain subdirs, or run reingest-scanned once for the whole tree — re-ingestion is idempotent by path/hash.)

**Folder list (excluding 01 and 02):** 03_Product_Catalogues, 04_Machine_Manuals_and_Specs, 05_Presentations, 06_Market_Research_and_Analysis, 07_Leads_and_Contacts, 08_Sales_and_CRM, 09_Industry_Knowledge, 10_Company_Internal, 11_Project_Case_Studies, 13_Contracts_and_Legal, 14_Miscellaneous, 15_Production, 16_LINKEDIN DATA, 17_Vendors_Inventory, 18_Tally_Exports, 19_Business Plans, 20_Email Attachments, 21_WebCall Transcripts, 22_HR Data, 23_Asana, 24_WebSite_Leads, plus ad-hoc folders (Current Machine Orders, docs_from_telegram, downloaded_from_emails, ETD Conference Presentations, Machinecraft Finance, takeout_batches, etc.). Using `--exclude-prefix` for 01 and 02 covers all of these in one ingest run.

---

## 5. Quick reference

| Question | Answer |
|----------|--------|
| How do we ingest? | Index (LLM metadata per file) → Gatekeeper + DigestiveSystem (LLM: classify → summarize → entities; then chunk, embed, Qdrant + Neo4j) → optional re-OCR for big PDFs. |
| What is our strategy? | Index first; ingest only new/changed/legacy files; use exclude/include to scope; run re-OCR after full ingest. |
| How do we use the LLM? | (1) **Metadata index:** one LLM call per file for summary, doc_type, entities, keywords. (2) **Digestive:** per file, LLM for nutrient classification, then summarization, then entity extraction; rest is chunk/embed/upsert. |

For quote/order semantics and folder-specific notes, see [IMPORTS_QUOTE_SEMANTICS.md](IMPORTS_QUOTE_SEMANTICS.md).
