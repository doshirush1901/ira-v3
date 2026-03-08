#!/bin/bash
# Project Shakti — Daily Training Cycle
#
# Run this each morning to sync emails, ingest new documents,
# and prepare Ira for the day's interactions.
#
# After running, use:
#   ira ask "..."                    — test Ira's knowledge
#   ira learn-from-cursor --query "..." --response "..." --correction "..."
#                                    — correct mistakes
#   ira graduate                     — check readiness for OPERATIONAL mode

set -e

echo "=== Project Shakti Training Cycle ==="
echo ""

echo "1/3  Syncing emails from inbox..."
poetry run ira email sync
echo ""

echo "2/3  Running morning ingestion (inhale)..."
poetry run ira system inhale
echo ""

echo "3/3  Training cycle complete."
echo ""
echo "Next steps:"
echo "  - Use 'ira ask \"...\"' to test knowledge"
echo "  - Use 'ira learn-from-cursor' to provide corrections"
echo "  - Use 'ira graduate' to check readiness"
