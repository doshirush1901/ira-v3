#!/bin/bash
set -e

# Ensure data subdirectories exist (volume mount replaces build-time dirs)
mkdir -p /app/data/brain /app/data/imports /app/data/quotes /app/data/reports

# Fix Railway's postgresql:// to postgresql+asyncpg:// for SQLAlchemy async
if [ -n "$DATABASE_URL" ]; then
  export DATABASE_URL="${DATABASE_URL/postgresql:\/\//postgresql+asyncpg:\/\/}"
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting Ira..."
exec uvicorn ira.interfaces.server:app \
    --host 0.0.0.0 --port "${PORT:-8000}" \
    --limit-concurrency 5 --timeout-keep-alive 30 \
    "$@"
