# Timeout Model — Total, Sub-Agents, and Athena Synthesis

Ira uses a layered timeout model so that within a **total** time budget, **sub-agents** run in parallel (each with a slot), and **Athena** has her own time to package the final answer for Cursor/API.

---

## 1. Total timeout (pipeline)

**What it is:** The maximum time for the full request (perceive → route → explore/think/memory → sub-agents → synthesis → shape). After this, the user gets a short “request timed out” message.

**Config:** `APP__PIPELINE_TIMEOUT` (seconds). Default: `600` (10 minutes).

**Typical presets:**

| Preset | Seconds | Use case |
|--------|---------|----------|
| 30s    | 30      | Quick factual lookup |
| 2 min  | 120     | Single-topic question |
| 5 min  | 300     | Multi-agent research |
| 10 min | 600     | Complex / Cursor tasks (default) |
| 20 min | 1200    | Deep analysis / task loop |

**Future: Ira/Athena chooses total by request type.**  
Total timeout can later be set by Athena (or a learning model) from request type / intent (e.g. “pipeline status” → 30s, “full deal analysis” → 10m). Today it is a single config value; the pipeline does not yet pass a “request type” hint for dynamic timeout.

---

## 2. Sub-process timeouts (inside the pipeline)

Before and after sub-agents, the pipeline runs other steps (perceive, remember, route, enrich, execute, gap resolve, faithfulness, shape). Each of these can have its own timeouts (e.g. Sphinx 15s, retriever backends 35s/12s). They all run within the **total** pipeline timeout above.

---

## 3. Parallel sub-agents and per-agent “slot” timeout

**What it is:** Athena (or the deterministic router) selects which agents to run. Up to **N** of them run **in parallel** (e.g. N=5). Each sub-agent gets a **slot**: a maximum time to return the best possible answer. If an agent hits its slot timeout, its response is replaced with a timeout message and synthesis still runs with the rest.

**Config:**

- `APP__MAX_PARALLEL_AGENTS` — Max number of sub-agents running at once (default: `5`).
- `APP__AGENT_TIMEOUT` — Per-agent slot in seconds (default: `90`). Each agent has this long to finish.

**Behavior:**

- Pantheon runs selected agents with `asyncio.gather` and a **semaphore** of size `max_parallel_agents`. So at most 5 (or whatever you set) run concurrently; the rest wait and run as slots free up.
- Each agent is wrapped in `asyncio.wait_for(..., timeout=agent_timeout)` (or the agent’s own `timeout` if set). So each sub-agent has a clear “slot” and must give Athena the best answer within that time.

---

## 4. Athena synthesis timeout (package answer for Cursor)

**What it is:** After Athena has all inputs (exploration, thinking, memory, sub-agent responses), she has a **dedicated timeout** to call the LLM and package the final answer so it can be displayed in the Cursor tab (or API).

**Config:** `APP__ATHENA_SYNTHESIS_TIMEOUT` (seconds). Default: `90`.

**Behavior:**

- Athena’s synthesis step is wrapped in `asyncio.wait_for(..., timeout=athena_synthesis_timeout)`.
- If it times out, the pipeline returns the concatenated sub-agent responses (no LLM-shaped answer) so the user still sees content.

---

## Summary

| Level              | Config                         | Default | Meaning |
|--------------------|--------------------------------|--------|---------|
| **Total**          | `APP__PIPELINE_TIMEOUT`        | 600s   | Full request; 30s / 2m / 5m / 10m / 20m presets; future: Athena/learning by request type. |
| **Sub-agent slot** | `APP__AGENT_TIMEOUT`           | 90s    | Per parallel sub-agent; best answer within this. |
| **Parallel cap**   | `APP__MAX_PARALLEL_AGENTS`     | 5      | Up to this many sub-agents at once. |
| **Athena synthesis** | `APP__ATHENA_SYNTHESIS_TIMEOUT` | 90s  | Time to package final answer for Cursor/API. |

## 5. Max rounds (ReAct loop depth)

**What it is:** Each sub-agent's ReAct loop (think → act → observe) runs for at most N iterations before forcing a final answer.

**Config:** `APP__REACT_MAX_ITERATIONS` (default: `8`).

**Stability tracking (Metis):** The Metis agent scores each response (0-100) and tracks a rolling average. When the average crosses 75 for 10 consecutive requests, Metis announces "I think we are stable." If the user rejects, Metis increases max_rounds by 20%. See `src/ira/agents/metis.py`.

---

All timeouts are enforced so that within the total budget, exploration, thinking, memory, and sub-agents run (with parallel slots), and Athena has her own window to produce the final answer for the Cursor tab.
