# Ira Operations Manual

Day-to-day handbook for running, training, and maintaining the Machinecraft AI Pantheon.

---

## Table of Contents

1. [System Startup and Shutdown](#1-system-startup-and-shutdown)
2. [Monitoring](#2-monitoring)
3. [Training Ira](#3-training-ira)
4. [Adding Knowledge](#4-adding-knowledge)
5. [Managing Campaigns](#5-managing-campaigns)
6. [Troubleshooting](#6-troubleshooting)
7. [The Graduation Process](#7-the-graduation-process)

---

## 1. System Startup and Shutdown

Ira runs as a set of Docker containers managed by `docker-compose.prod.yml`. The stack includes:

| Container | Purpose | Port |
|-----------|---------|------|
| **ira-app** | FastAPI server + background scheduler | 8000 |
| **qdrant** | Vector database (knowledge base) | 6333 |
| **postgres** | CRM and relational data | 5432 |
| **neo4j** | Knowledge graph (entities/relationships) | 7474 / 7687 |

### Prerequisites

1. Copy `.env.example` to `.env` and fill in all API keys:

   ```bash
   cp .env.example .env
   ```

   At minimum you need: `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `NEO4J_PASSWORD`, and `GOOGLE_CREDENTIALS_PATH`.

2. Ensure Docker and Docker Compose are installed.

### Starting

```bash
scripts/start.sh
```

This runs `docker-compose -f docker-compose.prod.yml up -d --build`, which builds the app image and starts all four containers in the background.

### Stopping

```bash
scripts/stop.sh
```

This runs `docker-compose -f docker-compose.prod.yml down`, which stops and removes all containers. Persistent data (Qdrant storage, Postgres data, Neo4j data) is stored under `data/` and survives restarts.

### Development Mode (Infrastructure Only)

If you want to run the app locally (outside Docker) while keeping the databases containerised:

```bash
docker-compose up -d          # starts qdrant, neo4j, postgres only
poetry install                # install Python dependencies
ira --help                    # verify the CLI is available
```

The root `docker-compose.yml` only defines the three database services, not the app.

---

## 2. Monitoring

### Health Check

Run the immune system health check to verify all services are reachable:

```bash
ira health
```

This tests connectivity to Qdrant, Neo4j, PostgreSQL, OpenAI, and Voyage. Each service is reported as `healthy`, `degraded`, or `unhealthy`. The same check is available via the API at `GET /api/health`.

### Dashboard

The web dashboard is served at:

```
http://localhost:8000/dashboard/
```

It displays:

- **Interaction volume** -- daily query counts over the past 30 days.
- **Intent distribution** -- breakdown of classified intents (quote requests, support, etc.).
- **Feedback trends** -- average feedback score over time.
- **Pipeline qualification** -- leads qualified and their scores.
- **Campaign activity** -- active drip campaigns and step completion.

### Logs

When running via Docker, view live logs with:

```bash
docker-compose -f docker-compose.prod.yml logs -f ira-app
```

The log format is:

```
HH:MM:SS  module_name                  LEVEL     message
```

For CLI commands, pass `--verbose` / `-v` to enable `DEBUG`-level output:

```bash
ira health -v
ira ingest -v
```

### Respiratory Heartbeat

The `RespiratorySystem` runs a heartbeat every 5 minutes in the background server, logging memory usage, uptime, and average response latency. If memory exceeds 2 GB or average response time exceeds 30 seconds, a warning is sent to the admin Telegram chat.

### Scheduled Cycles

| Time | Event | What Happens |
|------|-------|--------------|
| 03:00 | Dream | Memory consolidation, insight generation, pruning |
| 06:00 | Inhale | Document ingestion + email processing |
| 22:00 | Exhale | Dream cycle + drip evaluation + Telegram summary |

These run automatically when the server is up. To trigger a dream cycle manually:

```bash
ira dream
```

---

## 3. Training Ira

Ira starts in **TRAINING** mode, where she observes email threads on `rushabh@machinecraft.org` (read-only) and learns from your interactions. The goal is to accumulate enough supervised experience before graduating to autonomous operation.

### Daily Workflow

#### Step 1: Teach Ira from Real Email Threads

After handling an email thread in Gmail, feed it to Ira so she can learn the context, entities, and your communication style:

```bash
ira email learn --thread-id "18f3a..."
```

This fetches the full thread from Gmail, runs it through the DigestiveSystem (extracting high-value facts, entities, and metadata), updates the CRM, and stores the knowledge in the vector database.

To find a thread ID, look at the Gmail URL: `https://mail.google.com/mail/u/0/#inbox/<thread_id>`.

#### Step 2: Draft Emails with Ira's Help

Ask Calliope to draft an email, then review and send it yourself:

```bash
ira email draft \
  --to "client@example.com" \
  --subject "Follow-up on PF2 Quote" \
  --context "We discussed the PF2-1200 at the trade show. They need delivery by Q3. Budget around $180k."
```

The draft is printed to the terminal for you to copy-paste into Gmail. Over time, Ira learns your tone and preferences from the threads you feed back via `email learn`.

#### Step 3: Ask Questions and Chat

Use the interactive chat or single-query mode to test Ira's knowledge:

```bash
ira chat                                          # interactive session
ira ask "What's the lead time on the RF-100?"     # single question
```

#### Step 4: Run Training Cycles

Nemesis stress-tests the Pantheon agents by generating adversarial scenarios, scoring responses against ideal answers, and logging the results:

```bash
ira train                    # 3 scenarios (default)
ira train --scenarios 10     # more thorough
```

Training results feed into the LearningHub, which identifies skill gaps, knowledge gaps, and quality issues. These are visible on the dashboard.

#### Step 5: Run Board Meetings

Board meetings bring all agents together to discuss a strategic topic:

```bash
ira board "Q3 European expansion strategy"
```

Each agent contributes from their domain, and Athena synthesises the discussion into action items.

### Feedback Loop

Feedback currently flows through the Nemesis training cycle. When Nemesis scores an agent response below the threshold (score <= 3), the LearningHub:

1. Runs **gap analysis** to classify the failure (missing skill, knowledge gap, or quality issue).
2. Records the failure in **ProceduralMemory** so future similar queries can be handled better.
3. If a correction is provided, runs **correction analysis** to understand what went wrong.

The average feedback score, total interactions, and learned procedures are the three metrics that determine graduation readiness.

---

## 4. Adding Knowledge

### Directory Structure

Place documents in `data/imports/` using numbered subdirectories:

```
data/imports/
├── 01_Quotes_and_Proposals/
│   ├── quote_PF2_acme_corp.pdf
│   └── proposal_template.docx
├── 02_Product_Catalog/
│   └── machine_specs_2025.xlsx
├── 03_Pricing/
│   └── price_list_Q1.csv
├── 04_Case_Studies/
│   └── acme_installation.pdf
├── 05_Technical_Manuals/
│   └── PF1-C_operations_manual.pdf
...
```

The numeric prefix (e.g. `01_`) is stripped and the remainder becomes the **source category** (e.g. `quotes_and_proposals`). This category is stored as metadata on every chunk and enables filtered retrieval.

### Supported File Types

| Extension | Reader |
|-----------|--------|
| `.pdf` | pypdf |
| `.xlsx` | openpyxl |
| `.docx` | python-docx |
| `.csv` | built-in csv |
| `.txt` | plain text |

### Running Ingestion

```bash
ira ingest                          # ingest everything under data/imports/
ira ingest data/imports/03_Pricing  # ingest a specific subdirectory
ira ingest --force                  # re-ingest all files, even if unchanged
ira ingest -v                       # verbose logging
```

The command:

1. **Discovers** all supported files and displays an ingestion plan (file count, directory count, total size).
2. **Processes** each file with a progress bar, reading the content, splitting it into 512-token overlapping chunks, and upserting into Qdrant.
3. **Tracks** ingested files in a SQLite ledger (`data/ingested_files.db`) using SHA-256 hashes. Unchanged files are skipped on subsequent runs.
4. **Reports** a summary table with files processed, skipped, failed, and total chunks created.

If a file fails to parse (e.g. a corrupted PDF), the error is logged and ingestion continues to the next file. A "Failed Files" table is shown at the end with the error details.

The `--force` flag bypasses the ledger check and re-ingests all files. It also deletes existing Qdrant points for each file before re-upserting, so you won't get duplicate chunks.

### Automatic Ingestion

When the server is running, the RespiratorySystem's **Inhale** cycle (06:00 daily) automatically runs document ingestion on `data/imports/`.

---

## 5. Managing Campaigns

### Campaign Concepts

A drip campaign is a multi-step automated email sequence sent to a segment of contacts. Each campaign has:

- **Target segment** -- CRM filters (region, warmth level, lead score range).
- **Steps** -- Sequenced emails with delay offsets, themes, and templates.
- **Send window** -- Business hours and timezone for scheduling.
- **GDPR notice** -- Optional compliance footer for EU campaigns.

### Built-in European Campaign

The system includes a pre-built `EUROPEAN_CAMPAIGN_TEMPLATE` with 4 steps:

| Step | Day | Theme |
|------|-----|-------|
| 1 | 0 | Introduction |
| 2 | 5 | Value proposition |
| 3 | 12 | Case study |
| 4 | 20 | Meeting request |

It targets EU contacts (STRANGER and ACQUAINTANCE warmth levels), schedules within Berlin business hours (09:00--17:00, weekdays only), and appends a GDPR unsubscribe notice.

### Creating a Campaign

Campaigns are created programmatically through the `AutonomousDripEngine`:

```python
from ira.systems.drip_engine import AutonomousDripEngine

# Generic campaign
campaign = await engine.create_campaign(
    name="MENA Q3 Outreach",
    target_segment={
        "region": "MENA",
        "warmth_level": ["STRANGER"],
        "lead_score_min": 20,
        "lead_score_max": 80,
    },
    steps=[
        {"step_number": 1, "delay_days": 0, "theme": "introduction",
         "template": "Subject: Machinecraft for {industry}\n\nHi {name}, ..."},
        {"step_number": 2, "delay_days": 7, "theme": "follow_up",
         "template": "Subject: Quick follow-up\n\nHi {name}, ..."},
    ],
)

# European campaign (uses built-in template)
campaign = await engine.create_european_campaign()
```

Templates support `{name}`, `{region}`, and `{industry}` placeholders, which are filled from each contact's CRM profile.

### Campaign Lifecycle

1. **Creation** -- contacts are matched, steps are scheduled.
2. **Execution** -- the `run_campaign_cycle()` method (called during the Exhale cycle or manually) sends due emails via Hermes and Gmail.
3. **Evaluation** -- `evaluate_campaign()` computes per-step open/reply rates and requests LLM improvement suggestions.
4. **Auto-adjustment** -- `auto_adjust_campaign()` pauses contacts with negative sentiment and rewrites underperforming emails via LLM.

### Monitoring Campaigns

Campaign activity is visible on the dashboard at `/dashboard/`. The drip engine logs all sends, replies, and adjustments.

---

## 6. Troubleshooting

### Google OAuth Re-authentication

**Symptom:** Email commands fail with `invalid_grant` or `Token has been expired or revoked`.

**Fix:**

1. Delete the stored token:

   ```bash
   rm token.json
   ```

2. Run any email command to trigger the OAuth flow:

   ```bash
   ira email learn --thread-id "any_valid_id"
   ```

3. A browser window opens. Sign in with the Google account and grant the requested permissions.

4. The new token is saved to `token.json` automatically.

**Note:** In TRAINING mode, Ira only requests `gmail.readonly`. After graduation to OPERATIONAL mode, it requests `gmail.modify` and `gmail.compose`, so you will need to re-authenticate once after graduation.

### Qdrant Connection Refused

**Symptom:** `ira health` reports Qdrant as `unhealthy`, or ingestion fails with a connection error.

**Fix:**

1. Check if the container is running:

   ```bash
   docker ps | grep qdrant
   ```

2. If not running, restart the infrastructure:

   ```bash
   docker-compose up -d    # dev mode
   # or
   scripts/start.sh        # prod mode
   ```

3. Verify connectivity:

   ```bash
   curl http://localhost:6333/collections
   ```

### Neo4j Authentication Failure

**Symptom:** Health check reports Neo4j as `unhealthy` with an auth error.

**Fix:** Ensure `NEO4J_PASSWORD` in `.env` matches the password set in `docker-compose.yml` (default: `ira_password`). If you changed it in one place, update the other. Then restart:

```bash
docker-compose down && docker-compose up -d
```

### PostgreSQL Connection Issues

**Symptom:** CRM operations fail or `ira pipeline` shows no data.

**Fix:**

1. Verify the container is running: `docker ps | grep postgres`
2. Check that `DATABASE_URL` in `.env` matches the Postgres credentials in `docker-compose.yml`.
3. Run database migrations if this is a fresh setup:

   ```bash
   alembic upgrade head
   ```

### Empty or Missing Knowledge Base

**Symptom:** `ira ask` returns "I don't have enough information" for questions that should be answerable.

**Fix:**

1. Check that documents exist in `data/imports/`:

   ```bash
   ls data/imports/
   ```

2. Run ingestion:

   ```bash
   ira ingest -v
   ```

3. If files were previously ingested but the Qdrant collection was lost (e.g. after a volume reset), force re-ingestion:

   ```bash
   ira ingest --force
   ```

### LLM API Errors

**Symptom:** Agent responses contain `(LLM call failed)` or similar placeholders.

**Fix:**

1. Verify your API key is set: `grep OPENAI_API_KEY .env`
2. Check your account has available credits/quota.
3. Run with verbose logging to see the full error: `ira ask "test query" -v`

### Telegram Alerts Not Arriving

**Symptom:** No alerts in the admin Telegram chat despite errors occurring.

**Fix:**

1. Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ADMIN_CHAT_ID` are set in `.env`.
2. Ensure the bot has been started (send `/start` to the bot in Telegram).
3. Verify the chat ID is correct -- send a message to the bot and check the update via the Telegram Bot API.

---

## 7. The Graduation Process

Graduation is the transition from **TRAINING** mode (Ira observes, you act) to **OPERATIONAL** mode (Ira acts autonomously on `ira@machinecraft.org`).

### What Changes After Graduation

| Aspect | Training Mode | Operational Mode |
|--------|--------------|-----------------|
| Email account | `rushabh@machinecraft.org` (read-only) | `ira@machinecraft.org` (read + write) |
| Gmail permissions | `gmail.readonly` | `gmail.modify`, `gmail.compose` |
| Email handling | Observe and learn only | Classify, draft replies, create Gmail drafts |
| Drip campaigns | Manual execution | Autonomous send via Gmail |

### Graduation Thresholds

Ira must meet **all three** criteria:

| Metric | Threshold | How to Check |
|--------|-----------|--------------|
| Total interactions | > 1,000 | `ira pipeline` or dashboard |
| Average feedback score | > 4.5 / 10 | Dashboard feedback trends |
| Procedures learned | >= 10 | Accumulated via training cycles |

### Running the Assessment

```bash
ira graduate
```

This prints a self-assessment table showing each metric, its current value, the threshold, and PASS/FAIL status.

**If all three pass:**

1. The `.env` file is updated: `IRA_EMAIL_MODE=OPERATIONAL` and `IRA_EMAIL=ira@machinecraft.org`.
2. The system automatically restarts via `scripts/stop.sh` and `scripts/start.sh`.
3. You will need to re-authenticate Google OAuth (see [Troubleshooting](#google-oauth-re-authentication)) since the new mode requires broader Gmail permissions.

**If any fail:**

The command exits with a message indicating which thresholds are not yet met. Continue the training workflow (email learning, training cycles, board meetings) until all criteria are satisfied.

### Recommended Pre-Graduation Checklist

1. Run a thorough training cycle: `ira train --scenarios 10`
2. Verify the health of all services: `ira health`
3. Review the dashboard for any concerning trends.
4. Ensure `data/imports/` has comprehensive, up-to-date documents.
5. Run a final ingestion: `ira ingest`
6. Run a dream cycle to consolidate recent learnings: `ira dream`
7. Run the graduation: `ira graduate`
