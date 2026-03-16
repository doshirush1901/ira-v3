# Imports: Quote PDF semantics

## 01_Quotes_and_Proposals

Documents in `data/imports/01_Quotes_and_Proposals/` are **outbound quotes and proposals** from Machinecraft. They are critical for pipeline and CRM context.

### Quote PDFs (e.g. "2x3 m Forming Area Quote Machinecraft PF1 Thermoforming V0.3")

- **Content:** Customer name (often in filename or inside the PDF), tech specs, price, machine model (e.g. PF1).
- **Semantic:** These are **quotes we sent** to a prospect/customer. Unless CRM or email shows otherwise, treat them as **quote sent but we did not follow up** — i.e. no confirmed order or closed loop from this document alone.
- **Use in retrieval:** When answering "who did we quote?", "which quotes are outstanding?", or lead follow-up questions, surface these as "quote sent to [customer]; follow-up status unknown unless CRM/email says otherwise."

### About Us / company presentations (e.g. "About Us - Nov 22 PPT Machinecraft India")

- **Content:** Company data, customer logos/case studies, product overview, regional info.
- **Use:** Strong source for Machinecraft positioning, past customers, and reference data. Prefer for "who are our customers?", "what does Machinecraft do?", and similar.

### Deep scan and knowledge update

To refresh knowledge from all docs in imports (including 01_Quotes_and_Proposals):

1. **Rebuild metadata index** (LLM summaries, doc_type, entities):  
   `ira index-imports --force`
2. **Run full ingestion** (DigestiveSystem → Qdrant, Neo4j, Mem0):  
   `ira ingest --force`  
   Or only a subset, e.g. quotes folder:  
   `ira ingest --force --include-prefix 01_Quotes_and_Proposals`
3. **Re-OCR scanned PDFs** (large PDFs with little extractable text):  
   `ira reingest-scanned`  
   Or via API: `POST /api/reingest-scanned` (optional `min_file_size_mb`).

See [Deep scan workflow](#deep-scan-workflow) below.

---

## Deep scan workflow

| Step | Command / API | Purpose |
|------|----------------|--------|
| 1. Index | `ira index-imports --force` | Refresh file metadata (doc_type, summary, entities) for all of `data/imports/`. |
| 2. Ingest | `ira ingest --force` | Process all pending files through DigestiveSystem → Qdrant, Neo4j, Mem0. Use `--include-prefix <folder>` to limit to e.g. `01_Quotes_and_Proposals`. |
| 3. Scanned PDFs | `ira reingest-scanned` or `POST /api/reingest-scanned` | Re-OCR large PDFs with poor text, then re-ingest. |

All of these use the same APIs and pipelines (metadata index, ingestion log, DocumentIngestor, DigestiveSystem). No separate "scan" process — indexing + ingestion is the deep scan.

---

## 02_Orders_and_POs

Documents in `data/imports/02_Orders_and_POs/` are **current orders, POs, work orders, and order-related spreadsheets** at Machinecraft. They are execution/order ground truth for pipeline and Atlas.

### Deep ingest only this folder

To ingest all data from `02_Orders_and_POs` into the knowledge base (Qdrant, Neo4j, Mem0), from project root:

1. **Index** (LLM summaries and metadata for that folder):  
   `poetry run ira index-imports --include-prefix 02_Orders_and_POs`
2. **Ingest** (chunk, embed, upsert; optional `--force` to re-ingest all files):  
   `poetry run ira ingest --include-prefix 02_Orders_and_POs`  
   Or force a full re-ingest:  
   `poetry run ira ingest --include-prefix 02_Orders_and_POs --force`

Use `--workers 5` (default) or higher for faster parallel ingestion. Re-OCR large scanned PDFs in that folder with:  
`poetry run ira reingest-scanned --base-path data/imports/02_Orders_and_POs`
