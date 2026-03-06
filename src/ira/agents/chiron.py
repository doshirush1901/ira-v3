"""Chiron -- Sales Trainer agent.

Maintains a library of sales training patterns (trigger situations,
wrong approaches, right approaches) and provides contextual coaching
notes for live sales situations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("chiron_system")
_DATA_PATH = Path("data/brain/sales_training.json")


def _load_patterns() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        return []
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        return data.get("patterns", [])
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read sales training data at %s", _DATA_PATH)
        return []


def _save_patterns(patterns: list[dict[str, Any]]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DATA_PATH.write_text(
        json.dumps({"patterns": patterns}, indent=2, default=str),
        encoding="utf-8",
    )


def _next_pattern_id(patterns: list[dict[str, Any]]) -> str:
    max_num = 0
    for p in patterns:
        pid = p.get("id", "")
        if pid.startswith("ST-"):
            try:
                max_num = max(max_num, int(pid[3:]))
            except ValueError:
                pass
    return f"ST-{max_num + 1:03d}"


class Chiron(BaseAgent):
    name = "chiron"
    role = "Sales Trainer"
    description = "Sales training patterns, coaching notes, and situational guidance"

    async def log_pattern(
        self,
        trigger: str,
        wrong: str,
        right: str,
        category: str,
    ) -> str:
        patterns = _load_patterns()
        pattern_id = _next_pattern_id(patterns)
        patterns.append({
            "id": pattern_id,
            "trigger": trigger,
            "wrong_approach": wrong,
            "right_approach": right,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_patterns(patterns)
        logger.info("Sales training pattern %s logged (category: %s)", pattern_id, category)
        return f"Training pattern {pattern_id} recorded under '{category}'."

    async def get_coaching_notes(self, context: str) -> str:
        patterns = _load_patterns()
        if not patterns:
            return "No training patterns recorded yet."

        pattern_text = "\n".join(
            f"- [{p['id']}] Trigger: {p['trigger']} | Right: {p['right_approach']}"
            for p in patterns
        )

        prompt = (
            "Given the following sales situation, find the most relevant training "
            "patterns and provide actionable coaching notes.\n\n"
            f"SITUATION:\n{context}\n\n"
            f"AVAILABLE PATTERNS:\n{pattern_text}"
        )
        return await self.call_llm(_SYSTEM_PROMPT, prompt)

    async def get_sales_guidance(self) -> str:
        patterns = _load_patterns()
        if not patterns:
            return ""

        lines = ["Sales Training Guidance:"]
        by_category: dict[str, list[dict[str, Any]]] = {}
        for p in patterns:
            by_category.setdefault(p.get("category", "general"), []).append(p)

        for category, items in sorted(by_category.items()):
            lines.append(f"\n[{category.upper()}]")
            for p in items:
                lines.append(
                    f"  {p['id']}: When '{p['trigger']}' — "
                    f"DO: {p['right_approach']} / AVOID: {p['wrong_approach']}"
                )

        return "\n".join(lines)

    # ── BaseAgent interface ───────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if ctx.get("task") == "log_pattern":
            return await self.log_pattern(
                trigger=ctx["trigger"],
                wrong=ctx["wrong"],
                right=ctx["right"],
                category=ctx.get("category", "general"),
            )
        if ctx.get("task") == "coaching":
            return await self.get_coaching_notes(query)

        kb_results = await self.search_knowledge(query, limit=5)
        kb_context = self._format_context(kb_results)

        guidance = await self.get_sales_guidance()

        sections = [f"Query: {query}"]
        if guidance:
            sections.append(f"Training Patterns:\n{guidance}")
        sections.append(f"Knowledge Base:\n{kb_context}")

        return await self.call_llm(_SYSTEM_PROMPT, "\n\n".join(sections))
