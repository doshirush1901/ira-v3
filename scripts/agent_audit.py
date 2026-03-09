#!/usr/bin/env python3
"""Audit Ira agent consistency across code, prompts, and registries.

Usage:
    python scripts/agent_audit.py
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "src" / "ira" / "agents"
SRC_DIR = ROOT / "src" / "ira"
PROMPTS_DIR = ROOT / "prompts"
PANTHEON_FILE = ROOT / "src" / "ira" / "pantheon.py"
AGENTS_INIT = AGENTS_DIR / "__init__.py"
GITIGNORE_FILE = ROOT / ".gitignore"
LEGACY_AGENTS_DIR = ROOT / "data" / "agents"


@dataclass(slots=True)
class AgentReport:
    class_name: str
    file_name: str
    path: Path
    name: str | None = None
    role: str | None = None
    description: str | None = None
    has_knowledge_categories: bool = False
    has_handle: bool = False
    uses_run: bool = False
    prompt_exists: bool = False
    issues: list[str] = field(default_factory=list)


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse_agent_file(path: Path) -> AgentReport | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_nodes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    for cls in class_nodes:
        base_names = {getattr(base, "id", None) for base in cls.bases}
        if "BaseAgent" not in base_names:
            continue

        rep = AgentReport(class_name=cls.name, file_name=path.stem, path=path)
        for node in cls.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "name":
                        rep.name = _literal_str(node.value)
                    elif target.id == "role":
                        rep.role = _literal_str(node.value)
                    elif target.id == "description":
                        rep.description = _literal_str(node.value)
                    elif target.id == "knowledge_categories":
                        rep.has_knowledge_categories = True
            elif isinstance(node, ast.AsyncFunctionDef) and node.name == "handle":
                rep.has_handle = True
                rep.uses_run = any(
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "self"
                    and inner.func.attr == "run"
                    for inner in ast.walk(node)
                )

        if rep.name is None:
            rep.issues.append("missing class attribute: name")
        if rep.role is None:
            rep.issues.append("missing class attribute: role")
        if rep.description is None:
            rep.issues.append("missing class attribute: description")
        if not rep.has_knowledge_categories:
            rep.issues.append("missing class attribute: knowledge_categories")
        if not rep.has_handle:
            rep.issues.append("missing async handle()")
        if rep.name and rep.name != rep.file_name:
            rep.issues.append(f"name/file mismatch ({rep.name} != {rep.file_name})")

        if rep.name:
            rep.prompt_exists = (PROMPTS_DIR / f"{rep.name}_system.txt").exists()
            if not rep.prompt_exists:
                rep.issues.append(f"missing prompt file: prompts/{rep.name}_system.txt")

        return rep
    return None


def _scan_agents() -> list[AgentReport]:
    reports: list[AgentReport] = []
    for path in sorted(AGENTS_DIR.glob("*.py")):
        if path.name in {"__init__.py", "base_agent.py"}:
            continue
        rep = _parse_agent_file(path)
        if rep is not None:
            reports.append(rep)
    return reports


def _extract_pantheon_class_names() -> set[str]:
    tree = ast.parse(PANTHEON_FILE.read_text(encoding="utf-8"), filename=str(PANTHEON_FILE))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "_AGENT_CLASSES":
            continue
        if isinstance(node.value, ast.List):
            for elt in node.value.elts:
                if isinstance(elt, ast.Name):
                    names.add(elt.id)
    return names


def _extract_agents_all() -> set[str]:
    tree = ast.parse(AGENTS_INIT.read_text(encoding="utf-8"), filename=str(AGENTS_INIT))
    exported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(node.value, ast.List):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            exported.add(elt.value)
    return exported


def _scan_for_legacy_agent_imports() -> list[str]:
    """Return source files that import deprecated data.agents modules."""
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "data.agents" or alias.name.startswith("data.agents."):
                        offenders.append(str(path.relative_to(ROOT)))
                        break
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "data.agents" or module.startswith("data.agents."):
                    offenders.append(str(path.relative_to(ROOT)))
                    break

    return sorted(set(offenders))


def _gitignore_contains(pattern: str) -> bool:
    if not GITIGNORE_FILE.exists():
        return False
    lines = [line.strip() for line in GITIGNORE_FILE.read_text(encoding="utf-8").splitlines()]
    return pattern in lines


def main() -> int:
    reports = _scan_agents()
    pantheon_classes = _extract_pantheon_class_names()
    exported = _extract_agents_all()

    by_class = {r.class_name for r in reports}
    by_name = {r.name for r in reports if r.name}
    issues: list[str] = []

    missing_in_pantheon = sorted(by_class - pantheon_classes)
    extra_in_pantheon = sorted(pantheon_classes - by_class)
    missing_exports = sorted(by_class - exported - {"BaseAgent"})

    print("Ira Agent Audit")
    print("=" * 72)
    print(f"Discovered runtime agents: {len(reports)}")
    print(f"Pantheon registered:      {len(pantheon_classes)}")
    print(f"Exports in __all__:       {len(exported)}")
    print()
    print("Per-agent checks:")

    for rep in sorted(reports, key=lambda r: (r.name or "", r.class_name)):
        status = "OK" if not rep.issues else "ISSUES"
        print(
            f"- {rep.name or rep.class_name:12} [{status}] "
            f"role={'Y' if rep.role else 'N'} "
            f"desc={'Y' if rep.description else 'N'} "
            f"kcats={'Y' if rep.has_knowledge_categories else 'N'} "
            f"handle={'Y' if rep.has_handle else 'N'} "
            f"run={'Y' if rep.uses_run else 'N'} "
            f"prompt={'Y' if rep.prompt_exists else 'N'}"
        )
        for issue in rep.issues:
            issues.append(f"{rep.path.relative_to(ROOT)}: {issue}")

    print()
    print("Cross-file consistency:")
    if missing_in_pantheon:
        issues.append(f"Missing in pantheon registry: {', '.join(missing_in_pantheon)}")
        print(f"- Missing in pantheon: {', '.join(missing_in_pantheon)}")
    else:
        print("- Pantheon registry coverage: OK")

    if extra_in_pantheon:
        issues.append(f"Extra in pantheon registry: {', '.join(extra_in_pantheon)}")
        print(f"- Extra in pantheon: {', '.join(extra_in_pantheon)}")
    else:
        print("- Pantheon extra entries: OK")

    if missing_exports:
        issues.append(f"Missing in ira.agents.__all__: {', '.join(missing_exports)}")
        print(f"- Missing exports: {', '.join(missing_exports)}")
    else:
        print("- ira.agents exports: OK")

    missing_prompt_names = sorted(
        name for name in by_name
        if not (PROMPTS_DIR / f"{name}_system.txt").exists()
    )
    if missing_prompt_names:
        issues.append(f"Missing prompt files for: {', '.join(missing_prompt_names)}")
        print(f"- Missing prompts: {', '.join(missing_prompt_names)}")
    else:
        print("- Prompt coverage: OK")

    legacy_imports = _scan_for_legacy_agent_imports()
    if legacy_imports:
        issues.append(f"Deprecated imports from data.agents found in: {', '.join(legacy_imports)}")
        print(f"- Deprecated imports found: {', '.join(legacy_imports)}")
    else:
        print("- Canonical import path (src/ira/agents only): OK")

    legacy_files = list(LEGACY_AGENTS_DIR.rglob("*.py")) if LEGACY_AGENTS_DIR.exists() else []
    if legacy_files:
        if _gitignore_contains("data/agents/"):
            print(f"- Legacy tree detected: data/agents/ ({len(legacy_files)} files, quarantined)")
        else:
            issues.append("Legacy data/agents/ exists but is not quarantined in .gitignore")
            print("- Legacy tree detected: data/agents/ (NOT quarantined)")
    else:
        print("- Legacy tree detected: none")

    print()
    if issues:
        print("Audit FAILED")
        for item in issues:
            print(f"  - {item}")
        return 1

    print("Audit PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
