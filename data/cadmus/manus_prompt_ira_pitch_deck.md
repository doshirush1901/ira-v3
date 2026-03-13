# MANUS TASK: Generate an Internal MBB-Style Pitch Deck for Ira v22.1

## CONTEXT FOR MANUS

You are creating an **internal pitch deck** (McKinsey/BCG/Bain style) for **Ira** — an AI system built by Rushabh Doshi, founder of Machinecraft Technologies, entirely inside Cursor IDE in 4 days (March 1–4, 2026). This deck is for the founding team to understand what was built, how it works, and what it means for the business.

The tone should be: confident, data-driven, visually clean, with the storytelling quality of a top-tier strategy presentation. Use dark backgrounds with accent colors (deep navy #0A1628, electric blue #3B82F6, gold #F59E0B). Minimal text per slide. Heavy use of diagrams, org charts, and data callouts.

---

## WHAT IRA IS

**Ira** (Intelligent Revenue Assistant) is a 23-agent AI system that runs the entire commercial engine of Machinecraft Technologies — a B2B industrial machinery company that builds thermoforming machines (machines that heat plastic sheets and form them into shapes: car dashboards, food trays, bathtubs, luggage shells, EV battery enclosures).

Ira is not a chatbot. She is a **cognitive system** with:
- 23 specialist AI agents organized in a Greek mythology pantheon
- Persistent memory across Telegram, Email, and API
- A nightly dream cycle where she consolidates knowledge while the team sleeps
- An immune system that auto-corrects recurring mistakes
- A biological architecture (organs, hormones, metabolism)
- 63 callable tools and 40+ skills
- Real-time mid-conversation learning
- Defense-in-depth against hallucinations (3 layers)

She was built entirely in **Cursor IDE** using Claude as the coding partner, in **116 commits over 4 days**.

**Company:** Machinecraft Technologies (machinecraft.in)
**Product:** Custom thermoforming machines (PF1, PF2, AM, IMG, FCS, ATF series)
**Markets:** Global — India, Europe (Germany, Netherlands, Austria, France), Japan, Canada, Middle East, Africa
**Price range:** $30,000 – $500,000+ per machine
**Sales cycle:** 6–12 months per deal
**Active leads:** 50+ across email and Telegram
**CRM contacts:** 610+
**Documents ingested:** 636+ files (quotes, POs, specs, emails, presentations)

---

## THE 23 AGENTS — COMPLETE PANTHEON

### Tier 1: The Orchestrator
| # | Agent | Greek Name | Role | Tools | Lines of Code |
|---|-------|-----------|------|-------|---------------|
| 1 | **Athena** | Goddess of Wisdom | The orchestrator. Every request starts and ends with her. GPT-4o, up to 25 tool-calling rounds per query. Holds the complete price table, machine rules, sales playbook in her system prompt. | All 63 tools | ~1,600 |

### Tier 2: Knowledge & Research (4 agents)
| # | Agent | Greek Name | Role | Tools |
|---|-------|-----------|------|-------|
| 2 | **Clio** | Muse of History | Deep researcher. Parallel search across Qdrant (vector), Mem0 (memory), Neo4j (graph), machine database. Intent detection routes to pricing/comparison/recommendation paths. | 1 |
| 3 | **Iris** | Goddess of Rainbow | Intelligence agent. Real-time company news, industry trends, geopolitical context via Jina AI + NewsData.io. 24-hour cache. Batch processing for multiple leads. | 3 |
| 4 | **Alexandros** | Library of Alexandria | Librarian over 636+ raw files in data/imports/. LLM-generated summaries, hybrid search (keyword + Voyage semantic). When Qdrant/Mem0 come up empty, Alexandros finds the raw document. | 3 |
| 5 | **Prometheus** | Titan of Foresight | Market discovery. Scans 10 emerging industries (EV batteries, drones, medical devices, modular construction, cold chain, agritech, data centers, marine, EV charging, renewables). Scores opportunities by technical fit, market timing, volume, competitive gap, revenue potential. Maps products to Machinecraft machine series. | 1 |

### Tier 3: Business Operations (7 agents)
| # | Agent | Greek Name | Role | Tools |
|---|-------|-----------|------|-------|
| 6 | **Mnemosyne** | Titan of Memory | CRM owner. 610+ contacts, leads, conversations, deals. Merges data from 7 sources. Deal pipeline: new → contacted → engaged → qualified → proposal → negotiating → won/lost/dormant. | 5 |
| 7 | **Plutus** | God of Wealth | Chief of Finance. Order book value, receivables, cashflow projections, revenue history, payment milestones, concentration risk. Reads from Excel, PDF, JSON. EUR/INR/USD conversion. CFO dashboard with KPIs. | 7 |
| 8 | **Atlas** | Titan who holds the world | Project Manager. Every active order: machine specs, production stage, payments, documents, deadlines. CRM-style logbook per project. Risk register integrating vendor health (Hera) and quality (Asclepius). Payment alerts for overdue milestones. | 7 |
| 9 | **Hera** | Goddess of Family | Vendor/Procurement Manager. 337 vendors, 6,926 purchase orders, 724 components. Component lead times, vendor outstandings from Tally ledger. McMaster-Carr-style taxonomy. Structured 6-email data collection sequence to Purchase Manager. | 3 |
| 10 | **Asclepius** | God of Healing | Quality & Punch-list Tracker. FAT (factory) and installation (customer site) punch-lists per machine. Items by severity (critical/major/minor/observation), category (mechanical/electrical/software/cosmetic/safety), assignment. Aging detection (>14 days flagged). Auto-close on resolution. | 4 |
| 11 | **Tyche** | Goddess of Fortune | Pipeline Forecaster. Win/loss analysis by region and machine type. Deal velocity and bottleneck detection. Conversion funnels. Weighted revenue forecast (stage-based probability). Engagement scorecards. Injects pipeline health into system prompt. | 3 |
| 12 | **Quotebuilder** | — | Formal PDF quotation builder. Matches real quote style from data/imports/. Tech specs, terms, optional extras, pricing. PDF export ready to attach and send. | 1 |

### Tier 4: Sales & Outreach (3 agents)
| # | Agent | Greek Name | Role | Tools |
|---|-------|-----------|------|-------|
| 13 | **Hermes** | God of Commerce | Sales outreach engine. 7-stage adaptive drip: INTRO → VALUE → TECHNICAL → SOCIAL PROOF → EVENT → BREAKUP → RE-ENGAGE. Builds ContextDossier per lead (CRM + Iris + product fit + references + regional tone). Reply detection and classification. | 6 |
| 14 | **Chiron** | Wisest Centaur | Sales trainer. Observes sales interactions, logs patterns and techniques Rushabh teaches. Injects coaching notes into Hermes' email drafting and Athena's system prompt. | 1 |
| 15 | **Delphi** | The Oracle | Inner voice. Mines real Gmail conversations, builds per-customer interaction maps, runs shadow simulations scoring Ira vs Rushabh on 8 dimensions (technical accuracy, tone, conciseness, action orientation, personalization, sales instinct, information density, overall alignment). Weakest dimensions get loudest whispers in system prompt. | 1 |

### Tier 5: Marketing & Content (2 agents)
| # | Agent | Greek Name | Role | Tools |
|---|-------|-----------|------|-------|
| 16 | **Cadmus** | Phoenician prince who brought the alphabet | Chief Marketing Officer. Case studies from customer projects. LinkedIn post drafts in Rushabh's voice. Manus AI integration for hero images and visuals. NDA-safe anonymisation. | 4 |
| 17 | **Arachne** | The mortal weaver | Content scheduler. LinkedIn Mon/Wed/Fri rotation. Monthly newsletter assembly from Atlas (orders) + Cadmus (case studies) + machine specs + Google Calendar + Iris (news). Manus AI for professional HTML design. Telegram approval workflow. Gmail distribution with BCC batching. | 3 |

### Tier 6: Craft & Safety (4 agents)
| # | Agent | Greek Name | Role | Tools |
|---|-------|-----------|------|-------|
| 18 | **Calliope** | Muse of Poetry | Writer. Polished professional prose for all communications. | 1 |
| 19 | **Vera** | (Latin: Truth) | Fact checker. Validates every response against machine_specs.json (46 models), business rules, model number regex. Catches hallucinations before they reach the user. | 1 |
| 20 | **Hephaestus** | God of the Forge | Code forge. Describe a task in English, he writes Python, executes in sandbox, auto-retries on failure. Used for data aggregation, ranking, cross-referencing, report generation. | 1 |
| 21 | **Nemesis** | Goddess of Retribution | Correction learner. Intercepts every failure: Telegram corrections, Sophia reflections, immune escalations. Stores corrections in Mem0 immediately. During nightly sleep, rewires truth hints, Qdrant, system prompt. No mistake goes unlearned. | 1 |

### Tier 7: Passive / System-Level (2 agents)
| # | Agent | Greek Name | Role | Mechanism |
|---|-------|-----------|------|-----------|
| 22 | **Sphinx** | The Riddler | Gatekeeper. For complex but vague requests, asks 3–8 clarifying questions before Athena runs. User replies with numbered answers or says "skip". Merges into enriched brief. | Pre-pipeline gate |
| 23 | **Sophia** | Wisdom personified | Reflector. After every interaction, reflects on quality. Feeds Nemesis on failures. Logs patterns for continuous improvement. | Post-response, fire-and-forget |

---

## ARCHITECTURE: HOW A MESSAGE FLOWS

```
USER MESSAGE (Telegram / Email / API)
        │
        ▼
┌─────────────────────┐
│  INJECTION GUARD     │  ← Regex blocks "ignore instructions", "jailbreak", etc.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  TRUTH HINTS         │  ← Simple question? Cached answer → FAST PATH (milliseconds)
└──────────┬──────────┘
           │ (complex or model-specific)
           ▼
┌─────────────────────┐
│  SPHINX (optional)   │  ← Vague request? Ask 3–8 clarifying questions
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  ATHENA TOOL LOOP    │  ← GPT-4o + 63 tools, up to 25 rounds
│  Calls any agent:    │
│  Clio, Iris, Plutus, │
│  Mnemosyne, Atlas,   │
│  Hera, Tyche, etc.   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  VERA VALIDATES      │  ← Hallucination check, business rules, model numbers
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  IMMUNE SYSTEM       │  ← Recurring issues? Escalate: log → flag → remediate → block
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  VOICE SYSTEM        │  ← Reshape for channel (Telegram=short, Email=formal)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  SOPHIA REFLECTS     │  ← Quality check; on failure → feeds Nemesis
└──────────┬──────────┘
           │
           ▼
      FINAL ANSWER → User
           │
           ▼ (async, fire-and-forget)
┌─────────────────────┐
│  REALTIME OBSERVER   │  ← Extracts facts/corrections/preferences → applied next turn
└─────────────────────┘
```

**5 agents whisper into every system prompt:**
- Nemesis → learned correction rules
- Delphi → Rushabh's communication style patterns
- Tyche → pipeline health summary
- Chiron → sales coaching notes
- Endocrine → agent stress/health indicators

---

## THE BIOLOGICAL ARCHITECTURE

Ira is built as a biological system — not metaphorically, but architecturally:

| Organ System | Module | Function |
|-------------|--------|----------|
| **Brain** | tool_orchestrator.py | Athena's 25-round tool loop, system prompt, price table |
| **Immune** | immune_system.py | Auto-remediation of chronic knowledge issues. Escalation: log → flag → remediate → block |
| **Respiratory** | respiratory_system.py | Operational heartbeat, latency metrics, daily rhythm |
| **Endocrine** | endocrine_system.py | Agent scoring: dopamine (success) / cortisol (failure). Natural selection for AI skills |
| **Digestive** | stomach_enrichment.py | EAT → TASTE → CHEW → DIGEST → FILTER → ABSORB → SLEEP → FORGET → SPEAK → GROW |
| **Musculoskeletal** | musculoskeletal_system.py | Action-to-learning feedback. Every email/quote/research produces myokines for dream cycle |
| **Sensory** | sensory_system.py | Cross-channel perception. Same customer across Telegram, Email, API |
| **Metabolic** | metabolic_system.py | Knowledge hygiene. Cleanup contradictions, stale facts, Qdrant waste |
| **Voice** | voice_system.py | Adaptive output: Telegram (short, 2000 chars) / Email (formal, 8000 chars) / API (markdown) |
| **Growth Hormone** | growth_signal.py | After each email digestion, stimulates every body system simultaneously |

### The Metabolic Cycle (How Ira Eats Knowledge)

```
📄 New document arrives in data/imports/
  → EAT: File detected by heartbeat watcher
  → TASTE: First 2K chars → GPT-4o-mini generates metadata label
  → CHEW: PDF/Excel/Word/PPTX → plain text extraction
  → DIGEST: spaCy NER + YAKE keywords + LLM structured extraction
  → FILTER: Quality gate (min words, info density, boilerplate, semantic dedup)
  → ABSORB: Stored in Qdrant + Mem0 + Neo4j + JSON backup (4 destinations, 1 write)
  → SLEEP: 12-phase nightly dream cycle at 2 AM
  → FORGET: 30d decay → 90d archive → 180d prune ("use it or lose it")
  → SPEAK: Adaptive tone/length/format per channel
  → GROW: Every email triggers growth_signal.py → stimulates all body systems
```

### The Dream Cycle (12 Phases, Runs at 2 AM)

| Phase | What Happens |
|-------|-------------|
| 0.5 | **Nemesis sleep training** — apply corrections to truth hints, Qdrant, Mem0, system prompt |
| 0.7 | **RealTime consolidation** — promote durable patterns from today's conversations to Mem0/Nemesis |
| 1 | Deep extraction from new documents |
| 2 | Cross-document insight generation |
| 3 | Synaptic pruning (remove weak connections) |
| 4 | Price conflict detection |
| 5 | Episodic-to-semantic consolidation |
| 6 | Knowledge graph update |
| 7 | Prediction reconciliation (compare predictions vs CRM outcomes) |
| 8 | Knowledge decay and confidence calibration |
| 8.6 | **Arachne** — check content calendar, send Telegram notifications for due items |
| 9 | Morning summary generation |

---

## MEMORY ARCHITECTURE

| Type | What It Stores | Where | Decay |
|------|---------------|-------|-------|
| **Semantic** | Facts, specs, pricing, learned knowledge | Qdrant (6 collections), Mem0 | Use-it-or-lose-it |
| **Episodic** | Conversation history, interaction records | Mem0, JSON logs | 30d → archive |
| **Procedural** | Learned workflows, response patterns | Mem0 | Slow decay |
| **Identity** | Cross-channel user recognition | CRM database | Permanent |
| **Real-time** | Mid-conversation facts, corrections, preferences | In-memory hub | Conversation-scoped, consolidated nightly |
| **Corrections** | Every mistake Ira has made and the fix | Nemesis correction store, Mem0 | Permanent |

### Qdrant Collections (Vector Database)

| Collection | Contents |
|-----------|----------|
| ira_chunks_v4_voyage | Document chunks (main knowledge base) |
| ira_emails_voyage_v2 | Ingested email content |
| ira_discovered_knowledge | Knowledge from dream cycles |
| ira_dream_knowledge_v1 | Cross-document insights from dreams |
| ira_market_research_voyage | Prometheus market research |
| ira_customers | Customer profiles and history |

---

## DEFENSE IN DEPTH (3 Layers Against Hallucination)

| Layer | What | How |
|-------|------|-----|
| **1. Prompt Injection Guard** | Pre-LLM | Regex blocks "ignore instructions", "jailbreak", "reveal system prompt". Unicode normalization prevents bypass via homoglyphs. Internal users bypass. |
| **2. Knowledge Health Validation** | Post-LLM | Regex-matches every model number against machine_specs.json (46 models). Catches placeholders, vague pricing, business rule violations (AM ≤1.5mm). Known fake models blacklisted. |
| **3. Immune System** | Recurring issues | Escalation ladder: 1x=log, 2x=flag, 3x=remediate (inject correct fact into Mem0), 5x=block topic, 10x=emergency alert. Self-healing. |

---

## HOW RUSHABH USES IRA — REAL USE CASES FROM DAY 4

### Use Case 1: Tyche Batch Send — 7 European Leads
Rushabh asked Ira to prepare outreach for a board meeting. Tyche assembled a batch of 7 European leads (2 warm re-engagement, 5 cold intro) across Germany, Netherlands, and Austria. Each email was built by 5 agents working in concert:
- **Alexandros** found the "Top 50 European Thermoforming Companies" data
- **Mnemosyne** pulled CRM history (past quotes, conversations)
- **Athena** matched the right machine to each lead
- **Cadmus** provided reference stories as social proof
- **Delphi** shaped the tone to match Rushabh's voice

Preview mode for review, then one-click send via Gmail with automatic CRM logging.

### Use Case 2: Cadmus LinkedIn Post — First Marketing Content
Cadmus drafted Machinecraft's first LinkedIn post from a real customer case study (bedliner project). Manus AI generated a professional hero image. The post was emailed to Rushabh for review and manual posting. NDA-safe: all customer names anonymised automatically.

### Use Case 3: Atlas Project Briefing
"What's the status of the [European Customer] order?" → Atlas returns: machine model, PO number, order value, payment terms (30/60/10 split), production timeline, 8 project documents, compliance status, budget headroom. Full CRM-style logbook with every email, payment, and milestone.

### Use Case 4: Plutus Financial Dashboard
"What's our financial position?" → Plutus returns: order book value, collected amount, outstanding receivables, collection rate, top 3 receivables as % of outstanding, next expected cash inflows by month, stalled payments flagged.

### Use Case 5: Hermes Drip Campaign
Hermes runs a 7-stage adaptive drip across European leads. Each email is personalized with: company news (Iris), machine fit (Clio), reference stories (Cadmus), regional tone adaptation (Germany=precise, Netherlands=direct). Reply detection classifies responses as engaged/polite_decline/auto_reply/bounce.

### Use Case 6: Nemesis Correction Learning
Rushabh corrects Ira on Telegram: "That's wrong — [Customer] only has 2 Cr pending." Nemesis intercepts, extracts the correction, stores it in Mem0 immediately (next query uses corrected data), and queues it for sleep training where it rewires truth hints and system prompt rules.

### Use Case 7: Hera Vendor Intelligence
"Who supplies our PLCs?" → Hera returns: Mitsubishi Electric India (281 POs historically), lead time data status, top vendors by volume (Festo 1,202 POs, Mitsubishi 281, SMC Corp 216). Vendor outstandings from Tally ledger.

### Use Case 8: Asclepius Quality Tracking
"What quality issues are open on [Customer]?" → Asclepius returns: punch-list with items by severity, category, status, assignment. Critical items flagged. Aging items (>14 days) warned. Auto-closes when all critical/major items resolved.

---

## TECHNOLOGY STACK

| Component | Technology |
|-----------|-----------|
| **LLM** | OpenAI GPT-4o (main brain) + GPT-4o-mini (extraction, metadata) |
| **Embeddings** | Voyage AI (voyage-3, 1024 dimensions) |
| **Vector DB** | Qdrant (6 collections, Docker) |
| **Memory** | Mem0 (long-term semantic memory) |
| **Graph DB** | Neo4j (entity relationships) |
| **Reranking** | FlashRank / ColBERT |
| **Search** | Hybrid (vector + BM25) |
| **CRM** | SQLite (ira_crm.db) |
| **Messaging** | Telegram Bot API |
| **Email** | Gmail API (OAuth2) |
| **Google** | Sheets, Drive, Calendar, Contacts |
| **Web Intel** | Jina AI (search + scrape) + NewsData.io |
| **NER** | spaCy |
| **Keywords** | YAKE |
| **PDF** | PyMuPDF + pdfplumber |
| **Visual AI** | Manus AI (hero images, newsletter design) |
| **IDE** | Cursor (Claude as coding partner) |
| **Language** | Python 3.10+ |
| **Security** | mr_sanitiser.py (pre-commit hook for PII/secrets) |

---

## KEY METRICS

| Metric | Value |
|--------|-------|
| Total commits | 117 |
| Days of development | 4 (March 1–4, 2026) |
| Agents in pantheon | 23 |
| Callable tools | 63 |
| Skills registered | 40+ |
| Lines of agent code | ~15,000+ |
| Total codebase | ~50,000+ lines |
| CRM contacts | 610+ |
| Vendors tracked | 337 |
| Purchase orders | 6,926 |
| Components catalogued | 724 |
| Documents in archive | 636+ |
| Machine models in database | 46 |
| Qdrant collections | 6 |
| Max tool rounds per query | 25 |
| Response time (simple) | <500ms (truth hints) |
| Response time (complex) | 2–15 seconds |
| Dream cycle phases | 12 |
| Body organ systems | 10 |
| Defense layers | 3 |
| Google integrations | 5 (Sheets, Drive, Calendar, Contacts, Gmail) |

---

## EVOLUTION TIMELINE (4 DAYS)

### Day 1 — Foundation (March 1)
- First commit. 6 core agents: Athena, Clio, Calliope, Vera, Sophia, Iris
- Brain/RAG pipeline with Qdrant, Mem0, Neo4j
- Telegram bot, email channel, truth hints
- Feedback loop: corrections stored immediately

### Day 2 — Sales Machine (March 2)
- 15+ commits in one day
- Added: Mnemosyne (CRM), Hermes (outreach), Prometheus (discovery), Plutus (finance)
- Holistic body systems: immune, digestive, respiratory, endocrine
- Telegram UX overhaul, personality injection
- Machine rules hardened, benchy test suite

### Day 3 — Intelligence Layer (March 3)
- Added: Hephaestus (code forge), Sphinx (gatekeeper), Nemesis (corrections)
- Deeper agentic pipeline with parallel tool execution
- 13 agents in the pantheon

### Day 4 — The Big Push (March 4)
- 20+ commits. Most productive day.
- Added: Delphi (inner voice), Chiron (sales trainer), Atlas (project manager)
- Added: Alexandros (librarian), Cadmus (CMO), Arachne (content scheduler)
- Added: Hera (procurement), Asclepius (quality), Tyche (pipeline)
- RealTimeObserver, Live Agent Activation Trace, streaming responses
- Manus AI integration for visuals
- Full security sanitisation (mr_sanitiser.py pre-commit hook)
- **v22.1 shipped with 23 agents**

---

## AGENT COLLABORATION: "BOARD MEETINGS"

Agents don't work in isolation. Here are the collaboration patterns:

### The Sales Board (Hermes chairs)
**Participants:** Hermes, Iris, Mnemosyne, Cadmus, Delphi, Chiron, Tyche
**When:** Every outreach batch
**Flow:** Mnemosyne provides CRM history → Iris gathers company intelligence → Cadmus supplies reference stories → Delphi shapes the voice → Chiron injects coaching → Tyche tells Hermes which regions/machines convert best → Hermes drafts the email

### The Finance Board (Plutus chairs)
**Participants:** Plutus, Atlas, Hera, Tyche
**When:** Financial review, cashflow questions
**Flow:** Plutus owns the numbers → Atlas provides project-level payment status → Hera flags vendor payables → Tyche forecasts pipeline revenue

### The Project Board (Atlas chairs)
**Participants:** Atlas, Asclepius, Hera, Plutus
**When:** Project status review
**Flow:** Atlas owns the project → Asclepius reports quality issues → Hera reports vendor/procurement status → Plutus reports payment milestones → Atlas compiles into risk register

### The Marketing Board (Cadmus chairs)
**Participants:** Cadmus, Arachne, Iris, Atlas
**When:** Content creation, newsletter assembly
**Flow:** Cadmus writes case studies and LinkedIn posts → Arachne schedules on content calendar → Iris provides industry news → Atlas provides order milestones → Arachne assembles newsletter

### The Learning Board (Nemesis chairs)
**Participants:** Nemesis, Sophia, Immune System, RealTimeObserver, Delphi
**When:** Continuous (every interaction)
**Flow:** Sophia reflects on quality → Immune system flags recurring issues → Both feed Nemesis → RealTimeObserver captures mid-conversation patterns → Nemesis applies corrections during sleep → Delphi measures alignment gap

---

## SLIDE STRUCTURE FOR THE DECK

Please generate a **20-25 slide deck** with this structure:

1. **Title Slide** — "Ira v22.1: The Pantheon" / Machinecraft Technologies / Internal / March 2026
2. **The Problem** — Sales complexity: 50+ leads, 6-12 month cycles, scattered across email/Telegram/Excel/PDF. Context is everything and context is lost.
3. **The Insight** — You can't solve this with one AI agent. You need a team. A pantheon.
4. **What Is Ira** — One sentence: "A 23-agent AI system that runs Machinecraft's entire commercial engine." Built in 4 days in Cursor.
5. **The Pantheon Overview** — Visual org chart showing all 23 agents in their tiers (Orchestrator → Knowledge → Business Ops → Sales → Marketing → Craft/Safety → Passive)
6. **How a Message Flows** — The 9-layer pipeline diagram (Injection Guard → Truth Hints → Sphinx → Athena Loop → Vera → Immune → Voice → Sophia → RealTime Observer)
7. **The Orchestrator: Athena** — GPT-4o, 25 rounds, 63 tools, system prompt with price table + machine rules + sales playbook
8. **Knowledge Layer** — Clio + Iris + Alexandros + Prometheus. How Ira knows things.
9. **Business Operations** — Mnemosyne + Plutus + Atlas + Hera + Asclepius + Tyche. The back office.
10. **Sales Engine** — Hermes + Chiron + Delphi. The 7-stage drip. ContextDossier assembly. Regional tone.
11. **Marketing Engine** — Cadmus + Arachne. Case studies, LinkedIn, newsletters, Manus AI visuals.
12. **The Biological Architecture** — Organ systems diagram. Immune, endocrine, respiratory, digestive, metabolic, voice, growth.
13. **Memory Architecture** — 6 memory types, 6 Qdrant collections, Mem0, Neo4j. "Use it or lose it" decay.
14. **The Dream Cycle** — 12 phases at 2 AM. "Ira learns while you sleep."
15. **Defense in Depth** — 3 layers against hallucination. Prompt injection guard → Knowledge health → Immune system.
16. **Real-Time Learning** — RealTimeObserver. Facts/corrections/preferences extracted mid-conversation. Applied on next turn. Consolidated nightly.
17. **Agent Collaboration: Board Meetings** — Sales Board, Finance Board, Project Board, Marketing Board, Learning Board. How agents work together.
18. **Use Case: European Outreach** — Tyche batch: 7 leads, 5 agents in concert, preview → send → CRM log
19. **Use Case: Project Intelligence** — Atlas + Asclepius + Hera + Plutus working together on a project review
20. **Use Case: Self-Healing** — Nemesis correction flow: Telegram correction → immediate Mem0 store → sleep training → truth hints/Qdrant/system prompt rewired
21. **The Numbers** — Key metrics slide (117 commits, 4 days, 23 agents, 63 tools, 610+ contacts, 337 vendors, 636+ documents, 46 machine models)
22. **Evolution Timeline** — Day 1 → Day 2 → Day 3 → Day 4. From 6 agents to 23.
23. **Technology Stack** — Clean grid of all technologies
24. **What's Next** — Web dashboard, WhatsApp, voice (Whisper), multi-language, CRM integrations (Salesforce/HubSpot)
25. **Closing** — "Built in 4 days. 23 agents. 63 tools. One AI that eats documents, dreams about them, and wakes up smarter."

---

## DESIGN GUIDELINES

- **Style:** McKinsey/BCG/Bain — clean, minimal text, heavy diagrams
- **Colors:** Dark navy (#0A1628) background, electric blue (#3B82F6) accents, gold (#F59E0B) for highlights, white text
- **Fonts:** Sans-serif (Inter, Helvetica Neue, or similar)
- **Diagrams:** Use clean boxes, arrows, and org charts. No clip art.
- **Data:** Use the exact numbers from the metrics section. No rounding unless it improves readability.
- **Tone:** Confident, technical, impressive but not boastful. Let the numbers speak.
- **Audience:** Internal team — they know the business, they want to understand the system
- **Format:** Landscape, 16:9 aspect ratio

Generate this as a complete, polished presentation. Every slide should have a clear headline, supporting visual or data, and minimal body text (3-5 bullet points max per slide). The diagrams should be the star — especially the org chart, message flow, biological architecture, and board meeting collaboration patterns.
