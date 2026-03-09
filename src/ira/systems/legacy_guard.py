"""Guards against accidental runtime usage of archived v2 assets."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = REPO_ROOT / "src" / "ira"
LEGACY_PREFIXES = (
    "core_modules",
    "legacy_pipelines",
    "one_off_scripts",
    "skills",
)


@dataclass(frozen=True)
class LegacyImportViolation:
    file_path: str
    line_number: int
    import_name: str


def _is_legacy_import(import_name: str) -> bool:
    return import_name.startswith(LEGACY_PREFIXES)


def scan_runtime_for_legacy_imports(
    root: Path | None = None,
) -> list[LegacyImportViolation]:
    """Scan runtime Python modules for imports from archived v2 trees."""
    runtime_root = root or RUNTIME_ROOT
    violations: list[LegacyImportViolation] = []

    for py_file in runtime_root.rglob("*.py"):
        if py_file.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        try:
            rel_path = py_file.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_path = py_file.as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_legacy_import(alias.name):
                        violations.append(
                            LegacyImportViolation(
                                file_path=rel_path,
                                line_number=node.lineno,
                                import_name=alias.name,
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if _is_legacy_import(node.module):
                    violations.append(
                        LegacyImportViolation(
                            file_path=rel_path,
                            line_number=node.lineno,
                            import_name=node.module,
                        )
                    )

    return violations


def enforce_legacy_quarantine(strict: bool = False) -> list[LegacyImportViolation]:
    """Return violations and raise in strict mode."""
    violations = scan_runtime_for_legacy_imports()
    if strict and violations:
        first = violations[0]
        raise RuntimeError(
            "Legacy quarantine violation: "
            f"{first.import_name} imported in {first.file_path}:{first.line_number}"
        )
    return violations
