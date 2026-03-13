# Lead engagement email drafting (skill)

How we draft **contextual, evidence-based** outreach to leads (cold or warm re-engagement). **Vibe:** Human, warm, curious — here to chat about the industry, not to sell; small talk, industry talk, curious questions, reference past convos/quotes, tech specs + prices by region, funny last line, CTA web call next week. **Full agentic workflow:** see **outgoing_marketing_email_workflow.md** §8. **Primary reference:** Eduardo / Forma 3D — see **`data/knowledge/lead_email_drafting_learnings_eduardo_case.md`** for the full learning set (website scrape, **industry-specific** news + content, sector news + geopolitics, congratulate without revealing source, quote block from PDFs, MBB-style, plain text, reply in thread). Vladimir (Komplektant), Eric Vidal (PR3 PRETI France, sanitary), and Vignesh (Lead 7, Flexsol India) are further examples. Lead 7 learnings (machine match, PF1-C cut sheet, inquiry status, ice-breaker link, India INR) are in Section 6 of the learnings doc.

**Important:** Be **industry-specific** — news hook, references, and proof should match the lead's segment (e.g. sanitary → France sanitary news + Jaguar/Mirsant/Bathline; automotive → Turkey/EU refs; India telecom → PLI for plastic enclosures + thermoforming link; pallets/wine → Portugal plastics + Vinumpro). Generic content weakens engagement.

**Offer in the email:** When re-engaging, **offer the machine again with tech specs and revised price** in the body — model name, price (EXW), key specs (forming area, sheet thickness, loading, frames, tool clamping/loading, heater, tables), and lead time. Don’t rely on “happy to send the quote” alone; put the offer in the email so they can act without waiting for an attachment. *Learned from Zakaria (Lead 6):* PF1-C-2012 at 65,000 USD with full spec bullets. *Learned from Vignesh (Lead 7):* PF1-C-1015 at ₹55 Lakhs, 1×1.5 m, 2–6 mm, cut sheet — match machine to inquiry size; India → INR.

**Machine specs — always verify:** Check **sales_playbook** (or quote/Plutus) before stating table type. **PF1-C max forming area = 2×3 m;** for larger sizes we offer **PF1-X** (servo). **PF1-C = pneumatic tables + cut-sheet manual feeding only.** **PF1-X = servo;** on PF1-X, **universal frames and autoloader are optional.** **Roll feeder = PF1-R and ATF only** (0.2–1.5 mm sheet max); never offer "PF1-C with roll feeder". *Lead 7 (Vignesh):* offered PF1-C cut sheet; explained PF1-R/ATF for thin-sheet roll feed only. Do not use the lead’s inquiry-form choices as the machine spec — the form may show what they want; the quoted model (e.g. PF1-C at $65k) has fixed specs. *Correction:* We wrongly stated “electric servo” for PF1-C-2012 in the Zakaria email; corrected to pneumatic.

**Inquiry status (re-engagement after long gap):** Ask: Is this inquiry still active? Did you already purchase a machine elsewhere? We'd appreciate knowing so we can update our side and still help. *Lead 7 (Vignesh).*

**Ice-breaker:** Use a **link** that connects their **industry** to their **ask** (thermoforming), e.g. India telecom → PLI for non-electronic components (plastic enclosures). *Lead 7 (Vignesh).*

**India + PF1-X type spec — give two options with comparison table:** When an **Indian client** asks for a **PF1-X type** machine (servo, etc.), always offer **two options**: (1) **PF1-X** (servo, indicative price in INR) and (2) **PF1-C** (same forming size, pneumatic, lower price in INR). Present both in a **single comparison table** in the email body with columns for each option and rows for key specs and price (forming area, table movement, loading, price EXW INR, lead time) so they can compare side by side. This is the allowed exception to "no pipe tables" — use one clear comparison table for the two options. See Section 7 in `lead_email_drafting_learnings_eduardo_case.md` and **India PF1 dual-option** in `sales_playbook.md`.

## When to use

- Lead came from website/PF1 form; we sent a generic intro and got no reply.
- We want a **second touch** that is concrete and valuable so they reply.
- We have (or can find) **documents** that match their interest (e.g. sanitary-ware, bathtub, same machine size).

## Steps (taught flow)

0. **Pull past convos + logic tree + memory (always first for any CRM/lead)**  
   Run `scripts/pull_contact_email_history.py --email <lead_email> --output <path>.md --store-memory` (Ira API running). Pulls all emails with the contact, builds interaction logic tree (timeline, proposals sent, their feedback), stores in memory. Review logic tree before drafting; do not repeat what we already sent. See workflow Section 3.0 (pull past convos, logic tree, store memory, then draft).

0b. **Check lead website for what they do and location.** If India (e.g. .in domain, company in India) → quote in INR in the email. If Europe/other → EUR or USD. *Vignesh (Lead 7):* Flexsol is India (Gurgaon) → we quoted ₹55 Lakhs EXW (PF1-C-1015). Match machine to their stated forming area (e.g. 1×1.5 m → PF1-C-1015).

1. **Find relevant documents**
   - Use Alexandros-style search (hybrid_search on imports) with query combining: application (bath, sanitary, bathtub), machine (PF1, forming area), and any known customer/project names (e.g. Mirsant, Jaguar, RMbathroom).
   - Fallback: use a curated list of known PDFs for that segment if index is empty.

2. **Extract text from top N PDFs**
   - Read and extract text from the top 3–5 files (cap ~10k chars per file to avoid token blow-up).
   - Skip files with too little extractable text.

3. **LLM: extract insights**
   - One LLM call: from the combined doc snippets, extract **specs** (forming area, draw, cycle time), **customer/project names**, **process differentiators**, and **quotable details**.
   - Output: concise bullet list for use in the email.

4. **LLM: generate final email**
   - Inputs: (a) a **draft body** (re-engagement template or prior draft), (b) the **extracted insights**.
   - System prompt: Calliope / Rushabh voice; weave in 1–3 concrete details from insights; keep spec summary, indicative budget if applicable, references (e.g. Jaguar PF1-3030, Mirsant PF1-2116), one clear CTA (e.g. 15–20 min video call).
   - Use `prompts/email_rushabh_voice_brand.txt` for voice and `prompts/email_final_format_style.txt` for final layout: organised, MBB-style, data-driven from past interactions, spacing and section labels (e.g. "WHERE WE LEFT OFF —"), scannable bullets, no pipe tables. Personality like Rushabh; professional, not bot-like.
   - **Use all relevant data:** Before drafting, pull past convos (`pull_contact_email_history.py --store-memory`), then either (a) pass the history file + recalled memory in context, or (b) run `scripts/draft_lead_email_enriched.py` (calls `GET /api/memory/recall` and injects contact history + format/voice instructions into `POST /api/email/draft`). See `data/knowledge/outgoing_marketing_email_workflow.md` sections 5b and 5d.

5. **Optional: Rushabh-voice pass**
   - If the final email was generated without the voice prompt, run a rewrite pass using `prompts/email_rushabh_voice_brand.txt` so tone and packaging match.

6. **CRM and send**
   - Send from rushabh@machinecraft.org (or create Gmail draft for human send).
   - **After send:** Add or update contact and deal in CRM; log the outbound email as an interaction with channel=EMAIL, direction=OUTBOUND, subject, **sent_at** (when sent), and **LLM summary of what the email was about** (1–2 sentences in content/metadata). See **outgoing_marketing_email_workflow.md** §4b.
   - **When client replies:** Log the reply in CRM (direction=INBOUND) with **LLM summary of the client's reply** as metadata. See §4b.

## Reference implementation

- **Script:** `scripts/vladimir_email_from_imports.py` — Alexandros-style search → PDF extract → LLM insights → LLM final. Writes to `data/imports/24_WebSite_Leads/email_vladimir_kilunin_FINAL.md`.
- **Rushabh voice rewrite:** `scripts/rewrite_email_rushabh_voice.py` + `prompts/email_rushabh_voice_brand.txt`.
- **Send:** `scripts/send_vladimir_email.py` (body from `email_vladimir_kilunin_FINAL_RUSHABH_VOICE.md`).
- **CRM entry:** `scripts/add_vladimir_crm_entry.py` — contact Vladimir Kilunin, company Komplektant, deal PF1-X-2012 inquiry, interaction “Engagement email sent 2026-03-09”.

## Agents that should use this skill

- **Hermes:** When designing re-engagement or drip steps that need **document-backed** personalisation (e.g. “draft email 2 for this lead using case studies”). Delegate document search to Alexandros (or use search_knowledge); then use draft_email with context that includes extracted insights and Rushabh voice rules.
- **Calliope:** When asked to “draft a re-engagement email with evidence from our docs” — follow the same flow: get insights from context or from a prior tool call (e.g. ask_agent alexandros/clio for doc snippets), then generate the email using `email_rushabh_voice_brand` and a clear CTA.

## Outcome (Vladimir example)

- **Sent:** 2026-03-09 from rushabh@machinecraft.org.
- **To:** kiluninv@gmail.com (Vladimir Kilunin, Komplektant). **CC:** sales@machinecraft.org.
- **Subject:** PF1-X-2012 Thermoforming for Komplektant — Sanitary-Ware Specs, Price & References.
- **Content:** Concrete specs, indicative budget EUR 280k–380k, references (Jaguar PF1-3030, Mirsant PF1-2116, RMbathroom KSA), Netherlands reference, single CTA (15–20 min video call Thu/Fri).

## Outcome (Ruslan example — second send, validated pattern)

- **Sent:** 2026-03-10 from rushabh@machinecraft.org.
- **To:** ruslan.didenko@safariotomotiv.com (Ruslan Didenko, SAFARI ARAÇ EKİPMANLARI, Turkey).
- **Subject:** Your PF1 2000×2000 inquiry — EU references, Dutch Tides, and a quick catch-up.
- **Content:** NewsData.io ice breaker (Turkey–Europe trade), inquiry 31 Oct 2022, 2000×2000 PF1 specs as bullets, ~150k USD / 5 months, EU refs (Netherlands, Dutch Tides, Sweden/UK/Belgium), “we don’t have a customer in Turkey yet”, Dutch Tides PF1-X-6520, NRC Russia two machines in production, application questions, CTA video call Thu/Fri.
- **Reference:** `data/imports/24_WebSite_Leads/email_lead2_ruslan_didenko_TO_SEND.md`, `scripts/send_ruslan_email.py`, `scripts/add_lead2_ruslan_crm_entry.py`. Learnings stored in long-term memory via `scripts/learn_from_ruslan_email.py`.

The flow (document-backed or workflow-based) is validated by **Vladimir, Ruslan, and Lead 7 (Vignesh/Flexsol)**. When drafting the next lead email, recall this pattern and the workflow in `data/knowledge/outgoing_marketing_email_workflow.md`. **Lead 7 learnings (sales training):** See **Section 6** in `data/knowledge/lead_email_drafting_learnings_eduardo_case.md` — match machine to inquiry size, PF1-C cut sheet only (no roll feeder), India → INR, ice-breaker link (industry + thermoforming), ask inquiry status / bought elsewhere.
