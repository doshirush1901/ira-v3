# Ira v4 Data Lifecycle Policy

This policy governs migrated v2 archive assets and all new runtime data.

## Data classes

- `authoritative`: system-of-record business data.
- `derived`: generated outputs from authoritative data.
- `cache`: recomputable retrieval/processing state.
- `log`: append-only operational evidence.
- `binary_evidence`: raw attachments and large artifacts.

## Storage rules

- `authoritative` -> PostgreSQL/CRM or approved system store.
- `derived` and `cache` -> object storage or managed stores with retention.
- `log` -> append-only store with retention + access control.
- `binary_evidence` -> object storage with metadata pointers in DB.

## Repository rules

- Runtime repository keeps only small, non-sensitive fixtures.
- Sensitive or heavy paths are ignored by git and moved externally.
- Archived v2 assets are marked non-runtime and cannot be imported by `src/ira`.

## Retention defaults

- Contact and communication extracts: 90 days unless promoted to CRM.
- Generated campaign artifacts: 30 to 90 days.
- Knowledge snapshots: keep rolling latest N, purge stale versions.
- Audit logs: 180 days minimum.

## Required metadata for stored artifacts

- `source`
- `owner`
- `ingested_at`
- `classification`
- `retention_days`
- `sensitivity`
