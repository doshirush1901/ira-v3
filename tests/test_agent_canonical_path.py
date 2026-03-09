from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src" / "ira"
GITIGNORE_FILE = ROOT / ".gitignore"


def _has_legacy_import(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "data.agents" or alias.name.startswith("data.agents."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "data.agents" or module.startswith("data.agents."):
                return True
    return False


def test_runtime_code_does_not_import_legacy_data_agents() -> None:
    offenders: list[str] = []
    for py_file in SRC_DIR.rglob("*.py"):
        if _has_legacy_import(py_file):
            offenders.append(str(py_file.relative_to(ROOT)))

    assert not offenders, (
        "Runtime must only use src/ira/agents. "
        f"Found legacy imports: {', '.join(sorted(offenders))}"
    )


def test_legacy_agents_tree_is_quarantined_in_gitignore() -> None:
    assert GITIGNORE_FILE.exists(), ".gitignore must exist at repository root"
    lines = {line.strip() for line in GITIGNORE_FILE.read_text(encoding="utf-8").splitlines()}
    assert "data/agents/" in lines, (
        "Legacy `data/agents/` must be quarantined to avoid accidental tracking."
    )
