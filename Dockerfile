FROM python:3.11-slim-bullseye AS builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1

RUN pip install --no-cache-dir poetry

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-dev --no-root

# ── final image ───────────────────────────────────────────────────────────
FROM python:3.11-slim-bullseye

RUN groupadd --gid 1000 ira && \
    useradd --uid 1000 --gid ira --create-home ira

WORKDIR /app

COPY --from=builder /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ src/
COPY prompts/ prompts/
COPY alembic/ alembic/
COPY alembic.ini .

RUN chown -R ira:ira /app
USER ira

EXPOSE 8000

CMD ["uvicorn", "ira.interfaces.server:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "5", "--timeout-keep-alive", "30"]
