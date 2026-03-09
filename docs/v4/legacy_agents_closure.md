# Legacy Agents Closure

## Decision

`src/ira/agents/` is the **only canonical runtime agent implementation path**.

The legacy tree under `data/agents/` is treated as archived reference material and is not used by the runtime pipeline, pantheon orchestration, or agent registry.

## Controls in Place

- `data/agents/` is quarantined in `.gitignore`.
- `scripts/agent_audit.py` checks for any runtime imports from `data.agents`.
- `tests/test_agent_canonical_path.py` fails CI if runtime code imports `data.agents` or quarantine is removed.
- CI now runs a dedicated smoke gate (`tests/test_query_smoke.py`) before the full test suite so deterministic routing regressions fail fast.

## Migration Rule

If code is needed from legacy modules:

1. Re-implement or port it into `src/ira/agents/` (or relevant `src/ira/*` system module).
2. Add/update tests under `tests/`.
3. Update coverage/audit checks when new capabilities are introduced.

Direct runtime imports from `data/agents` are prohibited.
