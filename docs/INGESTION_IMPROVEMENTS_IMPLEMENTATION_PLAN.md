# Ingestion & Retrieval Improvements — Implementation Plan

Execute in order. Each item is self-contained; later items may build on earlier ones.

| # | Item | Status | Location / notes |
|---|------|--------|------------------|
| 1 | **Chunk size by doc_type** | **Done** | document_ingestor (`get_chunk_params_for_doc_type`), digestive (`_absorb`), gatekeeper (pass `doc_type`) |
| 2 | **Retrieval eval set** | **Done** | `scripts/retrieval_eval.py`, `data/brain/retrieval_eval_queries.json` |
| 3 | **Chunk/ingestion metrics** | **Done** | ingestion_gatekeeper appends to `data/brain/ingestion_metrics.jsonl` |
| 4 | **Parent–child chunks** | **Done** | digestive: `parent_summary` + `window` in metadata; retriever prepends parent to content |
| 5 | **Sentence-window** | **Done** | Payload field `window` (same as content for now; ready for future expansion) |
| 6 | **Re-OCR only when text low** | **Done** | `reingest_scanned_pdfs(min_chars_per_page=25)`; API `ReingestRequest.min_chars_per_page` |
| 7 | **Figure/caption from parser** | **Deferred** | Docling/Unstructured output if available (parser-dependent) |
| 8 | **Keyword boost + RRF** | **Done** | Retriever: `_apply_keyword_boost` before rerank |
| 9 | **Cross-file semantic dedup** | **Done** | `scripts/dedup_ingestion_chunks.py` (content-hash groups; report only) |
| 10 | **Canonical entities in Neo4j** | **Done** | Already MERGE + `normalize_entity_name` in knowledge_graph |
| 11 | **PII detection at ingest** | **Done** | `ira.brain.pii_redact`; `APP__REDACT_PII_AT_INGEST=true` to enable |
| 12 | **Delete by source/category** | **Done** | `QdrantManager.delete_by_source`, `delete_by_source_category` |
| 13 | **Dense + sparse hybrid (BM25/sparse + RRF)** | **Done** | `sparse_vectors.text_to_sparse`; `qdrant_manager`: hybrid collection (dense+sparse), upsert with both vectors, `hybrid_search` prefetch + RRF; `APP__USE_SPARSE_HYBRID`, `QDRANT__COLLECTION_HYBRID` |

Status key: **Done** | **Pending** | **Deferred**
