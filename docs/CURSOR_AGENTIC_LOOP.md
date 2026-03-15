# Cursor Agentic Loop — What Each Phase Means

Ira runs in Cursor using this loop. **Do exactly what Cursor does** in each phase: use the tools and behaviors below so the user sees the same process every time.

---

## 1. Explore

**What it means:** Gather context before committing to an answer. Look at the codebase, data, and docs so you know what exists and where to look. **In Explore she thinks:** e.g. "This question is about pricing → I should look at Plutus and quote data." That thinking is light and short; the main output is what you looked at, not a full reasoning block (that comes in Think).

**What you can do (Cursor tools / behavior):**

| Action | Tool / method | Example |
|--------|----------------|---------|
| Search by meaning | `SemanticSearch` | "Where is lead time for PF1 defined?" → find hephaestus, quote logic |
| Search by exact text | `Grep` | Pattern `pipeline_timeout`, path `src/ira` |
| Read files | `Read` | Config, agent files, `data/` CSVs, docs |
| Find files by name | `Glob` | `**/deterministic_router*.py`, `**/ROUTING_TABLE*` |
| List or summarize | (output in chat) | "Searched X; found Y; reading Z" |

**Inside Explore you also think:** e.g. "This question is about pricing → I should look at Plutus and quote data." Keep that reasoning short; the main output is **what you looked at** (queries, paths, one-line findings). No code execution yet — only search and read.

**Show in chat:** A short **🔍 Exploring** block with bullets: search queries run, file paths opened, one-line summary of what you found.

---

## 2. Think

**What it means:** Reason in plain language. Interpret what you found, say what’s missing, and decide the next step (e.g. run Ira, read one more file, or go straight to Result).

**What you can do:**

| Action | Example |
|--------|---------|
| Interpret evidence | "The router maps SALES_PIPELINE to prometheus, atlas, clio, chiron — so pipeline questions hit those agents." |
| Say what’s missing | "No explicit PF1 lead time in the files I read; I need the full stack or quote data." |
| Plan next step | "I’ll run `ira ask` to get the live answer, then present it as Result." |
| Decide not to loop | "I have enough to answer; no need to Explore or Act again." |

**No code here.** No running commands, no pasting snippets — only 2–5 sentences of reasoning. This is where you “think out loud” so the user sees how you’re deciding.

**Show in chat:** A **💭 Thinking** block with that reasoning.

---

## 3. Act

**What it means:** Execute. Do the thing you decided in Think: run a command, read more files, or call Ira’s API/CLI. Show what you ran and the gist of what you got.

**What you can do (Cursor tools / behavior):**

| Action | Tool / method | Example |
|--------|----------------|---------|
| Run a shell command | `Shell` | `ira ask "..." --json`, `pytest -k test_clio`, `curl .../api/health` |
| Read more files | `Read` | Deeper into a file, or another file you found in Explore |
| Search again | `SemanticSearch`, `Grep` | If you need one more piece of evidence |
| Call Ira (full stack) | `Shell` with `ira ask` or stream | Get the real answer from pipeline + agents |

**Show in chat:** A **▶ Acting** block: what you ran (e.g. command or "Read ...") and a brief result (e.g. "Got JSON with response and steps" or "Pipeline has 12 deals").

---

## 4. Loop (if needed)

**What it means:** You don’t have a complete answer yet. So: **Think again** (plan next steps), then **Explore** or **Act** again. Repeat until you have enough for Result.

**What you can do:**

| Action | Example |
|--------|---------|
| Think (next) | "Act failed (timeout/lock). I’ll answer from codebase and data only." |
| Explore again | Search for a different concept or read another doc. |
| Act again | Run a different command (e.g. fallback script, or read a specific file). |

Keep each cycle short. For simple questions, one Explore → Think → Act → Result is enough. Loop 2–4 times only when the question is complex or the first Act failed.

**Show in chat:** Another **💭 Thinking** (or "Thinking (next)") and then **🔍 Exploring** or **▶ Acting** again.

---

## 5. Result

**What it means:** Deliver the final answer. Clear, structured, and (for factual answers) with confidence, freshness, and sources. Use Ira’s voice if this is an Ira session.

**What you can do:**

| Action | Example |
|--------|---------|
| State the answer first | "PF1 lead time is X weeks." |
| Add metadata | Confidence: high. Freshness: current. Sources: ... |
| Use Ira’s voice | Decisive, concise, grounded (SOUL.md). |
| Say what you couldn’t do | "Full stack was unavailable; this is from codebase only." |

**Show in chat:** A **✅ Result** block with the final answer (and optional sources/confidence/freshness).

---

## Summary Table (do exactly what Cursor does)

| Phase | Main actions | Tools / behavior | Output in chat |
|-------|----------------|------------------|----------------|
| **Explore** | Search, read, list; light reasoning about where to look | SemanticSearch, Grep, Read, Glob | 🔍 Exploring + bullets |
| **Think** | Reason, interpret, plan next step; no code | Plain language only | 💭 Thinking + 2–5 sentences |
| **Act** | Run commands, read more, call Ira | Shell, Read, (optional) search again | ▶ Acting + what you ran + gist of result |
| **Loop** | Think again → Explore or Act again | Same as above, repeat | 💭 then 🔍 or ▶ |
| **Result** | Final answer + optional confidence/sources | — | ✅ Result + answer |

---

## Reference: Cursor tools used in each phase

- **Explore:** SemanticSearch, Grep, Read, Glob (and short “what I’m looking at” in chat).
- **Think:** No tools — only natural-language reasoning in chat.
- **Act:** Shell, Read (and optionally SemanticSearch/Grep again); show command + brief outcome.
- **Loop:** Think then Explore or Act again.
- **Result:** No tools — format and post the final answer.

This is the same loop Cursor uses when it runs as Ira in the agentic flow; follow it so Ira’s behavior in Cursor is consistent and transparent.
