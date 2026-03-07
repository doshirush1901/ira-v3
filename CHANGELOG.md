# Changelog

All notable changes to Ira are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
