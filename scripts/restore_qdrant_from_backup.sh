#!/usr/bin/env bash
# Restore Qdrant storage from backup (e.g. data/qdrant.bak.20260314092051).
# Run from project root. Stops Qdrant, replaces data/qdrant with backup contents, starts Qdrant.

set -e
cd "$(git rev-parse --show-toplevel)"
BACKUP="${1:-data/qdrant.bak.20260314092051}"

if [[ ! -d "$BACKUP" ]]; then
  echo "Backup not found: $BACKUP"
  echo "Usage: $0 [path_to_backup_dir]"
  exit 1
fi

echo "Stopping Qdrant..."
docker compose -f docker-compose.local.yml stop qdrant 2>/dev/null || true

echo "Replacing data/qdrant with backup (move = instant)..."
if [[ -d data/qdrant ]]; then
  mv data/qdrant "data/qdrant.before_restore.$(date +%Y%m%d%H%M%S)"
fi
mv "$BACKUP" data/qdrant

echo "Starting Qdrant..."
docker compose -f docker-compose.local.yml start qdrant

echo "Done. Run: poetry run ira takeout verify"
echo "To confirm takeout points: poetry run ira takeout verify"
