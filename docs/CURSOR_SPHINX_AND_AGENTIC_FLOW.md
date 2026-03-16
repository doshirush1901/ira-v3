# Sphinx visibility & Cursor vs Ira on the Harshul task

**Date:** March 2026  
**Context:** User asked (1) why Sphinx is not seen often when it was built to ask counter-questions before agent mode, and (2) whether the Harshul Jain recruitment email was done by Ira or Cursor, and whether Ira's agentic pipeline was used.

---

## 1. Sphinx — yes, we built it to ask counter-questions before agent mode

**Design:** Sphinx is the **gatekeeper**. It runs at **pipeline step 2.7** and is supposed to:
- Evaluate query clarity **before** routing to specialist agents.
- If the query is **vague or incomplete** → return **clarifying questions** (counter-questions) so the user can refine before we hit Athena/Prometheus/Themis/etc.
- If the query is **clear** → tag with `[CLEAR]` and the pipeline proceeds to routing and agents.

So the intended flow is: **User query → Sphinx → (if vague) show clarification questions; (if clear) proceed to agents.**

---

## 2. Why you're not seeing Sphinx often

### 2.1 Sphinx is skipped for many queries

Sphinx runs **only after** two short-circuit steps. If either matches, we **never reach Sphinx**:

| Step | What it does | Effect on Sphinx |
|------|----------------|------------------|
| **2.5 FAST PATH** | Regex match for greetings, identity, thanks, farewells ("hi", "who are you", "thanks") | **Skips Sphinx.** Response returned in 1–3 seconds. |
| **2.55 QUICK PIPELINE** | Short query like "show pipeline", "what's the sales pipeline" | **Skips Sphinx.** CRM summary returned directly. |

So any greeting or pipeline-only question **never hits Sphinx**. Only queries that **fail** both fast path and quick pipeline reach step 2.7.

### 2.2 When Sphinx runs, it usually says [CLEAR]

From `prompts/sphinx_system.txt`:
- *"Most queries are clear — default to [CLEAR] unless there is genuine ambiguity."*
- So when Sphinx **does** run, it often decides the query is clear and returns `[CLEAR]`. The pipeline then just logs `SPHINX CLEAR | query is actionable` and continues. **No message is sent to the user** — so you don't "see" Sphinx; you only see the final answer from the routed agent(s).

You **only see Sphinx** when it returns **`[CLARIFY]`** (vague query). Then the pipeline:
- Stores the clarification question
- Shapes it and **returns it to the user** (no agent run yet)
- User is expected to answer, then re-send (next request may use the clarification)

So Sphinx is "visible" only for **ambiguous** queries that pass fast path and quick pipeline.

### 2.3 In Cursor, streaming may not show "Sphinx checking"

When Cursor calls the API with streaming:
- The stream can emit `sphinx_checking` and (if clarify) `sphinx_clarifying`.
- If the UI doesn't surface every event, or we only show the final answer, the user may not see "Sphinx is checking" at all.
- If Cursor uses **Cursor-as-Ira fallback** (no API call — e.g. API down or we answer from codebase), **Sphinx is never run**; Cursor does its own clarification per `ira-cursor-workflow.mdc`.

### Summary: when do you see Sphinx?

- **Never** for: greetings, "show pipeline", and any fast-path or quick-pipeline match.
- **Rarely** for: clear long-form queries (Sphinx runs but returns [CLEAR], so no user-facing Sphinx message).
- **Only when**: the query is not fast/quick, **and** Sphinx decides it's vague and returns [CLARIFY] — then you see the counter-questions.

---

## 3. Making Sphinx more visible — FIXED (March 2026)

1. **Surface Sphinx in Cursor (done):** When using the streaming API, show a line like "• Sphinx: checking query clarity" for every `sphinx_checking` event, and "• Sphinx: clarification needed" when `sphinx_clarifying` is emitted. That way the user sees that Sphinx ran even when the result is [CLEAR] and we proceed.
2. **Stricter Sphinx (done):** In `prompts/sphinx_system.txt`, return [CLARIFY] when key entities (customer, project, machine, date) are missing; added vague-query examples.
3. **Don’t skip Sphinx for some paths:** Optionally run Sphinx even for quick-pipeline-style queries (e.g. "which pipeline?" → Sphinx could ask "Sales, production, or vendor?") — would require a small pipeline change.

---

## 4. Harshul Jain task — who did what (Cursor vs Ira)

### What was planned (tennis game)

The ideal flow would be: **User request → Cursor sends to Ira → Ira (Themis + Calliope, etc.) drafts the recruitment reply → Cursor shows Ira’s draft.** So Ira’s agentic pipeline and agents do the work; Cursor is the conduit.

### What actually happened

| Step | What happened |
|------|----------------|
| **Email search** | Cursor called Ira API `POST /api/email/search` — **succeeded**. Found Harshul Jain’s latest (16 Mar 2026, JOB APPLICATION). |
| **Thread body** | Cursor called `GET /api/email/thread/19cf517f63544eb9` — **500**. Body not available. |
| **Ira query for draft** | Cursor called `POST /api/query` with the full recruitment-draft prompt (Themis + profile questions + Calliope-style reply). **Ira’s pipeline ran** (we got a response from the API). |
| **Ira’s output** | The API returned something like "I'm not entirely certain... (No response)" and a Metis stability line. So **no usable draft** from Athena/agents. |
| **Draft creation** | **Cursor** then wrote the recruitment reply and the Themis-style checklist and saved it to `data/knowledge/draft_email_harshul_jain_plant_manager_umargam.md`. |

So: **Ira was invoked** (email search + query API), but **Ira’s agentic pipeline did not produce the recruitment email**. The pipeline ran but the synthesizer had no (or insufficient) agent output to work with. **Cursor completed the task** using Themis/Calliope framing and wrote the draft.

### Were any of Ira’s agentic models or pipelines used?

- **Yes:** The **request pipeline** was used (query hit the API; pipeline executed).
- **Yes:** **Email search** (part of Ira’s stack) was used and returned the Harshul thread list.
- **No:** The **agents that should have produced the draft** (e.g. Themis for HR questions, Calliope for the email text) did **not** return content that made it into the final response. So no "tennis" in the sense of Ira returning a draft and Cursor refining it — Ira was asked, Ira didn’t deliver a draft, Cursor did the writing.

**Bottom line:** The last task was **mostly done by Cursor**, with Ira used for email discovery and one attempted (but unsuccessful) agentic draft. To get a true tennis game, we’d need the pipeline to reliably return a draft from Themis/Calliope (or routed agents) so Cursor can show and optionally refine Ira’s reply.
