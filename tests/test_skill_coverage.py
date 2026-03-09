from __future__ import annotations

import ast
from pathlib import Path

from ira.skills.coverage import AGENT_SKILL_COVERAGE, validate_coverage


ROOT = Path(__file__).resolve().parents[1]
PANTHEON_FILE = ROOT / "src" / "ira" / "pantheon.py"
AGENTS_DIR = ROOT / "src" / "ira" / "agents"


def _runtime_agent_names() -> set[str]:
    tree = ast.parse(PANTHEON_FILE.read_text(encoding="utf-8"), filename=str(PANTHEON_FILE))
    class_names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "_AGENT_CLASSES":
            continue
        if isinstance(node.value, ast.List):
            for elt in node.value.elts:
                if isinstance(elt, ast.Name):
                    class_names.add(elt.id)
    return {name.lower() for name in class_names}


def test_skill_coverage_has_all_runtime_agents() -> None:
    assert set(AGENT_SKILL_COVERAGE) == _runtime_agent_names()


def test_skill_coverage_references_known_skills() -> None:
    assert validate_coverage() == []


def test_required_skills_have_handlers() -> None:
    import ira.skills.handlers as handlers

    missing: list[str] = []
    for agent, profile in AGENT_SKILL_COVERAGE.items():
        for skill in profile.required:
            if not callable(getattr(handlers, skill, None)):
                missing.append(f"{agent}:{skill}")
    assert not missing, f"Missing required handlers: {', '.join(sorted(missing))}"


def _explicit_agent_skills(agent_name: str) -> set[str]:
    path = AGENTS_DIR / f"{agent_name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skills: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "use_skill"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            skills.add(node.args[0].value)
    return skills


def test_all_agents_wire_required_skills_explicitly() -> None:
    missing: list[str] = []

    for agent in sorted(AGENT_SKILL_COVERAGE):
        required = set(AGENT_SKILL_COVERAGE[agent].required)
        wired = _explicit_agent_skills(agent)
        for skill in sorted(required - wired):
            missing.append(f"{agent}:{skill}")

    assert not missing, (
        "All agents must explicitly wire required skills via self.use_skill(). "
        f"Missing: {', '.join(missing)}"
    )
