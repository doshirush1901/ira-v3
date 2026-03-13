# Email workflow audit — deeper, human, contextual (no hallucinations)

**Purpose:** Improve the lead email workflow so every email feels **deeper** (richer context, real memory), **more human** (warm, curious, not templated), and **fully contextual** (every claim traceable to a source). **Zero hallucination:** no invented prices, dates, news, or "you said" without evidence.

---

## 1. Current strengths

- **Vibe** is clearly defined (human, warm, curious; chat about industry, not sell).
- **Full agentic checklist** (§8) covers machine match, small talk, geopolitics, tooling, Industry 4.0, India resin, latest builds, past convos, specs+prices, joke, CTA.
- **Source discipline** in places: inquiry date only from form/CRM; machine specs from sales_playbook; "never say I saw on your site".
- **Rushabh voice** prompt: contractions, "I" not "we", no buzzwords, one CTA, summary in prose.
- **CRM logging** with LLM summary (after send + on reply) is specified.
- **Multi-recipient** and **case study + joke** rules reduce one-size-fits-all.

---

## 2. Gaps and improvements

| Area | Gaps | Improvements |
|------|------|---------------|
| **Deeper** | Relationship memory not in draft; no "one thing from their last reply"; episodic memory missing; "something new" can be vague. | Pre-draft bundle: logic tree + **one snippet from their last reply** + check_relationship + recall_memory. "Something new" must name **one real reference** (case study / Atlas). |
| **Human** | Questions can be generic; opener can repeat; joke can repeat. | At least one question **specific to the lead**; vary opener; never use the same joke two leads in a row; mix sentence length. |
| **Contextual** | Prices/dates/references can be unsourced. | Verification gates: every price/lead time → playbook/quote/Plutus; every "latest"/customer → Atlas/case_studies; every "you said" → logic tree/thread; every news hook → real search result. |
| **No hallucinations** | LLM can invent numbers or quotes. | Explicit gates: no number without source; no "you said" without snippet; no news without search; no generic reference without concrete example. |

---

## 2b. Gaps and risks (detail)

### 2b.1 Depth — context not fully used

| Gap | Risk | Improvement |
|-----|------|-------------|
| **Relationship memory** (warmth, interaction count, preferences) is not auto-injected into draft context. | Emails feel generic; we don’t adapt to “first touch” vs “third touch” or known preferences. | **Always** pass `check_relationship` output into draft context (or enriched draft script). In workflow: "Before draft, call check_relationship for contact; include warmth + interaction count in context so tone and length can adapt." |
| **One specific thing from their last reply** is optional. | We reference "when you got in touch" but not "you’d said you’d check with management" or "you were waiting on capex approval." | **Mandate:** From logic tree, extract **one exact phrase or fact from their last reply** (or last significant message). Include in draft context: "Their last reply: [snippet]. Use it once in the email (e.g. 'You’d said you’d revert after [X] — no rush')." |
| **Episodic / narrative memory** not in draft path. | We lose "how this relationship evolved" — first quote, then meeting, then pause. | Where available, pass episodic summary (e.g. from Mem0 or pipeline) into draft: "Relationship narrative: [2–3 sentences]. Use to sound like we remember the journey." |
| **"Something new about us"** can be vague. | "We’ve been doing more in [segment]" without a **named** reference can sound like fluff. | **Rule:** "Something new" must name **one** real reference (case study, machine, region) from **case_studies index or Atlas**. No generic "we’ve been busy in your segment" without a concrete example. |

### 2b.2 Human — avoiding templated feel

| Gap | Risk | Improvement |
|-----|------|-------------|
| **Curious questions** are listed but can be generic. | "What parts? Volumes?" can feel like a form. | **Rule:** At least one question must be **specific to them** (from website scrape, industry, or their inquiry). E.g. "Are you looking at dashboards and trim for the same line, or a new line?" instead of only "What parts do you form?" |
| **Opening line** can default to a pattern. | "How are things on your side?" every time feels samey. | **Vary:** Alternate "How are things…", "Hope [region/industry]’s been kind to you", "Quick note — …", or a direct reference to their last message. In lead guide: add 3–4 opener patterns and pick by touch count / region. |
| **Joke** is chosen from a list. | Same joke type for same industry can repeat. | Already "vary every time"; add: **never use the same joke two leads in a row**; if same industry, pick a different line from the list or a slight twist. |
| **Sentence rhythm** | All medium-length sentences feel flat. | In voice prompt: "Mix one short punchy sentence with a longer one; use a single short line for emphasis (e.g. 'No pressure.')" |

### 2b.3 Contextual — every claim traceable

| Gap | Risk | Improvement |
|-----|------|-------------|
| **Price / lead time** stated without explicit source. | LLM can pull from training or guess. | **Verification gate:** Before send, every **price** and **lead time** in the email must have a **stated source** in the draft metadata: sales_playbook, quote PDF (with path), or Plutus. If none, use "indicative — happy to send formal quote" and do not state a number. |
| **Inquiry date/year** | enriched_leads.json is wrong sometimes. | Already "only if verified from form/CRM". Strengthen: "If the only source is enriched_leads.json, do **not** state the date; use 'when you got in touch about [X]' or 'when you filled out our form'." |
| **"Latest" / "current production"** | Old references presented as current. | Already "Ask Atlas for current projects". Add: "Any phrase like 'we just shipped', 'currently in production', 'latest installation' must be backed by **Atlas** or a **dated** case study. If unsure, say 'we’ve had installations in [region]' without implying recency." |
| **News hook** | Invented or outdated headline. | **Rule:** News hook must come from **NewsData.io / Iris / web search** run for this lead (sector + geography). Store the **exact headline or one-sentence summary** in draft metadata. If no result, use neutral opener; **never** invent a headline. |
| **"You said" / "you’d asked"** | Hallucinated quote. | **Rule:** Any "you said", "you’d mentioned", "you were looking for" must be traceable to **logic tree or thread**. In draft context, attach the snippet; if no snippet exists, do not attribute a quote to them. |

### 2b.4 No hallucinations — explicit gates

| Gate | How to enforce |
|------|----------------|
| **Numbers** | Draft metadata or checklist: "List every number in this email (price, lead time, forming area, cycle time). For each, source: [playbook / quote path / Atlas / none]." If "none", remove number or mark "indicative, formal quote to follow." |
| **References** | Every customer name, machine model, or "recent" claim: source = case_studies index or Atlas. No "we have customers in X" without checking case_studies/CRM by country. |
| **Their words** | Every "you said" / "you’d asked": source = logic tree or thread snippet. Otherwise rephrase to "when you got in touch about…" without quoting. |
| **News** | Every news hook: source = search result (headline + date or "recent"). If no search was run, no news hook. |
| **Company/lead details** | Website scrape or enriched_leads only. No invented company description or product. |

---

## 3. Workflow additions (integrated)

The following are **integrated** into `outgoing_marketing_email_workflow.md`. Use them when drafting.

### 3.1 Pre-draft context bundle (mandatory)

Before calling Calliope or the draft API, assemble and pass:

1. **Logic tree + recap** (from `pull_contact_email_history.py`).
2. **One snippet from their last reply** (from logic tree) — for one genuine "you said" moment.
3. **check_relationship** output (warmth, interaction count) — for tone/length.
4. **recall_memory** for this contact (Mem0) — for narrative/episodic flavour.
5. **Draft metadata template:** fields for [inquiry_date_source], [price_source], [lead_time_source], [news_hook_source], [reference_source]. Fill during draft; use in verification step.

### 3.2 Verification step (before send)

**Integrated in workflow §9.** Before send, confirm:

- [ ] **Source check:** Every price/lead time has a source (playbook, quote, Plutus); if not, removed or marked indicative.
- [ ] **Reference check:** Every "latest"/"current"/customer name traceable to Atlas or case_studies.
- [ ] **Quote check:** Every "you said" / "you’d asked" traceable to logic tree/thread; otherwise rephrased.
- [ ] **News check:** Any news hook has a real search result (headline/summary in metadata); if not, use neutral opener.

### 3.3 Deeper-human tweaks (integrated in workflow)

- **§3.6:** At least one question must be **specific to this lead** (from their inquiry, industry, or website), not only generic.
- **§3.4:** "Something new about us" must name **one** real reference (case study, machine, region) from case_studies or Atlas.
- **§3.1:** If no news search was run or no result found, use a neutral opener; **never** invent a headline or trend.
- **§3.2:** If inquiry date has no source other than enriched_leads.json, do not state the date; use "when you got in touch about [X]" or "when you filled out our form".
- **§3.8 (Voice):** Use "you said" / callback to **their** words only when we have a snippet from the logic tree; otherwise "when you got in touch about…".

---

## 4. Summary

| Dimension | Change |
|-----------|--------|
| **Deeper** | Mandate relationship + one "their last reply" snippet + episodic flavour in context; "something new" must name a real reference. |
| **Human** | One question specific to the lead; vary opener; mix sentence length; one callback to their words when we have evidence. |
| **Contextual** | Every number/reference/quote/news has a stated source; verification step before send. |
| **No hallucinations** | Explicit gates: numbers → playbook/quote/Plutus; references → Atlas/case_studies; "you said" → logic tree/thread; news → search result. |

Integrate the **pre-draft context bundle** and **verification step** into the main workflow (§3, §9) and reference this audit in the workflow doc for "deeper, human, contextual, no hallucinations".

**Practical takeaway:** The workflow now encodes a **pre-draft context bundle** (so drafts use relationship + one "their words" snippet + memory), **source rules** (so we don't invent dates, news, or references), and a **verification step** before send (so every number, reference, quote, and news hook has a clear source — no hallucinations). The full reasoning and extra suggestions are in this audit.
