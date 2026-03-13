# CRM segment audit: current customers, leads, region / application / machine

**Goal:** Extract and report for Machinecraft machine sales:
- **Segments:** current customers, recent customers, past customers, hot leads, warm leads, cold leads  
- **Dimensions:** region-wise, application-wise, machine-wise  

**Status:** We have the data in the system (imports, schema) but it is not extracted into one queryable place; segment dimensions are partially in schema and partially missing.

---

## 1. Where the data lives today

| Source | What it has | Structured? |
|--------|-------------|-------------|
| **Postgres CRM** | companies (name, region, industry), contacts (contact_type, warmth_level, lead_score), deals (stage, machine_model) | Yes, but almost empty (1 deal) |
| **data/imports/07_Leads_and_Contacts** | List of Customers, European Leads, K2025 Leads, PlastIndia visitors, Clients MC EUROPE, etc. | XLSX/CSV/PDF — needs parse |
| **data/imports/08_Sales_and_CRM** | European Machine Sales, sales memos | XLSX/PDF |
| **data/imports/24_WebSite_Leads** | 50+ lead_*_contact_context.md with Company, Region, Machine to offer, application (e.g. automotive, RV), Client? (current/past/lead), email, name | Semi-structured (markdown) |
| **Gmail** | Sent/received — contact list + history | Not used (no token.json) |
| **Qdrant** | Chunks from ingested docs; metadata.customer sometimes set | Underused by populator |
| **Neo4j** | Person/Company nodes if ingestion wrote them | May be empty or different schema |

So: **we have the data** (customers, leads, region, machine, application) in imports and in schema; it is **not** yet extracted into CRM and not consistently tagged for segments.

---

## 2. Schema vs desired segments/dimensions

### 2.1 Segments (who they are)

| Desired segment | CRM / today | Gap |
|-----------------|-------------|-----|
| **Current customers** | LIVE_CUSTOMER + deal stage WON (or active machine in field) | LIVE_CUSTOMER exists; “current” could be “has WON deal or recent delivery”. Need last_order / last_delivery or use deal stage. |
| **Recent customers** | PAST_CUSTOMER with “recent” cutoff | PAST_CUSTOMER exists. “Recent” needs a rule (e.g. last interaction or last WON in last 12–24 months). No stored last_order_date; derive from interactions or deal.actual_close_date. |
| **Past customers** | PAST_CUSTOMER | Supported. |
| **Hot leads** | LEAD_* + high engagement | We have warmth_level (STRANGER→TRUSTED) and lead_score (0–100). Populator does not set them; Delphi only sets contact_type. Need to set warmth/score from behavior (replies, meetings, quote sent). |
| **Warm leads** | LEAD_* + some engagement | Same as hot; need rules or LLM to map behavior → warmth/score. |
| **Cold leads** | LEAD_* + no/low engagement | Same; cold = STRANGER or low score. |

### 2.2 Dimensions (how to slice)

| Dimension | In schema? | In imports? | Gap |
|-----------|------------|------------|-----|
| **Region** | Company.region, Contact (via company) | Yes (lead context: “Region: Europe (UK)”, “Asia-Pacific (Australia)”) | Populate from imports; ensure Gmail/Neo4j extractors pass region. |
| **Application** | Company.industry (proxy) only; no Deal.application | Yes in lead context (“Automotive, mass transit”, “RV industry parts”, “Prototyping & R&D”) | No Deal.application or Contact.application. Add Deal.application (or contact/company tag) or reuse industry. |
| **Machine** | Deal.machine_model, Quote.machine_model | Yes (“Machine to offer: PF1-C-3030”, “PF1-X-6520”) | Populate from imports and quote/deal creation. |

So: **region** and **machine** are in schema and in data; **application** exists in text but not as a dedicated field (industry is a partial proxy).

---

## 3. Why populate-crm got 0 contacts

- **Gmail:** Skipped (no `token.json`).  
- **KB (Qdrant):** Extraction only keeps points with `metadata.customer` set; many chunks don’t have it. Company-only contacts have `email: ""` and are **dropped in deduplication** (which keeps only contacts with email). So KB effectively contributed 0.  
- **Neo4j:** Expects `(p:Person)` with email and optional `(p)-[:WORKS_AT]->(c:Company)`. If the graph doesn’t have that shape or has no such nodes, extraction returns 0.  
- **Imports:** Populator does **not** read `data/imports` (24_WebSite_Leads, 07_Leads) at all. So the richest source of leads/customers is unused.

---

## 4. Fix plan (how to get segment- and dimension-wise extraction)

### Phase A — Get contacts and deals into CRM

1. **Add an “imports” source to the CRM populator**
   - **24_WebSite_Leads:** Scan `lead*_contact_context.md` (and optionally `*_email_history.md`). Parse:
     - Name, email, company (from headers and bullets).
     - Region (from “Region: …”).
     - Machine (from “Machine to offer: …”).
     - Application (from “Inquiry: …”, “Form specs: …”, “Industry” or “Client?” context).
     - Client? / Lead? (from “Client? No/Yes” and “We sent quote …”) → map to contact_type (LIVE_CUSTOMER / PAST_CUSTOMER / LEAD_*).
   - **07_Leads_and_Contacts:** For XLSX/CSV, add a reader (e.g. openpyxl/pandas) and map columns to contact + company (name, email, company, region). Optionally tag source = "imports_07".
   - Output: list of `{email, name, company, region, machine_model, application, contact_type_hint, source}`. Dedupe by email; then run existing Delphi classification (or skip and use contact_type_hint for imports-only). Insert into CRM: company (with region), contact (with contact_type, and optionally warmth from “Client?” / quote sent), deal (with machine_model, stage from hint).

2. **Keep Gmail and KB/Neo4j**
   - **Gmail:** Add `token.json` (OAuth) in project root so `populate-crm --source gmail` can run. Populator already passes region/company where available.
   - **KB:** Option A — during ingestion, set `metadata.customer` (and optionally region/machine) when the doc is a lead list or customer list. Option B — extend KB extractor to also pull from chunks that have company/customer in **content** (e.g. regex or small LLM) and set email from content or leave empty and **allow company-only contacts** to be inserted with a placeholder email (e.g. `company_slug@imports.placeholder`) so they are not dropped, then merge when real email appears.
   - **Neo4j:** Ensure ingestion (or a one-off job) creates Person (with email) and Company (with region) and WORKS_AT so `_extract_from_neo4j` returns contacts.

3. **Set warmth and lead_score**
   - After insert (or in a separate sweep): for each contact, use interaction history (and deal stage) to set warmth_level and lead_score. Rules: e.g. replied in last 30 days → WARM; meeting in last 90 days → WARM or TRUSTED; quote sent, no reply → ACQUAINTANCE; no touch → STRANGER. lead_score from reply count, recency, deal value. Optionally use Delphi to infer warmth from last N interactions.

### Phase B — Support “application” and segment reporting

4. **Application dimension**
   - **Option 1 (recommended):** Add `application` (or `application_segment`) to **Deal** (nullable string or enum). Populate from imports parser and from quote configuration when creating deals. Use for “application-wise” reporting.
   - **Option 2:** Use Company.industry only and map “RV industry”, “automotive” etc. into industry in imports parser. No schema change; reporting is industry-wise.

5. **Segment definitions in code**
   - **Current customers:** contact_type == LIVE_CUSTOMER, or has deal with stage WON and actual_close_date in last 12 months (or use Atlas “delivered” if available).
   - **Recent customers:** contact_type == PAST_CUSTOMER and (last_interaction or last WON deal) in last 12–24 months.
   - **Past customers:** PAST_CUSTOMER and not “recent”.
   - **Hot leads:** LEAD_* and (warmth_level in (WARM, TRUSTED) or lead_score >= 70).
   - **Warm leads:** LEAD_* and (warmth_level in (ACQUAINTANCE, FAMILIAR) or 40 <= lead_score < 70).
   - **Cold leads:** LEAD_* and (warmth_level == STRANGER or lead_score < 40 or null).
   - Implement in CRM layer as `list_contacts_by_segment(segment, filters)` or `get_segment_counts(filters)` where filters = {region, application, machine_model}.

6. **API and dashboard**
   - **API:** Add `GET /api/crm/segments?region=&application=&machine_model=` returning counts and optionally list per segment (current/recent/past/hot/warm/cold), plus breakdown by region, application, machine. Use new CRM methods that join contact + company + deal and apply segment rules.
   - **Dashboard:** Command Center (or web UI) calls this API and shows tables or charts: segment × region, segment × application, segment × machine.

### Phase C — Maintenance

7. **Ongoing sync**
   - Run `ira populate-crm --source all` periodically (e.g. weekly). Once “imports” source is added, include it in “all” so new lead_* files are picked up.
   - After Gmail is connected, new sent/received contacts are classified and inserted; warmth/score can be updated from interaction history.

8. **Data quality**
   - Normalize region (e.g. “Europe (UK)” → “EU” or “UK”) and machine_model (e.g. “PF1-C-3030” vs “PF1-C 3030”) so filters and reports are consistent. Optionally store normalized values in CRM and keep raw in notes.

---

## 5. Summary: what to do next

| Priority | Action | Outcome |
|----------|--------|---------|
| 1 | Add **imports** source to CRM populator: parse 24_WebSite_Leads (and optionally 07) → contacts + companies + deals with region, machine_model, application (or industry) | CRM filled with current/past/lead from your existing data |
| 2 | Add **Deal.application** (or use industry) and populate from imports | Application-wise reporting |
| 3 | Define **segment rules** (current/recent/past/hot/warm/cold) in CRM layer and expose **GET /api/crm/segments** with region/application/machine filters | One API for all segment × dimension views |
| 4 | Add **warmth/lead_score** update step (from interactions + deals) and use in segment rules | Hot/warm/cold leads reflect behavior |
| 5 | (Optional) Gmail token + run populate-crm; (optional) KB metadata or content-based extraction so KB contributes contacts | More coverage |

Implementing **1** and **2** gives you extract (current/recent/past customers, hot/warm/cold leads) and dimension (region, application, machine) for Machinecraft machine sales; **3** and **4** make segment reporting and lead temperature accurate and dashboard-ready.
