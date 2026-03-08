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

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 ira && \
    useradd --uid 1000 --gid ira --create-home ira

WORKDIR /app

COPY --from=builder /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"

COPY src/ src/
COPY prompts/ prompts/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/entrypoint.sh .

RUN mkdir -p /app/data/brain /app/data/imports /app/data/quotes /app/data/reports \
    && chmod +x /app/entrypoint.sh \
    && chown -R ira:ira /app

USER ira
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
