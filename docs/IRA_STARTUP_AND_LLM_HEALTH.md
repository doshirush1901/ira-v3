# Ira startup: health check first, then “Ira is started”

**Date:** March 2026  
**Context:** When you say “start Ira”, we should run a **health check first** and only then show the Prince of Persia–style animation and “Ira is running” card. Also: what the “circuit breaker open” and Anthropic 404 errors mean, and what to do after reloading the OpenAI wallet.

---

## 1. The two issues you hit

### 1.1 “Circuit breaker open for operation” (OpenAI)

- **What it is:** Ira’s LLM client uses a **circuit breaker** for OpenAI (and Anthropic). After **10 failures** in a row (e.g. 429 quota exceeded, timeouts), the breaker **opens** and blocks further calls for **180 seconds** (3 minutes).
- **Why you saw it:** Earlier, OpenAI returned **429 (quota exceeded)**. After 10 such failures, the breaker opened. So even after you **reloaded the wallet** ($288.85), Ira kept refusing to call OpenAI until the 180s window passed (or the process restarted / breakers were reset).
- **Where it lives:** `src/ira/services/resilience.py` (`CircuitBreaker`), `src/ira/services/llm_client.py` (OpenAI and Anthropic breakers, threshold=10, window_seconds=180).
- **What to do:**  
  - **Option A:** Wait ~3 minutes; the breaker will allow one attempt again (half-open).  
  - **Option B:** Restart the Ira process (API server or CLI) so the breakers are fresh.  
  - **Option C:** Call the new **reset** (see below) so the next “start Ira” or explicit reset clears the breakers and the next request is attempted.

### 1.2 Anthropic 404 “not_found_error”

- **What it is:** A **404 Not Found** from the Anthropic API. That usually means the **endpoint URL or the model name** is wrong (e.g. a deprecated or non-existent model, or wrong region/URL).
- **Why it’s different from OpenAI:** Not a quota/billing issue; it’s “resource not found”.
- **What to do:** Check `.env`: `ANTHROPIC_API_URL` (if set) and the model name used for Anthropic (in `ira.config` / LLM client). Ensure the model exists for your account and region.

---

## 2. Health check first, then “Ira is started”

**Agreed behaviour:** When the user says “start Ira”, we **do not** show the Prince of Persia animation and “Ira is running” card until we’ve run a **health check**.

- **Step 1:** Run the usual start-Ira steps (Docker check, `docker compose -f docker-compose.local.yml up -d`, verify containers).
- **Step 2:** Run a **health check**:
  - If the **API server is already running:** `curl -s http://localhost:8000/api/health` or `GET /api/deep-health` and inspect the response.
  - If **no API server:** From project root, `poetry run ira health` (immune system: Qdrant, Neo4j, PostgreSQL, **OpenAI**, Voyage, Langfuse).
- **Step 3:** Only **after** the health check:
  - If **all critical services are healthy** (or only non-critical are unhealthy): run the **Prince of Persia–style splash** and show the **“Ira is running”** status card and engines table.
  - If **OpenAI or another critical service is unhealthy:** still show the status card but add a **warning**, e.g.  
    *“⚠️ OpenAI unreachable (quota or circuit breaker). Ira will retry in a few minutes, or restart Ira / reset breakers after reloading your wallet.”*

So we **never** say “Ira is started” with the full animation until the health check has been run; we may still show the card with a warning if something is unhealthy.

---

## 3. Resetting circuit breakers after wallet reload

So that “Ira is started” after you’ve reloaded the OpenAI wallet doesn’t keep hitting an open breaker:

- **Code:** A **circuit breaker reset** is available (see below). When you “start Ira”, Cursor (or the CLI) can trigger this reset so the next LLM call is attempted.
- **Behaviour:** After a reset, the next OpenAI/Anthropic request is attempted; if the wallet is valid and quota is OK, the request should succeed.

---

## 4. References

- Immune system (health checks): `src/ira/systems/immune.py` — `run_startup_validation()` checks Qdrant, Neo4j, PostgreSQL, **OpenAI**, Voyage, Langfuse.
- Circuit breaker: `src/ira/services/resilience.py`; usage in `src/ira/services/llm_client.py`.
- Startup flow (Cursor): `.cursor/rules/ira-session-mode.mdc` — “When the user says start Ira” now includes health-check-before-splash.
