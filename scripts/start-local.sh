#!/usr/bin/env bash
# Start Ira local dev stack (DBs only). No API server. Use from repo root or any subdir.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.local.yml up -d
echo "Ira local stack up (Postgres, Qdrant, Neo4j, Redis). Use: poetry run ira ask \"<question>\" --json"
