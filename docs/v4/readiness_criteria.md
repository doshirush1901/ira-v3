# Ira v4 Readiness Criteria

Use `python scripts/v4_readiness_gate.py` to validate minimum migration gates.

## Required gates

- No runtime imports from `core_modules`, `legacy_pipelines`, `one_off_scripts`, or legacy `skills`.
- Asset decision manifest exists and is populated.
- Data lifecycle and script productization policies are present.
- Outbound campaign workflow uses approval-gated endpoints:
  - `/api/outbound/campaigns/draft`
  - `/api/outbound/campaigns/approve`

## Rollout recommendation

1. Shadow mode in internal environment.
2. Internal default with restricted approvals.
3. Full production enablement after one stable cycle.
