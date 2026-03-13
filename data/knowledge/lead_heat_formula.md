# Lead heat formula — how we score “hotness”

Use this to prioritise leads, decide who gets the next touch, and which contacts to treat as hot in CRM and drafting.

---

## 1. Formula (score 0–10)

**Heat score = Engagement + Value + Export**

| Factor | What to check | Points (max) | How to score |
|--------|----------------|--------------|--------------|
| **Engagement** | Did we send a proposal/quote and did they reply? | 0–4 | See §2 below. |
| **Value** | Order / RFQ value (deal size, multi-machine, strategic) | 0–3 | See §3 below. |
| **Export** | Export-oriented customer (sells abroad, international ops) | 0–3 | See §4 below. |

**Total = 0–10.** Treat **7+** as hot, **4–6** as warm, **0–3** as cold for prioritisation.

---

## 2. Engagement (0–4 points)

| Signal | Points | Example |
|--------|--------|--------|
| We sent quote/proposal **and** they replied (any reply) | +2 | Naffco, Forma 3D (Eduardo) |
| They said they’d “get back” / “decide by X” / “review internally” | +1 | “Will get back by end of week” |
| Multiple back-and-forth (≥3 substantive exchanges) | +1 | Long thread with specs, questions, our answers |
| We sent but **no** reply yet | 0 | One-way outbound only |
| **Was hot, now no reply** (frozen) | 0 | They used to reply but have stopped; treat as cold until they respond again (e.g. nick.mcnamara@geminimade.com, Gemini Made). |

**Max 4.** If no proposal sent yet, engagement = 0. **Frozen = was hot, stopped replying** → set Engagement to 0 for prioritisation; re-score when they reply again.

---

## 3. Value (0–3 points)

| Signal | Points | Example |
|--------|--------|--------|
| High-value RFQ (large machine, multi-machine, or known big deal) | +2 | PF1-X large format, multi-unit, €200K+ type deal |
| Medium value (single mid-size machine, clear budget) | +1 | Single PF1-C / PF1-X, quoted in playbook range; **~40K USD** type deal (e.g. Stream Techno, virkhov@streamtechno.org) |
| Low / unknown value | 0 | Small machine, or value not yet known |

Use **quote value, RFQ description, or deal size** when known (Plutus, quote PDFs, CRM deal value). **A lead can still be hot (7+) with moderate order value** (e.g. 40K USD) when engagement and/or export score well — value is one factor, not a gate. **When value is unknown** (e.g. Abhishek, abhishekpkn@gmail.com): use Value = 0; if Engagement + Export ≥ 7, still treat as hot. Re-score Value once quote/deal size is known.

---

## 4. Export orientation (0–3 points)

| Signal | Points | Example |
|--------|--------|--------|
| Clearly export-focused (international sales, export market) | +2 | Sells to EU, MENA, or multiple countries |
| Regional / domestic with some export | +1 | Domestic first but some export or OEM |
| Purely domestic / unknown | 0 | No signal of export |

Use **website, geography, and “who they sell to”** (from research or contact context).

---

## 5. How to use it

- **Prioritisation:** Sort leads by heat score; work 7+ first, then 4–6, then 0–3.
- **Drafting:** When drafting emails, pull contact context for 7+ and 4–6; mention value/export in internal notes so tone and urgency match.
- **CRM:** Today heat in the dashboard = outbound + inbound (engagement only). When we add value and export to CRM (e.g. deal value, “export” flag), the same formula can power a single heat score in the UI.
- **Contact context:** In `24_WebSite_Leads/*_contact_context.md`, state “High-value RFQ”, “Export-oriented”, or “Proposal sent + reply” so the formula can be applied from context when we don’t have structured fields.

---

## 6. Quick reference

```
Heat = Engagement (0–4) + Value (0–3) + Export (0–3)  →  max 10

  Hot:   7–10   →  prioritise, full context, treat as “hottest” leads
  Warm:  4–6    →  next in queue, good for re-engagement
  Cold:  0–3    →  lower priority or nurture only
```

**Source of truth for “is this lead hot?”:** This formula. When in doubt, score the three factors and sum.
