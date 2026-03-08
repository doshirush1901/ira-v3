"""Centralised prompt loader for Ira.

Reads ``.txt`` prompt files from the ``prompts/`` directory at the
repository root.  Prompts are cached on first access so the filesystem
is hit only once per process.

Usage::

    from ira.prompt_loader import load_prompt

    _SYSTEM_PROMPT = load_prompt("athena_system")
    # -> reads  prompts/athena_system.txt
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _REPO_ROOT / "prompts"
_SOUL_PATH = _REPO_ROOT / "SOUL.md"


@functools.lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the contents of ``prompts/{name}.txt``, stripped of trailing whitespace.

    Raises :class:`FileNotFoundError` with a helpful message if the
    file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path}  "
            f"(looked in {_PROMPTS_DIR})"
        )
    return path.read_text(encoding="utf-8").rstrip()


@functools.lru_cache(maxsize=1)
def load_soul_preamble() -> str:
    """Load the Identity, Voice, and Behavioral Boundaries sections from SOUL.md.

    Returns an empty string if SOUL.md is missing so the system
    degrades gracefully.
    """
    if not _SOUL_PATH.exists():
        logger.warning("SOUL.md not found at %s — agents will run without shared identity", _SOUL_PATH)
        return ""

    text = _SOUL_PATH.read_text(encoding="utf-8")

    sections: list[str] = []
    capture = False
    current: list[str] = []

    for line in text.splitlines():
        if line.startswith("## ") and any(
            keyword in line for keyword in ("Identity", "Philosophical Foundation", "Voice", "Behavioral Boundaries")
        ):
            if current and capture:
                sections.append("\n".join(current))
            current = [line]
            capture = True
        elif line.startswith("## ") and capture:
            sections.append("\n".join(current))
            current = []
            capture = False
        elif capture:
            current.append(line)

    if current and capture:
        sections.append("\n".join(current))

    if not sections:
        return ""

    return "--- IRA CORE IDENTITY ---\n" + "\n\n".join(sections) + "\n--- END CORE IDENTITY ---"
