# Email workflow — n8n-style view and agent map

This doc shows the **complete email workflows** (inbound and outbound) in an n8n-style node flow, and **which agents are used when**.

---

## 1. Inbound email (inbox processing)

Trigger: unread emails in Gmail. Flow runs in **EmailProcessor** when OPERATIONAL mode processes inbox (or TRAINING mode observes).

```mermaid
flowchart LR
  subgraph trigger["⏱ Trigger"]
    T1[Gmail: unread messages]
  end
  subgraph fetch["Fetch"]
    N1[List unread]
    N2[Get full message]
  end
  subgraph analyze["Analyze"]
    N3[Parse to Email model]
    N4[Delphi: classify intent / urgency / suggested_agent]
    N5[DigestiveSystem: ingest_email]
    N6[SensorySystem: resolve_identity]
    N7[CRM: log interaction]
  end
  subgraph draft["Draft reply"]
    N8{Intent in REPLY_INTENTS?}
    N9[Pantheon agent: generate reply]
    N10[Create Gmail draft]
    N11[Mark as read]
  end

  T1 --> N1 --> N2 --> N3 --> N4 --> N5 --> N6 --> N7 --> N8
  N8 -->|yes| N9 --> N10 --> N11
  N8 -->|no| N11
```

| Node / step | What runs | Agent / system |
|-------------|-----------|----------------|
| List unread / Get full message | Gmail API | **EmailProcessor** (no agent) |
| Parse | `_parse_message()` | EmailProcessor |
| **Classify** | Intent, urgency, suggested_agent | **Delphi** |
| Digest | Entities, quotes, dates | **DigestiveSystem** (body system) |
| Resolve identity | Contact from CRM / cache | **SensorySystem** (body system) |
| Log interaction | CRM contact + interaction | **CRM** (EmailProcessor writes) |
| Generate reply | Draft reply body | **Pantheon agent** from classification (often **Calliope**, or Athena) |
| Create draft / Mark read | Gmail API | EmailProcessor |

**Agents used in inbound:** **Delphi** (classification), **Calliope** or other Pantheon agent (reply draft). Body systems: Digestive, Sensory.

---

## 2. Outbound lead email (full workflow)

Trigger: human or script starts “draft and send to lead”. Steps follow **outgoing_marketing_email_workflow.md** (§2a serial/parallel + score gate) and **lead_email_case_study_and_joke_guide.md**. **Serial:** Context → Research → Draft → Score gate → Pre-send → Send & log. **Parallel:** Within Research, website / news / machine+refs can run in parallel. **Score gate:** Score draft 0–10; if &lt; 8 redo, if 8–9 improve until ≥ 9; only if ≥ 9 allow send.

```mermaid
flowchart TB
  subgraph trigger["⏱ Trigger"]
    T2[User: draft email for lead / send to company]
  end
  subgraph context["1. Context (serial)"]
    O1[Pull contact email history]
    O2[Build logic tree + recap]
    O3[Pre-draft bundle: snippet + relationship + memory]
    O4[Optional: download attachments, quote summary]
  end
  subgraph research["2. Research (parallel ok)"]
    O5[Website: what they do, currency]
    O6[News: sector+geography or neutral]
    O7[Machine match + refs; Cadmus/Clio case study]
  end
  subgraph draft["3. Draft"]
    O8[Calliope: email body]
    O9[Voice/format → TO_SEND.md]
  end
  subgraph gate["4. Score gate"]
    O10[Score draft 0–10]
    O11{Score >= 9?}
    O12[Redo or improve draft]
  end
  subgraph presend["5. Pre-send"]
    O13[§9 Checklist + verification]
    O14[find_company_contacts → To + Cc up to 3]
  end
  subgraph send["6. Send & log"]
    O15[POST /api/email/send]
    O16[CRM: sent_at + LLM summary of email]
  end

  T2 --> O1 --> O2 --> O3
  O3 --> O4
  O3 --> O5
  O3 --> O6
  O3 --> O7
  O5 --> O8
  O6 --> O8
  O7 --> O8
  O4 --> O8
  O8 --> O9 --> O10 --> O11
  O11 -->|No| O12 --> O8
  O11 -->|Yes| O13 --> O14 --> O15 --> O16
```
(When the client replies, log that reply in CRM with **LLM summary of the reply** as metadata — see inbound flow and §4b in outgoing_marketing_email_workflow.)

| Node / step | What runs | Agent / system |
|-------------|-----------|----------------|
| Pull contact email history | `pull_contact_email_history.py` | **Gmail API** (EmailProcessor.search_emails, get_thread); no agent |
| Build logic tree / recap | Script + optional LLM | Script; optional **Calliope** or generic LLM for recap |
| Download attachments / quote summary | `download_email_attachments.py` | Script + Document AI / LLM (no pantheon agent) |
| recall_memory / check_relationship | MCP or API | **Mnemosyne** (memory), **RelationshipMemory** (body system) |
| Case study by industry+size | KB / case_studies index | **Cadmus** (case studies), **Clio** (KB search) or Alexandros (imports) |
| News hook / scrape | Iris, web search | **Iris** (external intel) |
| Production / refs | Atlas, CRM | **Atlas** (projects), **Plutus** (pricing when needed) |
| **Generate email body** | Draft with voice + format | **Calliope** |
| **Multi-recipient** | find_company_contacts.py → Gmail search | **Gmail API** (search); no agent |
| Send | POST /api/email/send | **EmailProcessor.send_message** (no agent) |
| **CRM log (after send)** | Contact, deal, interaction: subject, **sent_at**, **LLM summary of what email was about** (in content/metadata) | **CRM**; script or API; LLM for summary |
| **CRM log (on reply)** | Interaction INBOUND + **LLM summary of client's reply** in content/metadata | **EmailProcessor** (inbound) or sync; LLM for reply summary |

**Agents used in outbound:** **Calliope** (draft), **Cadmus** (case study pick), **Clio** / **Alexandros** (docs/KB), **Mnemosyne** (recall), **Iris** (news/scrape), **Atlas** (production refs), **Plutus** (pricing when in context). **Multi-recipient** is a script + Gmail search (no agent).

---

## 3. Agent summary — when each is used

| Agent | Inbound (inbox) | Outbound (lead email) |
|-------|-----------------|------------------------|
| **Delphi** | ✓ Classify incoming email (intent, urgency, suggested_agent) | — |
| **Calliope** | ✓ Draft reply (when intent = reply) | ✓ Draft full email body (voice, format) |
| **DigestiveSystem** | ✓ Ingest email (digest content) | — |
| **SensorySystem** | ✓ Resolve sender identity | — |
| **Mnemosyne** | — | ✓ recall_memory for contact context |
| **Cadmus** | — | ✓ Case study choice by industry/size |
| **Clio** | — | ✓ KB search for refs, playbook, case studies |
| **Alexandros** | — | ✓ Document/imports search (when used) |
| **Iris** | — | ✓ News hook, website scrape |
| **Atlas** | — | ✓ Production status, project refs |
| **Plutus** | — | ✓ Pricing / quote data when in context |
| **Hermes** | — | ✓ Drip/campaign design; can invoke Calliope + Clio |
| **EmailProcessor** | ✓ Fetch, parse, search, create draft, send | ✓ search_emails (Gmail), send_message |
| **find_company_contacts** | — | ✓ Script: Gmail search → up to 3 contacts (To + Cc) |

---

## 4. Where the multi-recipient step lives

- **Workflow doc:** `data/knowledge/outgoing_marketing_email_workflow.md` — **§ 3.9** and **§ 9** (checklist).
- **Lead guide:** `data/imports/24_WebSite_Leads/lead_email_case_study_and_joke_guide.md` — **Multi-recipient rule** at top.
- **Script:** `scripts/find_company_contacts.py` (search by company name; returns up to 3 emails).
- **Send:** `POST /api/email/send` with `to` + `cc`; or lead send scripts (e.g. `send_lead50_big_bear_email.py`) that call the script then send.

No pantheon agent is used for multi-recipient; it’s Gmail search + script logic.
