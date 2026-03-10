# Cursor Rules & Custom Workflows

All workflows that Cursor follows when you use Ira are defined in `.cursor/rules/` and a few supporting docs. This page indexes them so nothing is missed.

## Lifecycle (ira-api.mdc)

| Workflow | Trigger | What Cursor does |
|:---------|:--------|:-----------------|
| **Start Ira** | "wake up Ira", "start Ira", "activate Ira" | Start Docker (Postgres, Qdrant, Neo4j, Redis) only; no API server. See §1. |
| **Query Ira** | "@Ira", "ask Ira", "tell Ira" | Run `ira ask "<question>" --json` from project root; on failure use Cursor-as-Ira fallback. See §2. |
| **Complex task** | "@Ira do a full analysis...", "prepare a report..." | Run `ira task "<goal>" --json` (or API task stream if server up). See §2b + [ira-task-loop.mdc](../.cursor/rules/ira-task-loop.mdc). |
| **Feedback / correction** | "that's wrong", "actually it's..." | POST to `/api/feedback` with correction text and context. See §3. |
| **Email search** | "find emails from...", "pull up emails about..." | POST to `/api/email/search`; read thread via `/api/email/thread/<id>`. See §4. |
| **Email reply flow** | Read mail → draft reply → show in Cursor → revise or send | Draft via query/task, show To/Subject/Body; on "change X" redraft; on "send" call `/api/email/send`. See §4b. Also in [Stable modes](#stable-modes). |
| **Ingest file** | "learn this file", "ingest this" | POST to `/api/ingest` with file. See §5. |
| **Stop Ira** | "stop Ira", "shut down Ira" | Kill uvicorn if running; optionally `docker compose down`. See §7. |

## Fallback when CLI/API fails (ira-cursor-workflow.mdc)

When `ira ask` or the API is unavailable, Cursor follows the **Cursor-as-Ira** workflow: perceive → remember (codebase + `data/`) → route (delegation) → gather → synthesize → shape. Same voice and response contracts; no live DB. See [.cursor/rules/ira-cursor-workflow.mdc](../.cursor/rules/ira-cursor-workflow.mdc).

## Task loop (ira-task-loop.mdc)

- **Primary:** `ira task "<goal>" --json` from project root (no server).
- **Alternative:** When server is running, POST to `/api/task/stream`; clarify via `/api/task/clarify`.
- **Fallback:** If both fail, use Cursor-as-Ira workflow for the goal.

See [.cursor/rules/ira-task-loop.mdc](../.cursor/rules/ira-task-loop.mdc).

## MCP agent loop (ira-agent-loop.mdc)

When the user asks for multi-step work **and** the MCP server is running: use `plan_task` → `execute_phase` (per phase) → `generate_report`. See [.cursor/rules/ira-agent-loop.mdc](../.cursor/rules/ira-agent-loop.mdc).

## Stable modes

Well-defined flows we keep working. When the user says **"add this to stable list"**, add the item to [docs/stable_modes.md](stable_modes.md) (rule: [ira-stable-modes.mdc](../.cursor/rules/ira-stable-modes.mdc)).

| Mode | Description |
|:-----|:------------|
| **Email reply flow (Cursor)** | Read mail → draft reply → show in Cursor → revise until satisfied → user says "send" → POST `/api/email/send`. No auto-send. |

## Skills & domain workflows

| Doc | Purpose |
|:----|:--------|
| [data/knowledge/lead_engagement_email_skill.md](../data/knowledge/lead_engagement_email_skill.md) | Lead re-engagement email drafting (evidence-based, document-backed; Vladimir/Komplektant-style flow). When to use Hermes, Calliope, Alexandros. |

## Other rules (behavior, not workflows)

These shape how Cursor and Ira behave; they don’t define discrete “workflows”:

- **ira-soul.mdc** — Identity, voice, boundaries
- **ira-response-contracts.mdc** — Confidence, freshness, sources
- **ira-data-verification.mdc** — Source priority, verification contract
- **ira-delegation-matrix.mdc** — Which agent/domain for which question
- **ira-email-safety.mdc** — Draft-only default, no auto-send, approval metadata
- **ira-memory-policy.mdc** — What to store / not store, correction supremacy
- **ira-retrieval-slos.mdc** — Retrieval order, quality, failure behavior
- **ira-vision.mdc** — Priorities, what we won’t do
- **ira-guardrails.mdc** — LLM usage, autonomy level, architecture
- **ira-conventions.mdc** — Code and agent conventions
- **prompt-conventions.mdc** — Prompt style and token limits

---

**Summary:** Start/query/task/feedback/email/ingest/stop are in **ira-api.mdc**. Fallback when CLI fails is **ira-cursor-workflow.mdc**. Task loop details in **ira-task-loop.mdc**. MCP multi-step loop in **ira-agent-loop.mdc**. Stable flows in **docs/stable_modes.md**. Lead engagement in **data/knowledge/lead_engagement_email_skill.md**.
