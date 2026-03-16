# Ingestion: Making It Better / State of the Art

This doc outlines **concrete improvements** to Ira’s ingestion and retrieval pipeline so it stays current with best practices. It assumes the current design (metadata index → DigestiveSystem → Qdrant + Neo4j, semantic chunking, reranking) and suggests upgrades that fit the codebase and VISION priorities.

---

## What You Already Have (Strong Base)

| Area | Current state |
|------|----------------|
| **Parsing** | Docling + Unstructured for layout/tables; pypdf + Document AI OCR fallback |
| **Chunking** | SemanticChunker (Chonkie) with Voyage when available; table protection; tiktoken fallback |
| **Digestive** | LLM: nutrient classification → summarization → entity extraction; then embed → Qdrant + Neo4j |
| **Retrieval** | UnifiedRetriever: Qdrant + Neo4j + Mem0; Voyage Rerank + FlashRank; query decomposition |
| **Quality** | QualityFilter (length, diversity, numeric ratio); optional semantic dedup before upsert |
| **Metadata** | Per-file LLM metadata (summary, doc_type, entities, keywords) for Alexandros |

---

## 1. Chunking: Richer Structure and Retrieval

**Goal:** Better recall and context for the LLM without blowing context windows.

- **Parent–child or hierarchical chunks**  
  Store a short “parent” (e.g. section or doc summary) and attach it to “child” chunks in payload. At retrieval, return parent + child so the model sees local + broader context. Implement by:
  - In DigestiveSystem / `chunk_text` path: optionally produce a one-sentence “section summary” per logical block (e.g. via a light LLM call or first-sentence heuristic) and store as `parent_summary` or similar in chunk metadata.
  - Retriever returns both chunk and parent; shaper prepends parent to chunk when building context.

- **Sentence-window retrieval**  
  Store a “window” (e.g. ±2 sentences) around each chunk and only embed the core sentence(s). At retrieval, return the window so the model sees surrounding context. Fits well with existing semantic chunking: define “core” vs “window” and store both in payload.

- **Chunk size / strategy by doc_type**  
  Use metadata index `doc_type` (and optionally category) to tune chunk size or strategy: e.g. smaller chunks for contracts/quotes (precise clauses), larger for manuals/reports. Pass `doc_type` into the chunking path and choose `chunk_size` / overlap or chunker type accordingly.

**Where in code:** `document_ingestor.chunk_text`, DigestiveSystem `_absorb` (chunk_text usage), `KnowledgeItem` metadata; retriever and pipeline “context builder” that assembles retrieved chunks for the LLM.

---

## 2. True Dense + Sparse (Hybrid) at Index and Query

**Goal:** Strong performance on exact terms (model numbers, names, IDs) and semantic queries.

- **Current:** Qdrant is used for dense-only search; “hybrid” in the codebase is category filtering + dense, not dense + sparse vectors.
- **Improvement:** Use Qdrant’s (or your stack’s) **sparse vector** support:
  - At ingest: for each chunk, compute a sparse vector (e.g. BM25 or learned sparse) and store alongside the dense Voyage vector.
  - At query: embed query for dense; optionally compute sparse for query; combine dense + sparse (e.g. reciprocal rank fusion or Qdrant’s hybrid API) then rerank.
- **Fallback:** If you don’t add sparse in Qdrant, keep using Alexandros/imports metadata index for keyword-heavy lookups and fuse with Qdrant results (you already do some of this). Formalizing “keyword path” + “dense path” + RRF is a lighter variant.

**Where in code:** `QdrantManager.upsert_items` (add sparse payload or second vector if supported); `UnifiedRetriever.search` / `_rerank` (combine dense + sparse results); embedding service or a small sparse module.

---

## 3. LLM Use: Cheaper, Faster, More Robust

**Goal:** Same or better quality with lower cost and latency.

- **Batch metadata indexing**  
  Metadata index today: one LLM call per file. For large imports, batch files (e.g. 5–10) into one prompt: “For each of the following document previews, return the metadata list.” Reduces round-trips and can use a single larger context window. Requires parsing a list of `DocumentMetadata` and mapping back to file paths.

- **Smaller/faster model for classification**  
  STOMACH nutrient classification is highly structured. Try a smaller/faster model (e.g. GPT-4.1-mini or a small local model) with the same schema; keep heavier models for DUODENUM summarization and entity extraction if needed.

- **Caching and idempotency**  
  Cache LLM outputs keyed by (file path + content hash) or (text hash) for nutrient classification and summarization so re-runs or repeated chunks don’t re-call. You already have embedding cache; extend the idea to structured LLM outputs where safe.

- **Structured output validation and retries**  
  Ensure all `generate_structured` calls use strict schema validation and a single retry with a “fix the JSON” prompt on parse failure to avoid dropping documents.

**Where in code:** `imports_metadata_index._generate_metadata_llm` (batching); `digestive._classify_window` / `_call_summarize` (model choice, caching); shared LLM client or a small “structured cache” layer.

---

## 4. Retrieval: Reranking and Diversity

**Goal:** Better precision and less redundant context.

- **Rerank with the same model as embedding**  
  You already use Voyage Rerank + FlashRank. Prefer Voyage Rerank when the reranker was trained for the same (or similar) embedding model so query–document scoring is consistent.

- **Diversity (MMR or similar)**  
  After reranking, apply a simple MMR (maximal marginal relevance) step: iteratively pick the next result that maximizes a combination of relevance and dissimilarity to already-selected chunks. Reduces near-duplicate chunks in the same context.

- **Over-retrieve then rerank**  
  Retrieve more (e.g. 2–3×) than the final `limit`, then rerank and trim. You may already do this; if not, make over-retrieval and rerank the default path so the model sees the best subset.

**Where in code:** `UnifiedRetriever._rerank`, `search` / `decompose_and_search` (over-retrieve + rerank + optional MMR).

---

## 5. Document Parsing and OCR

**Goal:** Best possible text and structure from every file.

- **Docling/Unstructured first for PDFs**  
  Ensure the default path for PDFs (and other supported types) is Docling (or Unstructured) when configured, with pypdf + Document AI only as fallback. Reduces “blob of text” ingestion and improves tables and reading order.

- **Figure and caption extraction**  
  Where Docling/Unstructured expose figures and captions, append “Figure N: <caption>” (or a short description) to the text sent to the DigestiveSystem so that “diagram of X” is searchable.

- **Re-OCR strategy**  
  Re-OCR only when extracted text is below a threshold (e.g. character count or word count per page). You already have reingest-scanned; optionally add a “low-text” detector so only clearly image-heavy PDFs go to Document AI.

**Where in code:** `document_ingestor` reader selection (e.g. `_read_pdf`, `_LEGACY_READERS`, Docling/Unstructured wiring); reingest-scanned logic.

---

## 6. Evaluation and Observability

**Goal:** Data-driven tuning and regression detection.

- **Retrieval eval set**  
  Maintain a small curated set of (query, expected doc/chunk IDs or expected snippets). Run weekly or on-demand: retrieve top-k for each query, compute hit rate / MRR / precision@k; log to a dashboard or file. Start with 20–30 queries that matter (quotes, orders, manuals, CRM).

- **Chunk and ingestion metrics**  
  Log per-run stats: chunks created, entities added, quality-filter rejections, and (if you add it) semantic-dedup drops. Track trends so you notice drops in coverage or quality.

- **A/B or config flags**  
  When you change chunk size, model, or reranker, make the choice configurable (e.g. env or config) and run the same eval set for “old” vs “new” and compare.

**Where in code:** New small module or script under `scripts/` or `tests/` for retrieval eval; ingestion_gatekeeper or digestive to emit metrics; config for chunk/model/rerank choices.

---

## 7. Deduplication and Entities

**Goal:** Fewer redundant chunks and cleaner graph.

- **Cross-file semantic dedup**  
  QualityFilter already has optional semantic dedup per run. Optionally run a periodic job that finds very similar chunks across different sources (e.g. same quote text in two folders) and merges or demotes duplicates so retrieval doesn’t return the same content twice.

- **Canonical entities in Neo4j**  
  When extracting companies/people/machines, resolve to canonical nodes (e.g. by name normalization or a simple match step) so the graph doesn’t accumulate many “Acme” variants. Link chunks to canonical entity IDs in payload.

**Where in code:** QualityFilter (semantic dedup); DigestiveSystem LIVER step and Neo4j `add_company` / `add_person` / `add_machine` (canonical resolution); optional batch job for cross-file dedup.

---

## 8. Security and Compliance

**Goal:** Avoid storing PII or sensitive content in plain text where not needed.

- **PII detection before store**  
  Run a light PII detector (e.g. regex + optional small model) on chunks before upserting. Either redact (e.g. replace with [REDACTED_EMAIL]) or tag and store in a restricted collection. Aegis already does outbound scanning; add an ingestion-time step for at-rest content.

- **Retention and deletion**  
  If you have compliance requirements, support “delete all chunks from source X” or “delete by source_category” so you can remove data when requested.

**Where in code:** DigestiveSystem before `_absorb`, or in DocumentIngestor before building KnowledgeItems; QdrantManager delete by filter (if supported).

---

## Priority Order (Suggested)

Align with VISION’s “Retrieval quality” and “Reliability”:

1. **High impact, lower effort:** Over-retrieve + rerank; chunk size by doc_type; ensure Docling/Unstructured first for PDFs.
2. **High impact, more effort:** Dense + sparse hybrid indexing and search; parent–child or sentence-window retrieval.
3. **Quality and cost:** LLM batching and caching for metadata and digestive; smaller model for STOMACH; retrieval eval set.
4. **Ongoing:** Cross-file dedup; canonical entities; PII at ingest; observability dashboard.

---

## Summary Table

| Improvement | What | Why |
|-------------|------|-----|
| Parent–child / sentence-window | Richer context per chunk at retrieval | Better answers without huge context |
| Dense + sparse hybrid | Sparse (e.g. BM25) + Voyage at index and query | Exact match + semantic in one retrieval path |
| Batch metadata + smaller STOMACH model | Fewer/smaller LLM calls | Lower cost, faster ingestion |
| Rerank + MMR | Over-retrieve, rerank, then diversify | Fewer redundant chunks in context |
| Docling first + figure captions | Layout-aware parsing, captions in text | Better tables and “what’s in the diagram” |
| Retrieval eval set | Curated queries + metrics | Tune and avoid regressions |
| Cross-file dedup + canonical entities | Less duplicate content and graph clutter | Cleaner KB and graph |

All of these can be implemented incrementally; no need to change the overall workflow (index → ingest → re-OCR) or the DigestiveSystem metaphor.
