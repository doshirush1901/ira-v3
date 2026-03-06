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
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


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
