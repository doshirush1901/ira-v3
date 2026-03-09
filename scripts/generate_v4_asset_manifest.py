from __future__ import annotations

import csv
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "docs" / "v4"
OUTPUT_CSV = OUTPUT_DIR / "asset_decision_manifest.csv"
OUTPUT_MD = OUTPUT_DIR / "asset_decision_summary.md"


@dataclass(frozen=True)
class AssetDecision:
    owner: str
    decision: str
    target: str
    risk: str
    rationale: str


def _git_untracked_paths() -> list[str]:
    output = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        text=True,
    )
    raw_paths = [line[3:] for line in output.splitlines() if line.startswith("?? ")]
    return sorted(raw_paths)


def _expand_paths(paths: Iterable[str]) -> list[Path]:
    expanded: list[Path] = []
    for rel in paths:
        absolute = REPO_ROOT / rel
        if absolute.is_dir():
            for root, _, files in os.walk(absolute):
                root_path = Path(root)
                for file_name in files:
                    expanded.append(root_path / file_name)
        elif absolute.is_file():
            expanded.append(absolute)
    return sorted(expanded)


def _classify(path: Path) -> AssetDecision:
    rel = path.relative_to(REPO_ROOT).as_posix()

    if rel.startswith("core_modules/"):
        high_value = {
            "api_rate_limiter.py",
            "structured_logger.py",
            "knowledge_hygiene.py",
            "reindex_docs.py",
            "email_reindex.py",
            "company_config.py",
        }
        if path.name in high_value:
            return AssetDecision(
                owner="platform",
                decision="port_pattern",
                target="src/ira/services or src/ira/systems",
                risk="medium",
                rationale="High-value reliability/data-quality pattern from v2 archive.",
            )
        return AssetDecision(
            owner="platform",
            decision="archive",
            target="docs/archive/legacy-v2",
            risk="high",
            rationale="Legacy module overlaps v3 architecture; avoid direct runtime merge.",
        )

    if rel.startswith("legacy_pipelines/"):
        return AssetDecision(
            owner="platform",
            decision="archive",
            target="docs/archive/legacy-v2",
            risk="high",
            rationale="Monolithic legacy pipeline; v3 pipeline/pantheon already supersede it.",
        )

    if rel.startswith("one_off_scripts/"):
        if "/ingest/" in rel:
            return AssetDecision(
                owner="data_platform",
                decision="productize",
                target="src/ira/interfaces + src/ira/brain ingestion jobs",
                risk="medium",
                rationale="Useful adapter patterns; consolidate under governed ingestion framework.",
            )
        return AssetDecision(
            owner="operations",
            decision="archive",
            target="docs/archive/one-off-scripts",
            risk="high",
            rationale="One-time script or person-specific workflow; keep out of runtime path.",
        )

    if rel.startswith("scripts/"):
        if path.name.startswith("send_"):
            return AssetDecision(
                owner="operations",
                decision="productize",
                target="src/ira/systems/outbound_approvals.py",
                risk="high",
                rationale="Direct-send behavior must be approval-gated and audited.",
            )
        if path.suffix == ".html":
            return AssetDecision(
                owner="operations",
                decision="productize",
                target="prompts/ + governed templates",
                risk="medium",
                rationale="Reusable messaging templates should be managed centrally.",
            )
        return AssetDecision(
            owner="operations",
            decision="runbook",
            target="scripts/",
            risk="low",
            rationale="Operational utility script can remain as controlled runbook.",
        )

    if rel.startswith("skills/"):
        return AssetDecision(
            owner="platform",
            decision="archive",
            target="docs/archive/legacy-skills-v2",
            risk="medium",
            rationale="Legacy file-based skills not wired into v3 runtime skill matrix.",
        )

    if rel.startswith("data/"):
        if any(token in rel for token in ("/attachments/", "/newsletter_archive/", "/manus_outputs/")):
            return AssetDecision(
                owner="data_governance",
                decision="move_external",
                target="object_storage + metadata index",
                risk="high",
                rationale="Binary or generated artifacts should not be stored in runtime git tree.",
            )
        if rel.startswith("data/knowledge/"):
            return AssetDecision(
                owner="data_governance",
                decision="move_external",
                target="managed knowledge store with retention",
                risk="high",
                rationale="Timestamped snapshots are derived data with stale-data risk.",
            )
        if rel.startswith("data/themis/"):
            return AssetDecision(
                owner="themis",
                decision="move_external",
                target="encrypted HR storage",
                risk="high",
                rationale="HR/payroll artifacts require stricter access controls.",
            )
        return AssetDecision(
            owner="data_governance",
            decision="review",
            target="data lifecycle policy",
            risk="medium",
            rationale="Data asset requires classification before runtime use.",
        )

    return AssetDecision(
        owner="platform",
        decision="review",
        target="manual triage",
        risk="medium",
        rationale="Unclassified asset requires manual review.",
    )


def _write_manifest(rows: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "asset",
                "owner",
                "decision",
                "target",
                "risk",
                "status",
                "rationale",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_summary(rows: list[dict[str, str]]) -> None:
    by_decision: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for row in rows:
        by_decision[row["decision"]] = by_decision.get(row["decision"], 0) + 1
        by_risk[row["risk"]] = by_risk.get(row["risk"], 0) + 1

    lines = [
        "# v4 Asset Decision Summary",
        "",
        f"Total assets triaged: **{len(rows)}**",
        "",
        "## Decision counts",
    ]
    for decision, count in sorted(by_decision.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{decision}`: {count}")

    lines.append("")
    lines.append("## Risk counts")
    for risk, count in sorted(by_risk.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{risk}`: {count}")

    lines.append("")
    lines.append("Generated by `scripts/generate_v4_asset_manifest.py`.")
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    tracked = _git_untracked_paths()
    expanded = _expand_paths(tracked)
    rows: list[dict[str, str]] = []
    for file_path in expanded:
        rel = file_path.relative_to(REPO_ROOT).as_posix()
        decision = _classify(file_path)
        rows.append(
            {
                "asset": rel,
                "owner": decision.owner,
                "decision": decision.decision,
                "target": decision.target,
                "risk": decision.risk,
                "status": "pending",
                "rationale": decision.rationale,
            }
        )
    _write_manifest(rows)
    _write_summary(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
