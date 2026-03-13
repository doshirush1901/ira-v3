# Lead email drafting learnings — Eduardo / Forma 3D case (reference for sales agents)

This document captures how we drafted and sent the re-engagement email to Eduardo Pinto (Forma 3D, Portugal). Use it as the **reference pattern** for warm, data-driven, engagement-focused lead emails. Sales agents (Hermes, Calliope, Prometheus), draft scripts, and the workflow should follow this approach.

---

## 1. End-to-end process we followed

1. **Pull past conversations** — `pull_contact_email_history.py` for pinto@forma3d.pt → logic tree, recap, store in memory.
2. **Download PDFs from emails** — `download_email_attachments.py` for that contact → saved quote PDFs (ATF, PF1-X-1311, FCS-6070-3S) under `downloaded_from_emails/forma3d_eduardo/`.
3. **Extract specs and prices from PDFs** — Same script with `--analyze`; read the **actual quote PDFs** (not brochure) to get exact numbers. Insert only the **machines we quoted them** (e.g. ATF1212, PF1-X-1311, FCS-6070-3S), not every machine from a brochure.
4. **Scrape their website** — Understand what they do (thermoforming, sectors, projects). Forma 3D: logistics, transport, agricultural, **wine (Vinumpro)**. Use this to personalise; do **not** say "I saw on your site" or reveal the source.
5. **Pick relevant news** — Check their **sector** and **geography**. Then pick news that fits: e.g. Portugal plastics sector (recycled capacity, decarbonisation), and **geopolitics** (energy costs, raw materials, oil) that may affect European manufacturers. Ask how it’s been on their side; does any of that affect their plans or timing?
6. **Congratulate and ask questions** — Congratulate them on specific initiatives (e.g. Vinumpro) without revealing where we learned it. Ask: how’s the market going, what are the challenges, is there anything on the equipment/capacity side we could help with to grow that part of the business?
7. **MBB-style structure** — Section labels (WHERE WE LEFT OFF —, LATEST QUOTE WE SENT YOU —), short recap in prose, quote block with real specs/prices from PDFs, one clear CTA. Warm, human, no robotic or process-y openers.
8. **Plain text, no HTML** — Send as plain text. Bullets with •, no pipe tables, no HTML.
9. **Reply in thread** — When re-engaging an existing contact, **reply in the same Gmail thread** (use `thread_id` from email search) so the conversation stays together and engagement is higher. Subject stays "Re: ..." of the last thread.

---

## 2. Principles (teach the sales agent)

**Industry-specific (important):** Be **industry-specific** throughout the email. News hook, references, and proof should match the lead's segment — e.g. France sanitary/bathtub market for PR3 PRETI (Bath Fournitures, Kinedo, Jaguar/Mirsant refs); Portugal plastics + wine for Forma 3D; Turkey automotive for SAFARI. Generic plastics or energy news is weaker than sector-specific news and same-industry references. *Learned from Eric Vidal (Lead 4): the email was too short and generic until we made it industry-specific.*

| Principle | Do | Don’t |
|-----------|----|-------|
| **News hook** | Check their website first → understand what they do → pick news **relevant to their sector** (e.g. Portugal plastics, wine). Add **geopolitics** (energy, raw materials, oil) and ask if it affects them. | Use generic or irrelevant news (e.g. packaging labelling rules when they’re thermoformers with wine/industrial focus). |
| **Personalisation** | Scrape or research their site: sectors, projects (e.g. Vinumpro). Congratulate and ask questions (market, challenges, how we can help). | Say "I saw on your site" or "I read on your website" — never reveal the source. |
| **Quote block** | Use **only the machines we actually quoted them**. Pull prices and key specs from the **quote PDFs** we sent (download from Gmail, extract with script). When re-engaging after a long gap, **offer the machine again in the email** with **tech specs and revised price** (model, EXW price, forming area, sheet thickness, loading, frames, tool clamping/loading, heater, tables, lead time) — don’t only say “happy to resend the offer”. *Learned from Zakaria (Lead 6):* we included PF1-C-2012 at 65,000 USD with full spec bullets; the offer is in the email so they can act without waiting for an attachment. | List every machine from a brochure or "as per our November quote" without real numbers. Vague “I can send the quote” with no specs or price in the body. |
| **Machine specs — verify** | **Always check authoritative source** (sales_playbook, quote PDF, Plutus) before stating table/heater type. **PF1-C max forming area = 2×3 m;** for larger sizes we offer **PF1-X** (servo). **PF1-C series = pneumatic table movements** (upper/lower table pneumatic); **PF1-X series = servo** (universal frames and autoloader optional). Sales_playbook: Config A = pneumatic; servo is an upgrade (+cost). Never assume servo for PF1-C. *Correction (Zakaria email):* we wrongly stated “electric servo driven” for PF1-C-2012 tables; corrected to pneumatic. | Assume or copy table type from the lead’s inquiry form; the form may show what they *want*, not what the quoted model (e.g. PF1-C) actually has. |
| **Tone** | Warm, human, one clear CTA. MBB-style sections and spacing. Rushabh voice ("I", short paragraphs, no buzzwords). | Process-y openers ("I wanted to touch base"), long bullet dumps, multiple CTAs, robotic tone. |
| **Currency** | **Check lead's website** for location. **If India → quote in INR** (e.g. ₹1.08 Crore EXW). If Europe/other → EUR or USD. *Learned from Vignesh (Lead 7):* Flexsol is India (Gurgaon); we quote in INR for Indian customers. | Quote in EUR/USD when the lead is clearly Indian (e.g. .in domain, India in company name). |
| **Send** | Plain text. Reply in thread when re-engaging. From rushabh@machinecraft.org. | HTML. New thread when a reply exists. |

---

## 3. Reference files (Eduardo case)

- **TO_SEND (final):** `data/imports/24_WebSite_Leads/email_lead3_eduardo_pinto_TO_SEND.md`
- **Contact history:** `data/imports/24_WebSite_Leads/eduardo_forma3d_email_history.md`
- **Quote PDFs:** `data/imports/downloaded_from_emails/forma3d_eduardo/` (PF1-X-1311_Quote_EUR.pdf, Quotation__Machinecraft_FCS_6070-3S_V1.pdf, ATF-Brochure.pdf, etc.)
- **Workflow:** `data/knowledge/outgoing_marketing_email_workflow.md`, `data/knowledge/data_pulling_from_email_past_conversations.md`
- **Voice/format:** `prompts/email_rushabh_voice_brand.txt`, `prompts/email_final_format_style.txt`

---

## 4. Scripts and API

- Pull emails + logic tree: `scripts/pull_contact_email_history.py`
- Download PDFs + extract + insert quote block: `scripts/download_email_attachments.py` (--analyze --to-send)
- Draft with memory + history + news hook + quote block: `scripts/draft_lead_email_enriched.py` (--news-hook, --quote-block, --long-warm)
- Send: `POST /api/email/send` with to, subject, body (plain text), optional thread_id for reply-in-thread. Get thread_id via `POST /api/email/search`.

---

## 5. For agents

When drafting a lead re-engagement email:

- **Hermes / Calliope:** Use this learning set. Pull history, get quote data from PDFs (or script), scrape or research the lead’s website to understand their business and recent initiatives, pick sector- and geography-relevant news plus a geopolitics angle, congratulate and ask questions without revealing source, structure with MBB-style labels and real quote numbers, plain text, one CTA.
- **Artemis:** When running the data-pulling workflow, ensure the quote block inserted into the TO_SEND uses only the machines we quoted that contact (from their quote PDFs), not brochure content.
- **Iris:** When asked for a news hook, search for the lead’s **country + sector** (e.g. Portugal plastics, Turkey automotive) and optionally broader geopolitics (energy, raw materials) so the opener is relevant.

This way of emailing — **industry-specific** (news, references, and content matched to their segment), website-informed, sector-relevant news, geopolitics question, congratulate and ask how we can help, real quote block, MBB-style, plain text, reply in thread — is the **learned standard** for sales lead emails.

**Learned from Eric Vidal (Lead 4):** The email was too short and generic until we made it **industry-specific**: France sanitary sector news (Bath Fournitures/Allibert, Kinedo, bathtub market), and a full "what we're doing in sanitary" block with same-industry references (Jaguar, Mirsant, Middle East, India bathtub clients). Being industry-specific makes the email credible and worth reading.

---

## 6. Learned from Lead 7 (Vignesh Kumar / Flexsol, India) — sales training reference

These learnings went into the final Lead 7 email draft. **Use them for all future lead re-engagement emails** and for sales training (Chiron, Hermes, Nemesis).

| Learning | Rule / Do | Don't |
|----------|-----------|--------|
| **Match machine to inquiry size** | Lead stated 1×1.5 m (1000×1500 mm) → offer **PF1-C-1015** (that size). Get specs from model sheet / sales_playbook. State forming area and sheet range (e.g. 2–6 mm) clearly. | Offer a larger standard size (e.g. PF1-1515) when they asked for 1×1.5 m; omit sheet thickness range. |
| **PF1-C = cut sheet only** | **PF1-C** = cut-sheet manual feeding (light guard). **Roll feeder** is only on **PF1-R** and **ATF**, for **0.2–1.5 mm sheet max**. For 2–6 mm → PF1-C cut sheet. If they asked for roll feeder but need 2–6 mm, explain and offer PF1-C; mention PF1-R/ATF only if they need thin-sheet roll feed. | Offer "PF1-C with roll feeder" or roll feeder on PF1-C. |
| **India → INR** | Check lead website / location. **If India → quote in INR** (e.g. ₹55 Lakhs EXW). | Quote in EUR/USD for Indian leads (.in, India in company name). |
| **Ice-breaker link** | Use **one link** that connects **their industry** to **their ask** (thermoforming). E.g. India telecom + thermoforming → PLI for non-electronic telecom components (plastic enclosures). Makes the opener relevant and credible. | Generic or unrelated news; no link; or link that doesn't tie industry to machine inquiry. |
| **Ask inquiry status** | When re-engaging after a **long gap**, ask explicitly: **Is this inquiry still active?** **Did you already purchase a machine elsewhere?** We'd appreciate knowing so we can update our side and still help (e.g. tooling, future capacity). Repeat the ask at the end (e.g. "if you've already bought elsewhere, do let us know"). | Assume the lead is still in market; skip asking if they bought elsewhere. |
| **Price and specs from authority** | Use **sales_playbook** or model sheet for machine name, forming area, sheet range, table type. Use **user-specified price** when given (e.g. 55 Lakhs INR). Lead time (e.g. 5 months from PO) and formal quote on spec lock. | Invent price or specs; state servo for PF1-C; state roll feeder for PF1-C. |
| **Reply in thread, plain text** | Reply in same Gmail thread (thread_id from email search). Plain text, bullets (•), MBB-style sections (WHERE WE LEFT OFF —, WHAT YOU ASKED FOR —), one CTA. From rushabh@machinecraft.org. | New thread; HTML; pipe tables; multiple CTAs. |

**Reference:** `data/imports/24_WebSite_Leads/email_lead7_vignesh_flexsol_TO_SEND.md`, `lead7_vignesh_srk_tele_contact_context.md`. **Sales playbook:** PF1-C-1015 in table; PF1-C = pneumatic + cut sheet only; roll feeder = PF1-R/ATF 0.2–1.5 mm. **Workflow:** `outgoing_marketing_email_workflow.md` sections 3.1 (ice-breaker, India INR), 3.3 (machine specs, inquiry status).

---

## 7. India PF1-X inquiries — dual option (PF1-C vs PF1-X) with comparison table

When an **Indian client** asks for a **PF1-X type** machine (servo, automatic loading, or similar), do **not** offer only the PF1-X. Always offer **two options** in the same email:

1. **PF1-X** (servo) — indicative price in INR, full specs.
2. **PF1-C** (same forming size, pneumatic, economic) — indicative price in INR, full specs.

Present them in a **comparison table** in the email body so the client can see specs and prices side by side. Exception to "no pipe tables": for this India two-option comparison, **use one clear table** with columns for each option and rows for: forming area, max depth, sheet thickness, table movement (pneumatic vs servo), loading, heater, **price (EXW INR)**, lead time. Example structure:

```
  Spec              | PF1-C (economic)      | PF1-X (servo)
  Forming area      | 1000×1500 mm          | 1000×1500 mm
  Table movement    | Pneumatic             | Full servo
  Sheet             | 2–6 mm cut sheet      | 2–10 mm cut sheet
  Price (EXW)       | ₹55 Lakhs             | ₹XX Lakhs
  Lead time         | 5 months              | 5–6 months
```

Get prices from **sales_playbook** (PF1-C) and playbook/Plutus for PF1-X same size. Keep PF1-X within ~20% of any prior quote we sent this contact. Tell the client there are **two options** and that the table shows the comparison so they can choose.
