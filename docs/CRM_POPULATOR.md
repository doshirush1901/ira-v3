# CRM Populator — Sources and Column Mappings

The CRM populator (`ira populate-crm`) extracts contacts from multiple sources, classifies them (via Delphi or lead context), and inserts CRM-eligible contacts and deals into PostgreSQL.

## Sources

| Source          | Description |
|-----------------|-------------|
| `gmail`         | Gmail sent/received (requires `token.json`). |
| `kb`            | Qdrant knowledge base — company/contact mentions from ingested docs. |
| `neo4j`         | Neo4j Person/Company nodes. |
| `imports`       | `data/imports/24_WebSite_Leads` — `*_contact_context.md` files. |
| `imports_07`    | `data/imports/07_Leads_and_Contacts` — XLSX/CSV + Single Station Inquiry at imports root. |
| `imports_08`    | `data/imports/08_Sales_and_CRM` — XLSX, CSV, and PDF (LLM extraction). |
| `takeout_sent`  | `data/takeout_ingest/*.mbox` — contacts we emailed (From: *@machinecraft*). |

Default when no `--source` is given: all of the above.

Examples:

```bash
poetry run ira populate-crm --dry-run
poetry run ira populate-crm --source imports_07,imports_08 --dry-run
poetry run ira populate-crm --source imports_07,imports_08
```

## Spreadsheet columns (07 and 08)

For XLSX/CSV in `07_Leads_and_Contacts` and `08_Sales_and_CRM`, the first row is treated as headers. Normalization is case-insensitive and replaces spaces/dashes with underscores.

### Contact

| Normalized header   | Maps to   | Example column names |
|---------------------|-----------|----------------------|
| Email               | `email`   | Email, E-mail, Contact_Email |
| Name                | `name`    | Name, Contact, Contact_Name, Full_Name |
| Company             | `company` | Company, Organisation, Organization, Company_Name |
| Region              | `region`  | Region, Country, Location |

### Deal (optional)

| Normalized header   | Maps to          | Example column names |
|---------------------|------------------|----------------------|
| Machine / model     | `machine_model`  | Machine_Model, Model, Machine, Machine_Type, Machines_Mentioned (purely numeric values like counts are ignored) |
| Value / amount      | `quote_value`   | Quote_Value, Amount, Value, Quote_Value_USD, Deal_Value, Order_Value |
| Stage / status      | `stage`         | Stage, Status, Deal_Stage, Deal_Status |
| Application/segment | `application`   | Application, Target_Applications, Segment |

- **quote_value**: Parsed as float (commas and currency symbols stripped). If present and ≥ 0, the created deal uses this value.
- **stage**: Mapped to CRM deal stage. Examples: `won`, `delivered`, `closed won` → WON; `lost`, `closed lost` → LOST; `new`, `contacted`, `engaged`, `qualified`, `proposal`, `negotiation` → corresponding `DealStage`; unknown → CONTACTED.

## 08_Sales_and_CRM PDFs

When `imports_08` is used, the populator also scans `data/imports/08_Sales_and_CRM/*.pdf`. For each PDF:

1. Text is extracted via the document ingestor (pypdf, with Document AI OCR fallback for scanned PDFs).
2. An LLM extracts contacts (name, email, company, machine_model) from the text.
3. Extracted contacts are merged with those from 08 XLSX/CSV and deduplicated by email.

PDF extraction is best-effort; XLSX/CSV remain the primary source for structured 08 data.

## Deduplication and updates

Contacts are deduplicated by email. When the same email appears in multiple sources, fields are merged: company/name/region/phone from any source, machine_model/quote_value/stage preferred from the “richest” row (e.g. higher quote_value, or stage WON over CONTACTED).

**Existing contacts:** If a contact already exists in the CRM (skipped as duplicate), the populator can still:
- **Backfill** — Create a new deal if the contact has no deals and the import has `machine_model`.
- **Update** — If the contact has at least one deal and the import has `quote_value` and/or `stage`, the first deal is updated with those values (and optionally `machine_model`). Stage transitions from import data use `force=True` (e.g. can set to WON).

So re-runs with the same 07/08 data can refresh deal value and stage for existing contacts; the run summary includes **Deals updated**.

## See also

- `src/ira/systems/crm_populator.py` — implementation.
- `docs/LEADS_CLASSIFY_BY_COMMUNICATION.md` — lead classification context.
- `AGENTS.md` — Populator agent and CLI commands.
