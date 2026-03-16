# Case Study & Customer Corrections

Corrections applied so Ira and content do not repeat wrong claims.

## REINRAUM-MIETEN / hassa@reinraum-mieten.de (March 2026) — NOT A LEAD

- **Mistake:** We sent an outbound email to REINRAUM-MIETEN (Hassa, hassa@reinraum-mieten.de) treating them as a hot lead.
- **Correct:** REINRAUM-MIETEN is a **cleanroom rental** company (Germany). They did **not** inquire about thermoforming; the deal was a list-import / CRM record with **no email thread** and **no evidence of interest**. Do **not** treat them as a lead or send further outreach.
- **Remember:** Only treat as leads contacts who have **replied at least once** (inbound email) or have clear inquiry evidence. Ranked pipeline now uses `engagement_only=True` by default and **`data/knowledge/lead_campaign_exclusion_list.txt`** to exclude list-only and agency/partner contacts. When drafting/sending to "next lead", always include: **why they are a lead** (inquiry, reply, proposal sent), **what proposal/email was sent if any**, and **last email subject/preview**.

## THERMOFORMEUSE / info@thermoformeuse.fr (March 2026) — NOT A LEAD

- **What they are:** Philippe FRANCOIS / Thermoformeuse (Formech France) — they are a **Formech sales agent**, not a customer. The relationship was about them **wanting to be a sales agent for us** (Machinecraft); we had agency-for-France discussions, Lyon meeting, etc.
- **Why they are not a lead:** A **lead** is a (potential) **customer** — someone who might buy our machines or who is inquiring on behalf of a buyer. Philippe is not a buyer; he wanted to *sell for us* as an agent. So he’s an agency/partner contact. Per last email with them, **this relationship is of no real use** — we’re not pursuing that channel with them, so there’s no value in treating them as a sales lead. Lead list = customers and customer-side inquiries only; exclude ex–agency/partner contacts when the relationship is of no use.
- **Correct:** Do **not** treat THERMOFORMEUSE / info@thermoformeuse.fr as a sales lead. Do not send them lead-style outbound. They are an ex–agency prospect, not a buyer of our machines. Their email is in **`data/knowledge/lead_campaign_exclusion_list.txt`** so the ranked pipeline filters them out automatically.
- **Also:** Before drafting any "next lead" email, run `pull_contact_email_history.py` so we know context; and add agency/partner contacts (relationship of no use) to `lead_campaign_exclusion_list.txt`.

## THERMOFORMEUSE (March 2026) — always check Gmail before next-lead draft

- **Process lesson:** We sent a generic "first touch" to THERMOFORMEUSE without checking Gmail; CRM had almost no history. Before drafting/sending to any "next lead", **always** run `scripts/pull_contact_email_history.py --email <their_email>` and use the logic tree to see **why** we were in touch (customer inquiry vs agency vs other). Exclude contacts where the relationship is of no real use (e.g. ex–agency, Formech agent). See `data/knowledge/outgoing_marketing_email_workflow.md` § Next-lead send.

## Plastoranger Advanced Technologies (March 2026)

- **Wrong (removed):** "Plastoranger is a $200M automotive group."
- **Correct:** Plastoranger Advanced Technologies is a thermoforming / plastics processing company in Pune, India. They are **not** an automotive group and **not** $200M. Do not describe them as such. Use: "A thermoforming leader in India" or "Plastoranger Advanced Technologies" without size or automotive claims.
- **Source of error:** Case study copy had been incorrectly labelled; corrected in `plastoranger-complete-line-india` case study and index.

## India automotive customers — references

**Accurate automotive customers in India (case studies):**
- **IAC International Automotive India** — IMG/TPO, automotive interiors (Manesar).
- **Pinnacle Industries** — Large-format automotive components (PF1-5028 XL).
- **ALP Group** — Automotive components, Mahindra bedliner (Nashik); $200M automotive components conglomerate is correct for ALP only.

**Other automotive customers (not yet full case studies):**
- **Alphafoam** and others — We have many other customers in auto; Alphafoam is one. Do not limit India auto references to only IAC, Pinnacle, ALP. When asked for automotive references in India, consider that additional customers exist beyond the published case studies.

## PF1-X-5028 & PF1 specs (March 2026)

- **516 kW (PF1-X-5028):** Top and bottom heater **combined**, not top only. Total connected 602 kW = 516 kW heater + 86 kW servo.
- **Sheet thickness (PF1-C and PF1-X single-station):** **2–12 mm** for both (not 2–6 mm only).
- **Sheet loading:** Manual or with autoloader (option on both where applicable).
- **Universal frames:** **Sheet size changeover system** (for quick size changeover), not just "for loading".
- **PF1 options:** See `data/knowledge/pf1_specs_and_options.md` and `data/imports/04_Machine_Manuals_and_Specs/PF1 1015 all options format Machinecraft INR.pdf` and `PF1 3520 Machinecraft all Options V02.pdf`.

## Acme Packaging / Acme (March 2026)

- **Wrong:** Any deal analysis, CRM data, or proposal content that describes "Acme Packaging BV", "Erik Janssen", "Q-2024-089", "2× PF1 EUR 450,000", Netherlands, advance payments, or pipeline status for Acme as if it were real customer data.
- **Correct:** "Acme" and "Acme Packaging" in this repo appear only in **eval datasets and test fixtures** (e.g. `tests/eval_dataset.json`) as **example/synthetic data**. Do **not** use them as factual CRM, pipeline, or deal information. For any real Acme deal or contact, use live CRM, pipeline API, or email — not the eval context.
- **Action:** The file `data/knowledge/acme_deal_analysis_and_proposal_outline.md` was based on that eval data and has been retracted; do not cite it for Acme facts.
