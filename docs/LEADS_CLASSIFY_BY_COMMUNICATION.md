# Classify import leads by communication (they replied or sent us email)

**Goal:** From the lead lists in imports (Competitor Customer Analysis, LLM Thermoforming Prospects, Thermoforming Machine Market Data - Europe, European & US Contacts, K2016, K2022, K2025), **classify** leads by whether they have **ever communicated** with us. **Communication** = they sent us at least one email (reply or new) that is **not** an auto-reply. We do **not** count "we sent, they didn't reply" as communicated.

**Output:** A list of **only** people who have either replied to us or sent us a new email (genuine messages, no out-of-office/bounces).

---

## How it works

1. **Extract leads** from these files (by email; deduped):
   - `07_Leads_and_Contacts/European & US Contacts for Single Station Nov 203.csv`
   - `07_Leads_and_Contacts/K2025 Leads.xlsx`
   - `07_Leads_and_Contacts/K2022 Meetings.xlsx`
   - `07_Leads_and_Contacts/K2016 - Data for Exhibition Inquiry & Analysis.xlsx`
   - `06_Market_Research_and_Analysis/LLM_Thermoforming_Prospects.xlsx`
   - `06_Market_Research_and_Analysis/Competitor Customer Analysis - Single Station Thermoforming.xlsx`
   - `06_Market_Research_and_Analysis/Thermoforming Machine Market Data - Europe.xlsx`
   - **Not included:** `02_Orders_and_POs/Top 50 European Thermoforming Companies – Profiles & Opportunities.pdf` (PDF; no email extraction in script).

2. **For each lead email:** Call Ira API `POST /api/email/search` with `from_address=<lead email>` (emails **we received from** them).

3. **Filter auto-replies:** For each message returned, discard if it looks like out-of-office, vacation, bounce, noreply, etc. (same logic as `scripts/check_european_lead_conversations.py`).

4. **Communicated = true** if there is at least one non–auto-reply email **from** them **to** us.

5. **Output:** Print and/or write CSV of **communicated only** (and optionally full classification CSV with a `communicated` column).

---

## Prerequisites

- **Ira API running** (so Gmail can be searched):  
  `poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000`
- Gmail configured (OAuth token) so the API can search mail.
- `httpx` and `openpyxl` (already in the project).

---

## Usage

```bash
# 1. Start Ira API (so /api/email/search works)
poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000

# 2. Dry-run: only load leads, no API calls
poetry run python scripts/classify_import_leads_by_communication.py --dry-run

# 3. Run classification (calls Gmail via API for each lead)
poetry run python scripts/classify_import_leads_by_communication.py

# 4. Write communicated-only CSV
poetry run python scripts/classify_import_leads_by_communication.py --output data/reports/leads_communicated_only.csv

# 5. Also write full classification (all leads + communicated column)
poetry run python scripts/classify_import_leads_by_communication.py \
  --output data/reports/leads_communicated_only.csv \
  --full data/reports/leads_full_classification.csv

# 6. Limit how many to check (e.g. first 50)
poetry run python scripts/classify_import_leads_by_communication.py --limit 50 --output data/reports/leads_communicated_only.csv
```

---

## Output columns

- **Communicated-only CSV:** `email`, `name`, `company`, `source`, `emails_from_them`, `genuine_replies`
- **Full CSV (--full):** same plus `communicated` (true/false)

---

## Relation to existing scripts

- **`scripts/hot_leads_email_count.py`** — Uses same API (`from_address` / `to_address`) for a fixed list of hot/frozen emails; only prints counts.
- **`scripts/check_european_lead_conversations.py`** — Uses Gmail API directly (not Ira API), expects `european_leads_structured.json`, and filters genuine vs auto-reply; outputs conversation summary. The **classify_import_leads** script uses the **Ira** API and **import files** as source, and outputs **communicated-only** (or full) CSV.

---

**Confidence:** high  
**Sources:** `scripts/classify_import_leads_by_communication.py`, `scripts/check_european_lead_conversations.py`, `scripts/hot_leads_email_count.py`, `src/ira/interfaces/server.py` (email search)
