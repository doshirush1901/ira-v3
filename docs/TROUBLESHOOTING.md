# Troubleshooting

## Pipeline timeouts and `asyncio.exceptions.CancelledError`

**What it is:** When a run is stopped by an **external timeout** (e.g. Cursor’s 5‑minute limit, or a script that cancels the task), asyncio cancels the running coroutines. The innermost `await` then raises `asyncio.exceptions.CancelledError`. The run isn’t “stuck” — it was **cancelled**.

**Why it looks stuck:** The last log line is often deep in the stack (e.g. inside httpx or SSL read). That’s the point where the cancellation was delivered.

**What to do:**

- Run long queries (e.g. re-engagement drafts, multi-agent tasks) in your **own terminal** with no tool timeout:
  ```bash
  cd "$(git rev-parse --show-toplevel)" && poetry run ira ask "Your long query..." --json
  ```
- Increase timeouts for slow backends (e.g. `QDRANT_TIMEOUT` in `.env`).
- If you use the API, increase the HTTP client timeout or run behind a proxy that allows long-lived requests.

## Scraping (Crawl4AI, Firecrawl, Jina)

**Order used:** `scrape_url` tries (1) **Firecrawl** (if `FIRECRAWL_API_KEY`), (2) **Jina Reader** (no key), (3) **Crawl4AI** (Playwright), (4) **web_search** fallback.

- **Firecrawl:** Set `FIRECRAWL_API_KEY` in `.env` for best quality (JS rendering, anti-bot). [firecrawl.dev](https://firecrawl.dev).
- **Crawl4AI:** If you see “Executable doesn’t exist” or “markdown_v2 deprecated”, install browsers: `poetry run playwright install chromium`.
- **Jina:** No key; used automatically when Firecrawl is unset or fails.

## Mailbox access “down” from CLI

Agents need the **email processor** to use `search_emails` and `read_email_thread`. The CLI now injects it when the pipeline is built. If you still see “mailbox access is down”:

1. Ensure Google OAuth is set up: `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_TOKEN_PATH` (or run the email auth flow once).
2. Check logs for “CLI: email processor not available” — the message after it will indicate the cause (e.g. missing credentials).

## HHEMv2 / transformers warnings

The Vectara faithfulness model can emit “HHEMv2Config to instantiate HHEMv2” or tokenizer length warnings. These are suppressed in code; the model still runs. If you need to silence them in your environment, set `PYTHONWARNINGS=ignore` when running Ira, or ignore the message — it does not affect behaviour. Context is truncated to stay under 512 tokens to avoid "sequence length longer than maximum" errors.

## sqlite3.OperationalError: database is locked

SQLite is used by memory stores, correction store, agent journal, document ingestor ledger, learning hub feedback DB, Atlas logbook, Asclepius punch list, and embedding cache. All connections use `timeout=30` and `PRAGMA busy_timeout=30000` (wait up to 30s for the lock), and most use `PRAGMA journal_mode=WAL` to reduce contention. If you still see locks: (1) avoid running multiple Ira processes (CLI + server) against the same data directory; (2) ensure only one process writes to each SQLite file; (3) if a third-party component (e.g. Langfuse cache) uses SQLite in the same directory, consider moving it or disabling it.

## Avoiding two Ira processes (CLI + API server, or two CLIs)

Only **one** Ira process should use a given data directory at a time. Ira enforces this with a **single-instance lock** on `data/.ira.lock`:

- **CLI:** Commands `ira ask`, `ira chat`, and `ira task` acquire the lock when they start. If the API server (or another CLI run) already holds it, you get a clear error: *"Another Ira process is using this data directory (CLI or API server). Stop the other process or use a different IRA_DATA_DIR."*
- **API server:** On startup, the server acquires the same lock and holds it until shutdown. If you run `ira ask` or `ira chat` while the server is running, the CLI will block for up to 10 seconds then exit with the message above.

**What to do:**

1. **Use either CLI or server, not both** on the same machine/data dir. To query from Cursor or scripts, use `poetry run ira ask "..." --json` (no server). To use the web UI or streaming API, start the server and do not run `ira ask`/`ira chat`/`ira task` in parallel.
2. **Separate data dirs:** To run CLI and server at the same time (e.g. different repos or copies), set `IRA_DATA_DIR` to a different path for one of them so each process has its own `data/` and lock file.
3. **Stale lock:** If a process crashed without releasing the lock, the lock file is released by the OS when the process exits. Restart the other process.

## RuntimeError: Event loop is closed

Can appear during shutdown if a background task is still running. Often harmless; if it happens before you see the response, fix the primary error (e.g. database locked) first.

## Qdrant backfill: "All connection attempts failed" / ConnectError

**What it is:** The `ira graph backfill-from-qdrant` command scrolls the whole Qdrant collection and extracts entities into Neo4j. If Qdrant becomes unreachable mid-run (e.g. local container stopped, Docker restarted, or brief network blip), you get `ConnectError: All connection attempts failed` or `ResponseHandlingException` from the Qdrant client.

**What was changed:** Scroll calls in `scroll_collection_payloads` now retry up to 5 times with backoff (2s base) on connection/timeout errors, so short Qdrant outages no longer abort the backfill immediately.

**What to do:**

1. **Ensure Qdrant is running** (e.g. `docker compose -f docker-compose.local.yml up -d` from project root, or use Qdrant Cloud and set `QDRANT_URL` / `QDRANT_API_KEY`).
2. **Resume from where you left off:** Use `--resume` (or `-r`) to continue from the last saved offset. Progress is written to `data/.graph_backfill_state.json` after each batch; after a reboot or interrupt, run:
   ```bash
   poetry run ira graph backfill-from-qdrant --resume
   ```
3. **Re-run from the start.** Without `--resume`, the backfill starts from the beginning. The backfill uses MERGE in Neo4j, so it is idempotent and safe to re-run; state is cleared on successful completion.
