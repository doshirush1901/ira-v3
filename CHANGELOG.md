# Changelog

All notable changes to Ira are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

(Nothing yet.)

## [3.3.2] - 2026-03-10

### Added
- **Cursor-as-Ira (CLI-first)** — Ira runs without starting the API server: Cursor starts Docker (DBs only), runs `ira ask "<query>" --json` and `ira task "<goal>" --json` from the project root; full stack runs in-process. Fallback workflow when CLI fails.
- **CLI `--json`** — `ira ask` and `ira task` support `--json` for machine-readable stdout.
- **CLI `ira task`** — Multi-phase task command using TaskOrchestrator; report to `data/reports/`, optional `--json` output.
- **Cursor rules & workflows index** — `docs/CURSOR_WORKFLOWS.md` indexes all custom workflows. Linked from README, GETTING_STARTED, docs/README.
- **Stable modes** — `docs/stable_modes.md` and `.cursor/rules/ira-stable-modes.mdc` for "add this to stable list" flow.
- **Path-agnostic rules** — Rules use `cd "$(git rev-parse --show-toplevel)"` so the repo works on any machine.
- **One-command local start** — `./scripts/start-local.sh` for DBs only; documented in README, GETTING_STARTED, scripts/README.

### Changed
- **Start Ira** — Docker only; no uvicorn or health-check steps in rules.
- **Query Ira** — Primary: `ira ask --json`; API optional when server running.
- **Complex tasks** — Primary: `ira task "<goal>" --json`; API task stream optional.
- **Docs** — README, AGENTS, GETTING_STARTED, CONTRIBUTING, ARCHITECTURE, WHY_IRA, scripts/README, src/ira/README, web-ui/README, .cursor/agents/ira.md updated for CLI-first and workflow index.
- **Stop Ira** — Path in rules use git repo root (path-agnostic).

## [3.3.1] - 2026-03-09

### Added
- README files for all key subdirectories: `src/ira/`, `src/ira/agents/`, `src/ira/brain/`, `src/ira/memory/`, `src/ira/systems/`, `prompts/`, `tests/`, `scripts/`, `alembic/`, `web-ui/`, `docs/`.
- Helicone LLM proxy support in `LLMClient` and `.env.example`.
- Firecrawl web scraping support in `config.py` and `.env.example`.
- Unstructured.io document parsing support in `config.py` and `.env.example`.
- Sentry error monitoring support in `config.py` and `.env.example`.
- Document AI invoice and form parser processor IDs in `.env.example`.

### Changed
- Root README updated: agent count 24 → 27, test count 24 → 28, memory count 9 → 10, added Mnemon/Gapper/Artemis to Pantheon table, added vendor and correction endpoints to API table.
- `docs/ARCHITECTURE.md` agent count updated to 27.
- `.gitignore` expanded with web-ui build artifacts and local config entries.
- `BaseAgent` enhanced with improved tool dispatch.
- `DocumentIngestor` enhanced with additional chunking options.

### Fixed
- Cleaned stray files from repo root (duplicate docs, backup files, orphaned PDFs moved to `docs/`).
- Removed duplicate `AGENTS.md` and `SOUL.md` from `data/imports/`.
- Purged `.DS_Store` files throughout the repository.

## [3.3.0] - 2026-03-08

### Added
- **Entity extractor** — GLiNER-based NER for contacts, companies, and machines (`brain/entity_extractor.py`).
- **Guardrails module** — Input validation and output safety checks (`brain/guardrails.py`).
- **Cursor feedback interface** — IDE-integrated correction flow (`interfaces/cursor_feedback.py`).
- **Eval harness** — deepeval-based evaluation suite (`tests/test_eval.py`) and promptfoo config for prompt regression testing.
- **Training scripts** — `scripts/shakti_train.sh` for fine-tuning workflows.
- **Stalled goal sweep** — `GoalManager.sweep_stalled_goals()` finds ACTIVE goals that haven't been updated.
- **Langfuse observability** — config placeholders in `.env.example` for LLM tracing.
- **New dependencies** — crawl4ai, docling, chonkie, deepeval, guardrails-ai, gliner.

### Changed
- **Vera** upgraded with structured fact-checking and KB cross-referencing.
- **Iris** upgraded with crawl4ai-based web search.
- **BaseAgent** ReAct loop improved with better tool dispatch and error recovery.
- **Deterministic router** now entity-aware for smarter routing.
- **Document ingestor** enhanced with docling/chonkie chunking pipeline.
- **Pricing, machine intelligence, and sales intelligence** modules refactored.
- **CLI** expanded with richer interactive commands.
- **Email processor** hardened with retry logic.
- **Respiratory system** expanded with health monitoring.
- **AdaptiveStyleTracker** and **PowerLevelTracker** now use async locks to prevent race conditions.
- Docker healthcheck URL fixed (`/health` → `/api/health`).
- Codebase grown to 106 source files, ~33,000 lines | 23 test files, ~10,600 lines | 68 prompt files.

### Fixed
- Docker healthcheck URL in `docker-compose.yml` pointed to wrong path.
- Race conditions in `AdaptiveStyleTracker.update_profile()` and `PowerLevelTracker.record_success/failure/training_boost`.

## [3.1.0] - 2026-03-07

### Added
- **Email tools for all agents** — `search_emails` and `read_email_thread` auto-registered in BaseAgent when the email processor is available.
- **5 new body systems** — Redis Cache, Document AI (OCR), DLP (PII redaction), Google Docs, PDF.co.
- **Shared identity** — SOUL.md preamble injected into every agent's system prompt via `load_soul_preamble()`.
- **SOUL.md** and **VISION.md** — single source of truth for Ira's identity and project direction.
- **New API endpoints** — `/api/email/search`, `/api/email/thread/{id}`, `/api/reingest-scanned`.
- **Voyage Rerank** as primary reranker (FlashRank as local fallback).
- **Redis** added to local infrastructure (response dedup, message stream persistence).
- **GitHub Actions CI** — lint (ruff) and test on every push and PR.
- **Pre-commit hooks** — ruff linting and formatting, trailing whitespace, YAML checks.
- **Ruff** configured for linting and formatting.
- **SECURITY.md**, **LICENSE**, **CHANGELOG.md**, **CODE_OF_CONDUCT.md**.
- **GitHub issue and PR templates**.
- **conftest.py** with shared test fixtures.

### Changed
- Pipeline diagram in README now shows all 11 stages including sub-stages.
- Brain diagram updated to show reranking and Redis caching layers.
- Body systems split into Core (6) and Extended (11) in documentation.
- `docs/ARCHITECTURE.md` fully updated to reflect current state.
- BaseAgent grown to ~920 lines with email tools and SOUL.md injection.

### Fixed
- Pipeline tests updated for tuple return format.
- Endocrine and Qdrant test mocks aligned with current APIs.

## [3.0.0] - 2026-02-15

### Added
- Initial v3 release with 24-agent pantheon.
- 11-stage request pipeline.
- 9 memory subsystems + dream mode.
- ReAct loops with up to 8 iterations for all agents.
- Automatic Anthropic fallback when OpenAI fails.
- Multi-backend retrieval (Qdrant + Neo4j + Mem0).
- CRM with PostgreSQL (companies, contacts, deals, quotes).
- FastAPI server, CLI, Telegram bot, email processor, dashboard.
- Document ingestion (PDF, DOCX, Excel, PPTX).
- Board meetings, drip campaigns, sales intelligence.
