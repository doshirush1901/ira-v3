# Good leads (for outbound mail)

**Good leads** = people we should mail. They are **not** list-only contacts with no prior engagement.

## Definition

A **good lead** is someone who has **communicated** with us:

- They **replied** to an email we sent, or  
- They **sent us** an email (inquiry, question, quote request) that was **not** an auto-reply.

We **do not** count "we sent, they never replied" as communicated. We **do not** treat agency/partner contacts (e.g. Formech agent who wanted to be our agent) as good leads when the relationship is of no use.

## How to get good leads

1. **Run the top-50 script (requires Ira API + Gmail):**
   ```bash
   # Start API so Gmail can be searched
   poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000

   # Get good leads: 07_Leads, exclude customers + exclusion list, keep only communicated, top 50 by genuine replies
   poetry run python scripts/top50_hot_leads_excluding_customers.py --output data/reports/top50_good_leads.csv
   ```
   This uses Gmail (via API) to see who has actually replied or emailed us. Output: CSV of **good leads only**, ranked by hottest (genuine replies, then total from them).

2. **Exclusion list:** The script also excludes emails in `data/knowledge/lead_campaign_exclusion_list.txt` (agency/partner, not customers). Add any contact there that is not a potential customer.

3. **Use this list for "next lead":** When drafting or sending to the next lead, **pick from the good-leads CSV** (or the script output), not from the CRM ranked API. Then run `pull_contact_email_history.py` for that email to get full thread context before drafting.

## Why not CRM ranked API for "who to mail"

The CRM ranked pipeline (`GET /api/deals/ranked`) has almost no Gmail-backed interactions (legacy mail wasn’t logged). So:

- With `engagement_only=true` it often returns **0** deals.
- With `engagement_only=false` it returns list-import contacts who may have **never** replied — so they are **not** good leads.

Use the **good-leads list** (top50 script output) as the source of who to mail. Use CRM for deal/contact details once you’ve chosen a lead from that list.

## Deep scan (full intel before next-step email)

For a **deep scan** of leads across all memory types and web intel, use:

```bash
# 1. Get good leads (API + Gmail)
poetry run python scripts/top50_hot_leads_excluding_customers.py --output data/reports/top50_good_leads.csv

# 2. Deep scan: Mem0, Neo4j, Qdrant, Alexandros, email history, web (Iris)
poetry run python scripts/deep_scan_leads.py --input data/reports/top50_good_leads.csv --limit 10 --output data/reports/deep_scan_report.md
```

The script checks: **Mem0** (recall by contact email), **email** (Gmail + pull_contact_email_history for relationship summary), **Alexandros** (document archive), **knowledge base** (Qdrant + Neo4j via pipeline), and **web** (Iris) for company intel. Report includes a suggested next step per lead. See `scripts/deep_scan_leads.py` docstring.

## Summary

| Source | Use for |
|--------|--------|
| `scripts/top50_hot_leads_excluding_customers.py` + exclusion list | **Who to mail** — good leads only (communicated). |
| `scripts/deep_scan_leads.py` | **Full intel** — Mem0, Neo4j, Qdrant, Alexandros, email summary, web. |
| `pull_contact_email_history.py` | **Context** for the chosen lead before drafting. |
| CRM ranked API | Optional for deal/company info; not the source of "next lead" when we need good leads only. |
