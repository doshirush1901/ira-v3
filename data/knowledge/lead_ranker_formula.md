# Lead Ranker Formula

A single **lead score (0–100)** ranks deals/leads by how "hot" they are: order size, engagement (emails exchanged), pipeline stage, existing-customer status, and whether there was a meeting or web call.

**Reference example:** NAFFCO KSA, PF1-X-5028 — proposal (quote) sent, they replied, followed through with web call, and they are an existing customer → score should be high.

---

## Score Components (total = 100)

| Component | Max points | How it's measured |
|-----------|------------|------------------|
| **Order size** | 20 | Deal/quote value (USD equivalent). Log-scale bands. |
| **Interest (emails)** | 20 | Genuine replies from the lead (or total emails exchanged). |
| **Stage** | 40 | Pipeline stage: NEW → CONTACTED → … → PROPOSAL → NEGOTIATION → WON. |
| **Existing customer** | 10 | Contact type = LIVE_CUSTOMER or PAST_CUSTOMER. |
| **Meeting / web call** | 10 | At least one CRM interaction with channel MEETING or WEB. |

---

## 1. Order size (0–20)

Deal/quote value in USD (or converted). Unknown or zero = 0.

| Value (USD) | Points |
|-------------|--------|
| 0 / unknown | 0 |
| 1 – 49,999 | 5 |
| 50,000 – 99,999 | 8 |
| 100,000 – 249,999 | 12 |
| 250,000 – 999,999 | 16 |
| 1,000,000+ | 20 |

---

## 2. Interest — emails exchanged (0–20)

**Genuine replies** = non–auto-reply emails we received from the lead. If not available, use total **emails from them** or outbound+inbound count from CRM.

| Genuine replies (or equiv.) | Points |
|-----------------------------|--------|
| 0 | 0 |
| 1 – 5 | 5 |
| 6 – 15 | 10 |
| 16 – 30 | 14 |
| 31 – 50 | 17 |
| 50+ | 20 |

---

## 3. Stage (0–40)

Pipeline stage of the **deal** (or lead’s best deal).

| Stage | Points |
|-------|--------|
| NEW | 0 |
| CONTACTED | 5 |
| ENGAGED | 10 |
| QUALIFIED | 15 |
| PROPOSAL | 25 |
| NEGOTIATION | 35 |
| WON | 40 |
| LOST | 0 |

*PROPOSAL* = quote/proposal sent; *NEGOTIATION* = deep in (e.g. web call, back-and-forth).

---

## 4. Existing customer (0–10)

- **LIVE_CUSTOMER** or **PAST_CUSTOMER** → **10 points**
- Lead-only (LEAD_WITH_INTERACTIONS, LEAD_NO_INTERACTIONS) → **0**

---

## 5. Meeting / web call (0–10)

- At least one interaction for this contact (or deal) with **channel = MEETING** or **channel = WEB** → **10 points**
- Otherwise → **0**

---

## Final score

- **Total** = order_size_pts + interest_pts + stage_pts + existing_customer_pts + meeting_pts  
- **Capped at 100** (if raw total > 100, score = 100).

Leads are ranked by this score descending (e.g. NAFFCO KSA with proposal + reply + web call + existing customer should land near the top).

---

## Data sources

- **Order size:** `deals.value`, `deals.currency` (convert to USD when needed).
- **Stage:** `deals.stage`.
- **Existing customer:** `contacts.contact_type`.
- **Meeting/web call:** `interactions.channel` in (MEETING, WEB) for the contact or deal.
- **Interest:** Email search (genuine_replies) or CRM interaction counts (inbound + outbound).

**Confidence:** high  
**Freshness:** current  
**Sources:** CRM schema (`crm.py`), `DealStage`/`ContactType`/`Channel` in `models.py`, lead scoring requirements.
