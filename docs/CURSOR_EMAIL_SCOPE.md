# Cursor Email Scope

Defines what email data Ira can access when running inside Cursor, and how.

## Mailbox

- **Single mailbox:** Rushabh's Gmail account, authenticated via OAuth (`credentials.json` / `token.json`).
- **EmailProcessor** uses this credential for all live Gmail operations (`search_emails`, `read_email_thread`, `observe_inbox`).
- All agents that have `EmailProcessor` injected share this single mailbox.

## Two paths to email data

### Highway: Qdrant (fast, pre-indexed)

- **What:** Mbox takeout data ingested via `ira takeout ingest` → DigestiveSystem → Qdrant with `source_category="takeout_email_protein"`. Live emails ingested via `observe_inbox` → Qdrant with `source_category="email"`.
- **How agents use it:** `clio.search_knowledge` / UnifiedRetriever → Qdrant vector search. Fast (sub-second).
- **When to prefer:** For general context, historical lookups, "what do we know about X." The scope resolver (pipeline step) routes here when the query doesn't need real-time data.

### Slow road: Live Gmail (real-time)

- **What:** Gmail API via `search_emails` and `read_email_thread` tools (registered on all agents when EmailProcessor is injected).
- **How agents use it:** ReAct tool calls during agent execution. Slower (1-5s per call, subject to Gmail API quotas).
- **When to prefer:** For "latest email from X," "what did Y say today," or anything requiring real-time inbox state. The scope resolver routes here when the query needs fresh data.

### Both

- For comprehensive research ("find everything about Project X"), the scope resolver sets `both` so agents can use Qdrant for historical context and Gmail for the latest.

## Neo4j (contact and company graph)

- **Person** nodes: `email`, `name`, `role`.
- **Company** nodes: `name`, `region`, `industry`, `website`.
- **Relationships:** `WORKS_AT`, `INTERESTED_IN`, `QUOTED_TO`, `QUOTES_MACHINE`, `CONTACTED_BY`, etc.
- **How agents use it:** `clio.search_knowledge_graph`, `find_company_contacts()`. Fast graph lookups for contact info, company relationships, quote history.
- **Available to all sub-agents** for fast contact/company lookups without hitting Gmail.

## Scope resolver

The pipeline classifies each query's email scope as one of:

| Scope | Meaning | Example queries |
|-------|---------|-----------------|
| `live_email` | Needs real-time Gmail | "latest email from Acme," "what did X say today" |
| `imported_email` | Qdrant is enough | "what do we know about Y," "history with Z" |
| `both` | Use Qdrant + Gmail | "find everything about Project X," "full analysis of Acme" |
| `no_email` | No email needed | "what's the PF1 lead time," "pipeline status" |

This is set in `context["email_scope"]` and checked by `_tool_search_emails` in `base_agent.py`.
