# Contributing to Ira v3

## Prerequisites

- Python 3.11+
- Poetry (`pip install poetry`)
- Docker & Docker Compose (for local infrastructure)
- (Optional) [pre-commit](https://pre-commit.com/) for automated linting

## Setup

```bash
# Install dependencies
poetry install

# Start infrastructure (Qdrant, Neo4j, PostgreSQL, Redis)
docker compose -f docker-compose.local.yml up -d

# Run database migrations
alembic upgrade head

# Copy environment template and fill in API keys
cp .env.example .env

# Install pre-commit hooks (recommended)
pre-commit install
```

## Running

```bash
# CLI mode
poetry run ira chat

# FastAPI server
poetry run uvicorn ira.interfaces.server:app --reload

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=ira

# Lint
poetry run ruff check src/ tests/

# Format
poetry run ruff format src/ tests/
```

## Project Structure

```
src/ira/
  agents/       # 24 specialist agents + BaseAgent
  brain/        # Knowledge retrieval, embeddings, entity extraction,
                #   guardrails, pricing, routing (30 modules)
  data/         # CRM models, quote models
  interfaces/   # CLI, server, email, dashboard, cursor feedback
  memory/       # Conversation, episodic, relationship, goals
  services/     # LLMClient (OpenAI + Anthropic with Langfuse tracing)
  schemas/      # Pydantic models for structured LLM outputs
  systems/      # Body-system metaphor (20 modules)
  pipeline.py   # 11-stage request pipeline
  pantheon.py   # Agent orchestrator
prompts/        # LLM prompt templates (68 files)
tests/          # pytest test suite (23 files)
alembic/        # Database migrations
```

## Creating a New Agent

1. Create `src/ira/agents/{name}.py` inheriting from `BaseAgent`.
2. Set `name`, `role`, `description`, and `knowledge_categories` class attributes.
3. Implement `_register_tools()` to add custom tools via `self.register_tool()`.
4. Implement `handle()` -- typically call `await self.run(query, context)` to use the ReAct loop.
5. Create `prompts/{name}_system.txt` with the agent's system prompt.
6. Register the class in `src/ira/pantheon.py` by adding it to `_AGENT_CLASSES`.
7. Write tests in `tests/test_agents.py`.

## Code Style

- Use `from __future__ import annotations` in every module.
- Use stdlib `logging`, not structlog.
- Type-hint all public functions.
- LLM calls go through `LLMClient` (`src/ira/services/llm_client.py`). Use `generate_text()` for plain text and `generate_structured()` with a Pydantic model for JSON. All calls are auto-traced via Langfuse.
- **Linting and formatting** are enforced by [Ruff](https://github.com/astral-sh/ruff). Run `poetry run ruff check --fix src/ tests/` to auto-fix.
- **Pre-commit hooks** run ruff automatically on every commit if installed.
- **Evaluation** — run `poetry run pytest tests/test_eval.py` for the deepeval suite, or `npx promptfoo eval` for prompt regression testing.
- See `AGENTS.md` for full conventions.

## Testing

- Run the full suite: `poetry run pytest`
- Run with coverage: `poetry run pytest --cov=ira`
- Run a specific file: `poetry run pytest tests/test_agents.py`
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`.
- Shared fixtures live in `tests/conftest.py` (`mock_settings`, `sample_contact`, `sample_email`, etc.).
- Mock all external services (LLM APIs, Qdrant, Neo4j, Mem0) in tests.

## Database Migrations

After changing models in `src/ira/data/crm.py` or `src/ira/data/quotes.py`:

```bash
# Generate a new migration
alembic revision --autogenerate -m "description of change"

# Apply migrations
alembic upgrade head
```

## Troubleshooting

**`ConnectionRefusedError` on Qdrant (port 6333)**
Qdrant is not running. Start infrastructure with `docker compose -f docker-compose.local.yml up -d` and wait for the health check to pass.

**`ServiceUnavailable` from Neo4j**
Neo4j takes ~30 seconds to start. Check `docker compose logs neo4j` for readiness. Ensure `NEO4J_AUTH` matches your `.env` file (default: `neo4j/ira_knowledge_graph`).

**`OperationalError: could not connect to server` from PostgreSQL**
Postgres is not running or the connection string is wrong. Verify `DATABASE_URL` in `.env` matches the compose config (default: `postgresql+asyncpg://ira:ira@localhost:5432/ira_crm`).

**`ModuleNotFoundError: No module named 'mem0'`**
Run `poetry install` to install all dependencies including `mem0ai`. If the Mem0 API key is not set, the system gracefully degrades -- the import is guarded.

**`FAILED alembic upgrade head` with "target database is not up to date"**
Run `alembic stamp head` to mark the current state, then retry. This happens when tables were created by `create_tables()` before migrations existed.

**Tests fail with `asyncio` errors**
Ensure `pytest-asyncio >= 0.23` is installed and `asyncio_mode = "auto"` is set in `pyproject.toml` under `[tool.pytest.ini_options]`.
