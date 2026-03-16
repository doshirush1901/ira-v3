# How to Start Ira Inside Cursor

Use Ira entirely from Cursor — no separate terminal or browser. This guide gets Ira running in your Cursor chat.

---

## 1. One-time setup (if not done yet)

- **Project open in Cursor** — Open the `ira-v3` repo in Cursor.
- **Dependencies** — From project root: `poetry install`.
- **Environment** — Copy `.env.example` to `.env` and set required keys (OpenAI, Qdrant, Neo4j, etc.). See [GETTING_STARTED.md](GETTING_STARTED.md) for details.
- **Docker Desktop** — Installed and running (used for Postgres and Redis).

---

## 2. Use Ira in Cursor

You can use Ira in two ways:

- **@Ira (on-demand bot):** Type **@Ira** or **@ Ira** followed by your question (e.g. *@Ira what's the pipeline?*). Cursor sends that question to Ira's full stack and shows you Ira's answer. No need to "Start Ira" first.
- **Start Ira (session):** Say "Start Ira" so that *every* message in that chat goes to Ira until you say "End Ira".
- **Ira and Cursor hand in hand:** Cursor can delegate to Ira when the task fits her stack (pipeline, CRM, email, memory); when Ira needs code or a script, Cursor builds it and they can hand off multiple times for the final answer. See `.cursor/rules/ira-cursor-handshake.mdc`.

### Step 1: Open a Cursor chat

Use the Cursor chat tab (Composer or Chat) in the same workspace as `ira-v3`.

### Step 2: Start a session (optional) or just @Ira

To have every message go to Ira, say you want to start Ira:

Type one of:

- **"Start Ira"**
- **"Activate Ira"** / **"Wake up Ira"**

The AI will:

1. **Check Docker** — If Docker isn’t running, it may prompt or start it.
2. **Start local services** — Run `docker compose -f docker-compose.local.yml up -d` from the project root (Postgres, Redis). If you use Qdrant Cloud and Neo4j Aura, no local Qdrant/Neo4j containers are needed.
3. **Show the startup animation** — A Prince of Persia–style ASCII splash appears in the chat (dungeon, torches, "IRA"), plus which **engines and tools** are hooked up and a **"What would you like to do today with Ira?"** prompt. Run `poetry run ira splash` in a terminal to see the full animation: engines lighting up one by one, then "All engines ready."
4. **Confirm Ira is running** — You’ll see a short status (e.g. “Ira is running”) for this chat.

### Step 3: You’re in Ira session

From that point, **every message you send in that chat** is sent to Ira until you end the session. You don’t need to say “@Ira” again — just ask.

---

## 3. Ask Ira anything

Examples:

- *"What's the lead time for a PF1-X-1210?"*
- *"Compare European sales cycles for Dutch Tides and Donite."*
- *"Which case study should we send for a Netherlands lead replacing an old thermoforming machine?"*

You’ll see the **agentic flow** in the same chat:

- **Explore** — What’s being looked up.
- **Think** — How the question is being routed (e.g. which agents).
- **Act** — Ira runs (CLI or API) and may show steps (e.g. Clio, Atlas, Athena).
- **Result** — Final answer in Markdown (tables, bullets, sources).

All of this stays **inside the Cursor chat**; no need to open a browser or run `ira ask` in a terminal yourself.

---

## 4. End the Ira session

When you’re done, type:

- **"End Ira"** / **"Stop Ira"** / **"Exit Ira"**

The AI will confirm that the session is off. Later, say **"Start Ira"** again in any chat to turn it back on for that chat.

---

## 5. Optional: API server for streaming

By default, Cursor runs Ira via the **CLI** (`ira ask`). No server is required.

If you want **live streaming** (step-by-step events in the chat), start the API server once in a terminal:

```bash
cd /path/to/ira-v3
poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000
```

Then, when you use Ira from Cursor, the AI can use the streaming endpoint and show progress (e.g. “Perceiving”, “Routing”, “Clio → search”) as it happens. This is optional; the CLI path works without the server.

---

## Quick reference

### Switch between Ira and Cursor

| You want          | Say (any of these) |
|-------------------|--------------------|
| **Switch to Ira** | "Start Ira", "Ira", "Ira mode", "switch to Ira" |
| **Switch to Cursor** | "End Ira", "Cursor", "Cursor mode", "switch to Cursor", "stop Ira" |
| **One question to Ira** (no session) | **@Ira** then your question |

### Other

| You want to…           | Do this in Cursor chat                          |
|------------------------|--------------------------------------------------|
| Ask a question (Ira session on) | Just type it; no need for @Ira again        |
| Use Ira again later    | **@Ira** for one-off, or **"Ira"** / **"Start Ira"** for session |

---

## Troubleshooting

- **"Docker not running"** — Open Docker Desktop and wait until it’s ready, then say **"Start Ira"** again.
- **Containers fail** — From project root run `docker compose -f docker-compose.local.yml ps` and check [TROUBLESHOOTING.md](TROUBLESHOOTING.md). If you use Qdrant Cloud / Neo4j Aura, only Postgres and Redis need to be up locally.
- **Ira command fails** — The AI will fall back to answering from the codebase and data in Ira’s voice and note that the full stack wasn’t available.

For more on the agentic flow and Cursor-only behavior, see [CURSOR_AGENTIC_LOOP.md](CURSOR_AGENTIC_LOOP.md) and `.cursor/rules/ira-cursor-only.mdc`.
