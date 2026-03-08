#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting Ira..."
exec uvicorn ira.interfaces.server:app \
    --host 0.0.0.0 --port 8000 \
    --limit-concurrency 5 --timeout-keep-alive 30 \
    "$@"
