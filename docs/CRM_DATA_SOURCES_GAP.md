# Why isn’t all our data in the CRM?

**Short answer:** The CRM populator only reads **one** of your many data sources today: `data/imports/24_WebSite_Leads` (and only the `*_contact_context.md` files). Customer lists, production data, inquiry XLS, and mailbox/takeout data are either in other folders and not read, or ingested into Qdrant/Neo4j but not bulk-loaded into Postgres CRM.

---

## 1. Where the data actually is

| Data you have | Location | Ingested? | Used by populate-crm? |
|---------------|----------|-----------|------------------------|
| **Customer list, European leads, K2025, PlastIndia, etc.** | `data/imports/07_Leads_and_Contacts/` (XLSX/CSV) | Yes (docs can be in Qdrant if ingested) | **No** — populator has no 07 reader |
| **European Machine Sales, sales memos** | `data/imports/08_Sales_and_CRM/` (XLSX/PDF) | Same | **No** |
| **Single Station Inquiry (responses)** | `data/imports/Single Station Inquiry Form (Responses).xlsx` | — | **No** |
| **Machines on production / current orders** | `data/imports/Current Machine Orders/`, `02_Orders_and_POs/` | Likely in Qdrant if ingested | **No** — no production/order → CRM pipeline |
| **Hot leads (e.g. Naffco KSA), client email threads** | `data/takeout_ingest/*.mbox` (Gmail Takeout) | **Yes** — into **Qdrant** (chunks), **Neo4j** (people/companies/machines), **Mem0** (facts) via `ira takeout ingest` | **No** — populator uses **Gmail API** (needs `token.json`), not mbox files; no bulk “Neo4j → CRM” or “takeout → CRM” step |
| **Website leads (contact context)** | `data/imports/24_WebSite_Leads/*_contact_context.md` | — | **Yes** — only source currently used (19 contacts) |
| **Case studies (Naffco, IAC, Dutch Tides, etc.)** | `data/case_studies/*/` (JSON + md) | In knowledge / Cadmus | **No** |
| **Customer orders history** | `data/knowledge/customer_orders_history.md` | In Qdrant if ingested | **No** — KB extractor only uses chunks with `metadata.customer` and drops company-only (no email) |

So: **we do have this data ingested somewhere** (Qdrant, Neo4j, Mem0, and/or files in imports), but **almost none of it is wired into the CRM populator**. Only 24_WebSite_Leads markdown files are read and pushed to Postgres CRM.

---

## 2. Why mailbox/takeout isn’t in CRM

- **Takeout ingestion** (`ira takeout ingest`): reads `data/takeout_ingest/*.mbox`, extracts “protein” (entities, relationships), and writes to **Qdrant**, **Neo4j**, and **Mem0**. It does **not** write to Postgres CRM.
- **Populator “Gmail” source**: uses the **Gmail API** (requires `token.json`). It never reads the mbox files. So even with takeout ingested, the CRM doesn’t get those contacts unless:
  - You use Gmail API (token) and run `populate-crm --source gmail`, or
  - We add a “takeout” or “neo4j” path that bulk-loads Person/Company from Neo4j (or from mbox folder names + sample messages) into CRM.

Neo4j *does* get Person/Company from takeout (and other ingestion). So **after takeout ingest**, running `populate-crm --source neo4j` can in theory pull those into CRM — but that only works if Neo4j has `Person` nodes with `email` and optional `WORKS_AT → Company`. If the takeout pipeline doesn’t emit those, or the graph schema is different, you get 0 contacts from Neo4j.

---

## 3. What to do next (prioritised)

1. **Add 07_Leads_and_Contacts + Single Station Inquiry**  
   Implement a reader in the CRM populator for:
   - `data/imports/07_Leads_and_Contacts/` (List of Customers, European Leads, K2025 Leads, etc.) — XLSX/CSV.
   - `data/imports/Single Station Inquiry Form (Responses).xlsx` (if present).
   Map columns (Email, Name, Company, Region, etc.) to contact/company and add as a new source (e.g. `imports_07`) so `populate-crm --source all` includes them.

2. **Use Neo4j after takeout**  
   Ensure takeout (or document ingestion) writes **Person** (with email) and **Company** to Neo4j; then run `populate-crm --source neo4j` (or `--source all`) so those flow into CRM. If Neo4j still returns 0, fix the graph writer or the populator’s Cypher query.

3. **Optional: takeout mbox → CRM**  
   Add a “takeout” source that scans `data/takeout_ingest/*.mbox` (e.g. folder names like “Machinecraft - Clients-Naffco”, “Machinecraft Sales Inquiry-Thermic Energy”) and/or first N messages per mbox to derive contacts and push to CRM. That way mailbox ingestion data feeds CRM even without Gmail API.

4. **Optional: production / orders → CRM**  
   Add a pipeline that reads `Current Machine Orders` or `02_Orders_and_POs` and creates/updates companies and deals (machine, stage) in CRM. Lower priority than 1–2.

---

## 4. Summary

- **Data is there:** customer lists in 07, Single Station Inquiry xlsx, production/orders in imports, hot leads and client threads in takeout (and in Qdrant/Neo4j after ingest).
- **CRM is thin** because the populator only reads **24_WebSite_Leads** `*_contact_context.md`. Gmail source needs API token; KB drops company-only; Neo4j may be empty or schema mismatch; 07/08/root xlsx and takeout mbox are not read at all.
- **Next step:** Add 07_Leads_and_Contacts (and Single Station Inquiry) as a populator source so CRM fills from your existing XLSX/CSV; then verify Neo4j → CRM and optionally add takeout → CRM.
