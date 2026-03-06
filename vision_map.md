# Ira Vision Map — Complete Catalog of Every Architectural Concept

## 1. THE AGENT PANTHEON (Named Agents)

### C-Suite / Primary Agents
| Agent | Greek Name | Role | Key Functions |
|:------|:-----------|:-----|:-------------|
| CEO / Orchestrator | **Athena** | Routes queries, orchestrates pipeline, synthesizes final response | Tool orchestration, agent delegation, response synthesis |
| CRO (Sales) | **Prometheus** | Sales, CRM, pipeline, lead management | CRM handoff, deal tracking, pipeline management |
| CMO (Marketing) | **Hermes** | Drip campaigns, outreach, board meeting research | Board meeting prep, campaign execution, lead intelligence |
| CFO (Finance) | **Plutus** | Financial analysis, quote pricing, revenue tracking | Quote lifecycle, pricing estimation, financial dashboards |
| CPO (Production) | **Hephaestus** | Machine specs, production, inventory | Machine database, specs, build processes |
| CHRO (HR) | **Themis** | Employee data, HR policies, skill matrix, payroll | Employee lookup, HR dashboard, skill matrix |
| Pipeline Forecaster | **Tyche** | Win/loss analysis, conversion funnels, revenue forecasting | Pipeline forecast, deal velocity, engagement scorecard |

### Specialist Agents
| Agent | Greek Name | Role | Key Functions |
|:------|:-----------|:-----|:-------------|
| Researcher | **Clio** | Deep research across all knowledge sources | Qdrant search, Mem0 recall, web search, multi-source synthesis |
| Writer | **Calliope** | Email drafting, response crafting, brand voice | Style patterns, email polish, adaptive tone |
| Fact Checker | **Vera** | Verify facts, figures, claims before responding | Cross-reference, truth validation |
| Reflector | **Sophia** | Post-interaction learning, dream mode consolidation | Reflection, lesson extraction, quality scoring |
| Gatekeeper | **Sphinx** | Intercept vague queries, ask clarifying questions | Ambiguity detection, question generation, brief enrichment |
| Quote Builder | **QuoteBuilder** | Generate formal PDF quotes with full specs | PDF generation, spec lookup, pricing |
| Memory Keeper | **Mnemosyne** | CRM, contact management, conversation history | Contact upsert, interaction logging, deal events |
| Trainer | **Nemesis** | Correction handling, sleep training, adversarial testing | Correction store, sleep trainer, stress testing |
| Intelligence | **Iris** | External intelligence gathering, web research, news | Web scraping, news monitoring, competitor research |
| Newsletter | **Arachne** | LinkedIn content, newsletter drafting | Content creation, social media |
| Content Creator | **Cadmus** | LinkedIn drafts, Manus outputs | Content pipeline |
| Delphi | **Delphi** | Inbound email classification, lead scoring | Email triage, intent detection |

## 2. BODY SYSTEMS (Biological Metaphor Architecture)

### Digestive System (Data Ingestion)
- **Stomach Enrichment**: Raw data → structured knowledge items
- **Email Nutrient Extractor**: Emails → sales facts, customer intel, communication patterns
- **Quality Filter**: Filter out noise, keep only "protein" (high-value data)
- **Knowledge Ingestor**: Batch ingestion into Qdrant with proper chunking + metadata

### Respiratory System (Operational Rhythm)
- **Heartbeat**: Every 5 minutes, record Ira is alive
- **Inhale Cycle**: Morning — gather, ingest, learn
- **Exhale Cycle**: Evening — dream, consolidate, report
- **Breath Timing**: Per-request HRV-like pipeline health monitoring

### Immune System (Error Handling & Self-Healing)
- **Error Monitor**: Track failures, patterns, recurring issues
- **Startup Validator**: Verify all systems healthy on boot
- **Knowledge Health**: Check Qdrant collection health, stale data

### Endocrine System (Adaptive Behavior)
- **Power Levels**: Energy/confidence levels that affect response style
- **Growth Signals**: Track learning velocity, knowledge gaps

### Musculoskeletal System (Action-to-Learning Feedback)
- **Action Recording**: Every CRM update, email sent, quote generated → learning signal
- **Outcome Tracking**: Did the email get a reply? Did the quote convert?
- **Myokines**: Learning signals extracted from actions

### Sensory System (Cross-Channel Integration)
- **Unified Perception**: Telegram + Email + Web → single coherent picture
- **Identity Resolution**: Same person across channels recognized as one entity

### Voice System (Response Shaping)
- **Adaptive Tone**: Match user's communication style
- **Channel Adaptation**: Telegram (short) vs Email (formal) vs CLI (detailed)
- **Length Enforcement**: Trim verbose, expand terse

## 3. BRAIN SYSTEMS

### RAG Pipeline (Retrieval-Augmented Generation)
- **Qdrant Retriever**: Vector search across document chunks
- **Hybrid Search**: BM25 (keyword) + Semantic (vector) fusion
- **Unified Retriever**: Multi-source retrieval with reranking (FlashRank)
- **Query Decomposition**: Complex questions → sub-queries → parallel retrieval
- **Voyage AI Embeddings**: Primary embedding model (voyage-3)
- **OpenAI Embeddings**: Fallback embedding model

### Knowledge Graph (Neo4j)
- **Entity Relationships**: Machines → specs, customers → quotes, regions → leads
- **Graph Consolidation**: Merge duplicate entities, strengthen connections
- **Relationship Discovery**: Find non-obvious connections between entities

### Document Processing
- **PDF Spec Extractor**: Extract machine specs from PDF catalogs
- **Document Extractor**: General document → structured data
- **Imports Metadata Index**: Index all files in data/imports/ with metadata
- **Realtime Indexer**: Index new documents as they arrive

### Machine Intelligence
- **Machine Database**: Complete machine catalog (PF1, AM, etc.)
- **Machine Features KB**: Feature-level knowledge base
- **Machine Recommender**: Match customer needs → best machine
- **Detailed Specs Generator**: Generate full technical specifications
- **Detailed Recommendation**: Multi-factor recommendation with reasoning

### Pricing & Quotes
- **Pricing Estimator**: Estimate pricing based on configuration
- **Pricing Learner**: Learn pricing patterns from historical quotes
- **Quote Generator**: Generate quote documents
- **Quote Email Formatter**: Format quotes for email delivery
- **Ingest Quotes**: Parse historical quotes into structured data

### Sales Intelligence
- **Sales Qualifier**: Score and qualify inbound leads
- **Inquiry Qualifier**: Classify inquiry type and urgency
- **Lead Email Drafter**: Draft personalized sales emails
- **Leads Database**: Structured lead storage and retrieval
- **Truth Hints**: Hard-coded business rules (AM thickness limits, lead times, etc.)

### Deterministic Router
- **Pattern-based routing**: Keywords → specific tool combinations
- **Intent categories**: sales_pipeline, finance_review, hr_overview, quality_risk, etc.
- **Required vs optional tools per intent**

## 4. MEMORY SYSTEMS

### Short-Term Memory
- **Conversation History**: Per-user, per-channel chat log
- **Entity Extraction**: Extract entities from each message
- **Coreference Resolution**: "he", "that machine" → resolved entities

### Long-Term Memory (Mem0)
- **Unified Mem0**: Single interface to Mem0 for all agents
- **Memory Search**: Semantic search across all memories
- **Memory Storage**: Store facts, preferences, corrections
- **Memory Decay**: Ebbinghaus forgetting curve for relevance

### Episodic Memory
- **Episodic Consolidator**: Convert conversations → episodic memories
- **Memory Weaver**: Connect related episodes into narratives
- **Memory Surfacing**: Surface relevant memories during conversations

### Procedural Memory
- **Learned procedures**: How to handle specific request types
- **Pattern recognition**: Recurring request → optimized response path

### Meta-Cognition
- **Knowledge States**: KNOW_VERIFIED, KNOW_UNVERIFIED, PARTIAL, UNCERTAIN, CONFLICTING, UNKNOWN
- **Confidence Calibration**: "I'm 90% sure" vs "I think, but not certain"
- **Source Awareness**: "User told me" vs "I inferred" vs "Document says"
- **Conflict Detection**: Flag contradictory information

### Dream Mode (Nightly Consolidation)
- **Dream Neuroscience**: Spaced repetition decay (Ebbinghaus), knowledge gap detection, REM-like creativity
- **Dream Advanced**: Deep consolidation with cross-referencing
- **Dream Experimental**: Novel connection discovery
- **Consolidation Job**: Scheduled nightly processing
- **Dream Reflection**: Drip campaign performance review during dreams

## 5. CONVERSATION INTELLIGENCE

### Emotional Intelligence
- **Emotion Detection**: Regex + LLM-based emotion detection
- **Emotional States**: NEUTRAL, POSITIVE, STRESSED, FRUSTRATED, CURIOUS, URGENT, GRATEFUL, UNCERTAIN
- **Intensity Levels**: MILD, MODERATE, STRONG
- **Adaptive Response**: Adjust tone based on detected emotion

### Inner Voice
- **Personality Traits**: Tunable traits (warmth, directness, humor, etc.)
- **Reflection Types**: OBSERVATION, OPINION, CELEBRATION, CURIOSITY, CONNECTION
- **Trait Evolution**: Traits adjust based on feedback (positive/negative outcomes)
- **Surfacing**: Inner reflections occasionally surface in responses

### Relationship Memory
- **Warmth Levels**: STRANGER → ACQUAINTANCE → FAMILIAR → WARM → TRUSTED
- **Memorable Moments**: Personal shares, celebrations, difficulties, preferences
- **Learned Preferences**: Per-user communication preferences

### Goal-Oriented Dialogue
- **Goal Types**: Lead qualification, meeting booking, quote preparation, follow-up scheduling
- **Goal Steps**: Structured progression with slot filling
- **Proactive Prompts**: Steer conversation toward goal completion

### Proactive Systems
- **Proactive Questions**: Ask follow-up questions to fill information gaps
- **Proactive Outreach**: Scan for stale leads, draft follow-ups
- **Insights Engine**: Generate insights from data patterns

## 6. CRM & SALES SYSTEMS

### CRM Core (ira_crm.db)
- **Contacts**: Name, email, company, region, industry, source, score
- **Interactions**: Every touchpoint logged (email, Telegram, phone)
- **Deal Events**: Stage transitions with timestamps
- **Deal Stages**: new → contacted → engaged → qualified → proposal → negotiation → won/lost

### Drip Campaign Engine
- **European Drip Campaign**: Region-specific campaign logic
- **Autonomous Drip Engine**: Self-sending, self-evaluating, self-improving
- **Campaign Self-Evaluator**: Track reply rates, engagement quality
- **Drip Dream Reflection**: Overnight analysis of campaign performance
- **Lead Intelligence**: Real-time context enrichment (news, industry, geopolitical)

### Quote Lifecycle
- **Quote Tracking**: Draft → Sent → Follow-up → Won/Lost
- **Quote-to-Lead Linking**: Connect quotes to CRM leads
- **Follow-up Automation**: Scheduled follow-ups based on quote status

### Customer Health
- **Health Scoring**: Engagement frequency, response latency, sentiment, conversion history
- **Risk Levels**: Identify at-risk relationships
- **Engagement Opportunities**: Flag re-engagement targets

### Lead Enrichment
- **Company Research**: Website, news, industry context
- **Contact Enrichment**: LinkedIn, email verification
- **HubSpot Integration**: Sync with HubSpot CRM

## 7. BOARD MEETINGS

- **Board Meeting Researcher**: Research company context before meetings
- **Board Hints**: Inject relevant context into agent prompts
- **Meeting Actions**: Track action items from meetings
- **Meeting Booker**: Workflow for scheduling meetings

## 8. SKILLS MATRIX (24 Skills)

| Skill | Purpose |
|:------|:--------|
| answer_query | Core query answering |
| discover_knowledge | Knowledge discovery and exploration |
| research_competitor | Competitor analysis |
| suggest_followup | Follow-up suggestions for stale leads |
| fact_checking_skill | Vera's fact verification |
| feedback_handler | Process user corrections |
| store_memory | Store facts in Mem0 |
| mem0_memory | Direct Mem0 interface |
| proactive_outreach | Automated lead follow-ups |
| reflection_skill | Post-interaction reflection |
| identify_user | Cross-channel identity resolution |
| unified_pipeline | Master orchestration |
| qualify_lead | Lead scoring and qualification |
| generate_quote | PDF quote generation |
| research_skill | Deep multi-source research |
| check_health | System health check |
| run_dream_mode | Nightly consolidation |
| deep_research | Extended research |
| recall_memory | Memory retrieval |
| detect_emotion | Emotional state detection |
| assess_confidence | Confidence calibration |
| writing_skill | Professional writing |
| draft_email | Email drafting |
| run_reflection | Auto post-interaction analysis |

## 9. DATA INFRASTRUCTURE

### Databases
- **PostgreSQL**: Primary relational database (via DATABASE_URL)
- **Qdrant**: Vector database for embeddings (chunks, emails, knowledge)
- **Neo4j**: Knowledge graph for entity relationships
- **SQLite (ira_crm.db)**: CRM data, leads, contacts, deals
- **SQLite (quotes.db)**: Quote lifecycle tracking
- **SQLite (employees.db)**: HR data (Themis)
- **Mem0**: Long-term memory storage

### Qdrant Collections
- ira_chunks_v4_voyage (document chunks, Voyage embeddings)
- ira_chunks_openai_large_v3 (document chunks, OpenAI embeddings)
- ira_emails_voyage_v2 (email chunks, Voyage embeddings)
- ira_emails_openai_large_v3 (email chunks, OpenAI embeddings)

### Document Imports (22 Categories)
01_Quotes_and_Proposals, 02_Orders_and_POs, 03_Product_Catalogues,
04_Machine_Manuals_and_Specs, 05_Presentations, 06_Market_Research,
07_Leads_and_Contacts, 08_Sales_and_CRM, 09_Industry_Knowledge,
10_Company_Internal, 11_Project_Case_Studies, 13_Contracts_and_Legal,
14_Miscellaneous, 15_Production, 16_LinkedIn_Data, 17_Vendors_Inventory,
18_Tally_Exports, 19_Business_Plans, 20_Email_Attachments,
21_WebCall_Transcripts, 22_HR_Data, Current_Machine_Orders

### External APIs
- OpenAI (GPT-4.1, GPT-4.1-mini)
- Anthropic (Claude)
- Voyage AI (embeddings)
- Google Workspace (Gmail, Sheets, Drive, Calendar, Contacts)
- Telegram Bot API
- NewsData API (news monitoring)
- HubSpot (CRM sync)

## 10. INTERFACES

### Telegram Bot
- Interactive chat with full agent access
- Commands: /start, /help, /inbox, /pipeline, /team, /vitals, /clear
- Admin notifications for new emails, drip results
- Document upload support

### Email (ira@machinecraft.org)
- Inbound email classification and routing
- Draft response generation
- Autonomous drip campaign sending
- Thread tracking and follow-ups

### CLI
- Interactive chat mode
- Single question mode
- Server mode (API + background tasks)

### Web Dashboard
- FastAPI server
- Health monitoring
- API endpoints for external integration

## 11. LEARNING & FEEDBACK LOOPS

### Real-Time Learning
- **Real-Time Observer**: Extract learnings from every conversation turn
- **Correction Learner**: Process explicit corrections immediately
- **Feedback Handler**: Store and apply user feedback
- **Learning Hub**: Central learning coordination

### Overnight Learning (Dream Mode)
- **Memory Consolidation**: Strengthen important memories, decay irrelevant
- **Knowledge Gap Detection**: Identify topics with low confidence
- **Creative Connections**: Discover novel relationships between concepts
- **Campaign Reflection**: Analyze drip campaign performance

### Continuous Improvement
- **Conversation Quality Scoring**: Rate every interaction
- **Error Monitoring**: Track and learn from failures
- **Prediction Logging**: Track prediction accuracy over time
