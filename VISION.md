# Ira — Vision

This document describes where Ira is, where it's going, and what we
deliberately choose not to do.

## What Ira Is

Ira is a multi-agent AI system purpose-built for Machinecraft. It is not a
platform, not a framework, and not a product for other companies. Every design
decision optimizes for one customer: Machinecraft and its founder.

The goal: an AI system that knows the business deeply enough to handle sales,
production, finance, marketing, HR, and quality — not by being a generalist,
but by routing to specialists who each own their domain.

## Current State

### What works

- 24 specialist agents with ReAct loops and domain-specific tools
- 11-stage request pipeline (perceive → remember → route → execute → learn)
- Three-tier routing: deterministic → procedural memory → LLM
- Hybrid retrieval across Qdrant (vectors), Neo4j (graph), and Mem0 (memory)
- Nine memory subsystems including dream mode for overnight consolidation
- Body-system metaphor for subsystem organization
- REST API, CLI, and Telegram interfaces
- CRM with companies, contacts, deals, and quotes in PostgreSQL
- Drip campaign engine with 7-stage sequences
- Document ingestion pipeline (PDF, DOCX, Excel)

### What needs work

- **Retrieval quality.** Reranking helps but the chunking strategy needs
  tuning. Some queries return irrelevant results from Qdrant.
- **Agent tool reliability.** Some tools fail silently or return empty results
  without the agent retrying or falling back.
- **Email processing.** The digestive system handles ingestion but the
  end-to-end email workflow (classify → draft → review → send) needs
  hardening.
- **Testing coverage.** Core pipeline and agents have tests; body systems
  and memory subsystems are under-tested.
- **Observability.** Pipeline stage timings exist but there's no dashboard
  for monitoring agent performance, tool success rates, or memory growth.
- **Production deployment.** The system runs locally with Docker Compose.
  There is no CI/CD pipeline or cloud deployment yet.

## Priorities

In order:

1. **Reliability.** Fix silent failures, add retries, improve error messages.
   Ira should never return "I don't know" when the answer is in the KB.
2. **Retrieval quality.** Better chunking, smarter query decomposition,
   tune reranking weights across Qdrant/Neo4j/Mem0.
3. **Email workflow.** End-to-end email processing from inbox to sent folder,
   with human-in-the-loop approval.
4. **Testing.** Increase coverage for body systems, memory, and the pipeline.
   Add integration tests that exercise the full request flow.
5. **Observability.** Dashboard for pipeline metrics, agent performance, and
   system health trends.

## Architectural Principles

### The pantheon model is intentional

Twenty-four agents is not accidental complexity. Each agent has a bounded
domain, its own tools, and its own system prompt. This makes the system:

- **Debuggable.** When pricing is wrong, you look at Plutus. When a drip
  email has the wrong tone, you look at Hermes.
- **Testable.** Each agent can be tested in isolation with mocked tools.
- **Extensible.** Adding a new capability means adding a new agent, not
  modifying a monolith.

Do not collapse agents into fewer, larger ones. The overhead of routing is
small compared to the clarity of bounded responsibility.

### The biological metaphor is intentional

Body systems (digestive, immune, endocrine, etc.) are not just naming. They
enforce separation of concerns:

- The immune system validates; it does not generate.
- The endocrine system modulates; it does not decide.
- The voice system shapes; it does not reason.

Do not merge body systems. If a new capability doesn't fit an existing system,
create a new one with a clear metaphor.

### Memory is a first-class citizen

Ira's value compounds over time. Every interaction should make the system
smarter. The nine memory subsystems exist because different kinds of knowledge
need different storage and retrieval patterns:

- Facts go to long-term memory (Mem0).
- Patterns go to procedural memory (SQLite).
- Relationships go to relationship memory (SQLite).
- Narratives go to episodic memory (SQLite + Mem0).

Do not shortcut memory. If an agent learns something useful, store it.

### Prompts are configuration, not code

System prompts live in `prompts/`, not inline in Python. This makes them:

- Editable without code changes
- Reviewable in isolation
- Versionable with clear diffs

Do not embed prompts in agent code. Use `load_prompt()`.

## What We Will Not Do

- **Generalize Ira into a platform.** Ira is for Machinecraft. Resist the
  urge to make it configurable for arbitrary businesses.
- **Add consumer-facing features.** Ira talks to Machinecraft employees and
  their customers. It is not a consumer product.
- **Replace the routing layer with a single large-context LLM.** The
  three-tier routing (deterministic → procedural → LLM) exists because most
  queries can be routed without an LLM call. This saves cost and latency.
- **Add agents without clear domain boundaries.** Every agent must have a
  role that doesn't overlap with existing agents. If the role overlaps,
  extend the existing agent instead.
- **Adopt heavy frameworks.** No LangChain, no LlamaIndex, no CrewAI. Ira
  uses raw httpx for LLM calls and manages its own ReAct loop. The
  complexity budget goes into domain logic, not framework abstractions.

## Long-Term Direction

- **Operational mode.** Move from TRAINING (draft-only) to OPERATIONAL
  (send emails, update CRM, trigger campaigns) with proper guardrails.
- **Proactive behavior.** Ira should surface insights without being asked:
  stale deals, overdue milestones, vendor lead time changes, follow-up
  reminders.
- **Multi-modal ingestion.** Process images of machines, engineering
  drawings, and handwritten notes from factory floors.
- **Voice interface.** Phone-based interaction for factory staff who don't
  use computers.
- **Continuous learning.** Tighter feedback loops between corrections,
  dream mode, and procedural memory so Ira self-improves faster.
