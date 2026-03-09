# Ira v4 Script Productization Matrix

This matrix defines how newly migrated scripts are handled.

## Categories

- `runbook_utility`: low-risk read/analyze helper script.
- `productize`: convert into API/system/CLI with approvals and audit.
- `archive`: person-specific or one-time script; not part of runtime.

## Priority productization tracks

1. Outbound campaign scripts (`scripts/send_*.py`) -> approval-gated batch drafts via `/api/outbound/campaigns/*`.
2. Case study and inbox extraction scripts -> governed ingestion/extraction pipeline with retention controls.
3. Reindex and cleanup scripts -> controlled maintenance jobs, not ad hoc direct execution.

## Mandatory controls for productized flows

- Human approval before any external send operation.
- Audit record for all draft or send actions.
- Recipient/domain policy checks.
- Idempotency key or batch identifier for replay safety.
- Environment-driven configuration only (no in-code recipient defaults).
