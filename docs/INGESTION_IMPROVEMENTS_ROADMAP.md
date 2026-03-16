# Ingestion & Retrieval Improvements Roadmap

Tracked work from [INGESTION_STATE_OF_THE_ART.md](INGESTION_STATE_OF_THE_ART.md). Status: **Done** | **In progress** | **Planned** | **Deferred**.

---

## 1. Chunking & context

| Item | Status | Notes |
|------|--------|------|
| **Parent–child chunks** | **Done** | Digestive stores `parent_summary` (first sentence) + `window` in metadata; retriever prepends parent to content. |
| **Sentence-window retrieval** | **Done** | Payload field `window` (same as content for now); ready for future core+window expansion. |
| **Chunk size by doc_type** | **Done** | `get_chunk_params_for_doc_type()`; gatekeeper passes doc_type to digestive; quote/contract 256/64, manual/report 512/128. |

---

## 2. Dense + sparse (real hybrid)

| Item | Status | Notes |
|------|--------|------|
| **Sparse vectors in Qdrant** | **Done** | `ira.brain.sparse_vectors`: token-hash sparse per chunk; Qdrant collection has named vectors `dense` + `sparse`. Set `APP__USE_SPARSE_HYBRID=true`, `QDRANT__COLLECTION_HYBRID`; re-ingest to populate. |
| **RRF at query time** | **Done** | `qdrant_manager.hybrid_search`: when hybrid, prefetch sparse + dense, `FusionQuery(fusion=RRF)`; `search()` uses `using="dense"` on hybrid collection. |
| **Keyword path + RRF** | **Done** | `_apply_keyword_boost()`: keyword overlap score blended before rerank so exact-match candidates rank higher. |

---

## 3. Retrieval behavior

| Item | Status | Notes |
|------|--------|------|
| **Over-retrieve then rerank** | **Done** | Qdrant fetches `limit * 3`; reranker gets `limit * 2` candidates. See `_OVER_RETRIEVE_FACTOR`, `_RERANK_CANDIDATES_FACTOR` in `retriever.py`. |
| **MMR / diversity after rerank** | **Done** | `_diversify_results()` drops items with word-overlap > 55% to already-selected chunks. No extra embedding calls. |

---

## 4. Parsing & OCR

| Item | Status | Notes |
|------|--------|------|
| **Docling first for PDF** | **Done** | PDF reader order: Docling → Unstructured → pypdf + Document AI. See `_get_reader()` in `document_ingestor.py`. |
| **Figure/caption text** | Deferred | When Docling/Unstructured expose figures/captions, append "Figure N: &lt;caption&gt;". Parser-dependent. |
| **Re-OCR only when text low** | **Done** | `reingest_scanned_pdfs(min_chars_per_page=25)`; skip OCR when text per page ≥ threshold. API: `min_chars_per_page`. |

---

## 5. Evaluation

| Item | Status | Notes |
|------|--------|------|
| **Retrieval eval set** | **Done** | `scripts/retrieval_eval.py` + `data/brain/retrieval_eval_queries.json`; Hit@1/5/10, MRR, P@5. |
| **Chunk/ingestion metrics** | **Done** | Each ingest cycle appends one line to `data/brain/ingestion_metrics.jsonl`. |

---

## 6. Dedup & entities

| Item | Status | Notes |
|------|--------|------|
| **Cross-file semantic dedup** | **Done** | `scripts/dedup_ingestion_chunks.py`: group by content hash, report duplicate groups (no delete). |
| **Canonical entities in Neo4j** | **Done** | Already MERGE + `normalize_entity_name` in knowledge_graph. |

---

## 7. Safety & compliance

| Item | Status | Notes |
|------|--------|------|
| **PII detection at ingest** | **Done** | `ira.brain.pii_redact`; set `APP__REDACT_PII_AT_INGEST=true` to redact email/phone in chunks. |
| **Delete by source/category** | **Done** | `QdrantManager.delete_by_source`, `delete_by_source_category`. |

---

## Summary

- **Done:** Over-retrieve + rerank, diversity (MMR-like), Docling-first for PDF, chunk size by doc_type, parent–child + window, retrieval eval set, ingestion metrics, keyword boost, re-OCR when text low, dedup script, canonical entities (existing MERGE), PII redaction, delete by source/category, **dense+sparse hybrid** (sparse in Qdrant + RRF at query time).
- **Remaining:** Figure/caption from parser (deferred until Docling/Unstructured expose it).
