from __future__ import annotations

import csv
import sys
from pathlib import Path

from ira.systems.legacy_guard import scan_runtime_for_legacy_imports


REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_legacy_imports() -> tuple[bool, str]:
    violations = scan_runtime_for_legacy_imports()
    if violations:
        sample = violations[0]
        return (
            False,
            f"legacy import detected: {sample.import_name} in {sample.file_path}:{sample.line_number}",
        )
    return (True, "no legacy runtime imports")


def _check_manifest() -> tuple[bool, str]:
    manifest = REPO_ROOT / "docs" / "v4" / "asset_decision_manifest.csv"
    if not manifest.exists():
        return (False, "asset manifest missing")
    with manifest.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return (False, "asset manifest is empty")
    return (True, f"asset manifest rows={len(rows)}")


def _check_policy_docs() -> tuple[bool, str]:
    required = [
        REPO_ROOT / "docs" / "v4" / "data_lifecycle_policy.md",
        REPO_ROOT / "docs" / "v4" / "script_productization_matrix.md",
    ]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        return (False, f"missing docs: {', '.join(missing)}")
    return (True, "data + script governance docs present")


def _check_outbound_endpoints() -> tuple[bool, str]:
    server = (REPO_ROOT / "src" / "ira" / "interfaces" / "server.py").read_text(encoding="utf-8")
    required = [
        '/api/outbound/campaigns/draft',
        '/api/outbound/campaigns/approve',
    ]
    missing = [route for route in required if route not in server]
    if missing:
        return (False, f"missing endpoints: {', '.join(missing)}")
    return (True, "outbound approval endpoints present")


def main() -> None:
    checks = [
        ("legacy_imports", _check_legacy_imports),
        ("manifest", _check_manifest),
        ("policy_docs", _check_policy_docs),
        ("outbound_endpoints", _check_outbound_endpoints),
    ]
    failed = False
    for name, check in checks:
        ok, detail = check()
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        failed = failed or (not ok)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
