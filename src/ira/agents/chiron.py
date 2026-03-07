"""Chiron -- Sales Trainer agent.

Maintains a library of sales training patterns (trigger situations,
wrong approaches, right approaches) and provides contextual coaching
notes for live sales situations.

Equipped with ReAct tools for pattern logging, coaching notes,
sales guidance, pattern search, and cross-agent delegation to Prometheus.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import DatabaseError, ToolExecutionError
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("chiron_system")
_DATA_PATH = Path("data/brain/sales_training.json")
_PATTERNS_LOCK = asyncio.Lock()


def _load_patterns_sync() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        return []
    try:
        data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        return data.get("patterns", [])
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read sales training data at %s", _DATA_PATH)
        return []


async def _load_patterns() -> list[dict[str, Any]]:
    async with _PATTERNS_LOCK:
        return await asyncio.to_thread(_load_patterns_sync)


def _save_patterns_sync(patterns: list[dict[str, Any]]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DATA_PATH.write_text(
        json.dumps({"patterns": patterns}, indent=2, default=str),
        encoding="utf-8",
    )


async def _save_patterns(patterns: list[dict[str, Any]]) -> None:
    async with _PATTERNS_LOCK:
        await asyncio.to_thread(_save_patterns_sync, patterns)


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
    knowledge_categories = [
        "sales_and_crm",
        "leads_and_contacts",
        "webcall transcripts",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="log_pattern",
            description="Log a new sales training pattern (trigger, wrong approach, right approach).",
            parameters={
                "pattern": "Description of the trigger situation",
                "context": "Category or context for the pattern",
                "effectiveness": "Effectiveness rating (default 'unknown')",
            },
            handler=self._tool_log_pattern,
        ))
        self.register_tool(AgentTool(
            name="get_coaching_notes",
            description="Get contextual coaching notes for a sales situation based on training patterns.",
            parameters={"scenario": "Description of the current sales situation"},
            handler=self._tool_get_coaching_notes,
        ))
        self.register_tool(AgentTool(
            name="get_sales_guidance",
            description="Retrieve the full sales training guidance organised by category.",
            parameters={"scenario": "Optional scenario context (can be empty)"},
            handler=self._tool_get_sales_guidance,
        ))
        self.register_tool(AgentTool(
            name="search_sales_patterns",
            description="Search the sales training pattern library for matching patterns.",
            parameters={"query": "Search query to match against patterns"},
            handler=self._tool_search_sales_patterns,
        ))
        self.register_tool(AgentTool(
            name="ask_prometheus",
            description="Delegate a question to Prometheus, the sales/CRM agent.",
            parameters={"query": "Question for Prometheus"},
            handler=self._tool_ask_prometheus,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_log_pattern(
        self, pattern: str, context: str, effectiveness: str = "unknown",
    ) -> str:
        return await self.log_pattern(
            trigger=pattern,
            wrong=f"(to be refined — effectiveness: {effectiveness})",
            right=pattern,
            category=context or "general",
        )

    async def _tool_get_coaching_notes(self, scenario: str) -> str:
        return await self.get_coaching_notes(scenario)

    async def _tool_get_sales_guidance(self, scenario: str = "") -> str:
        guidance = await self.get_sales_guidance()
        return guidance or "No sales training patterns recorded yet."

    async def _tool_search_sales_patterns(self, query: str) -> str:
        patterns = await _load_patterns()
        if not patterns:
            return "No sales training patterns recorded yet."

        query_lower = query.lower()
        matches = []
        for p in patterns:
            searchable = f"{p.get('trigger', '')} {p.get('category', '')} {p.get('right_approach', '')}".lower()
            if any(word in searchable for word in query_lower.split()):
                matches.append(p)

        if not matches:
            return f"No patterns matching '{query}'. Total patterns: {len(patterns)}."

        lines = [f"Found {len(matches)} matching patterns:"]
        for p in matches[:10]:
            lines.append(
                f"- [{p.get('id', '?')}] ({p.get('category', 'general')}) "
                f"Trigger: {p.get('trigger', '')} → DO: {p.get('right_approach', '')}"
            )
        return "\n".join(lines)

    async def _tool_ask_prometheus(self, query: str) -> str:
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("prometheus")
        if agent is None:
            return "Prometheus agent not found."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            logger.warning("Prometheus delegation failed: %s", exc)
            return f"Prometheus error: {exc}"

    # ── existing methods ─────────────────────────────────────────────────

    async def log_pattern(
        self,
        trigger: str,
        wrong: str,
        right: str,
        category: str,
    ) -> str:
        patterns = await _load_patterns()
        pattern_id = _next_pattern_id(patterns)
        patterns.append({
            "id": pattern_id,
            "trigger": trigger,
            "wrong_approach": wrong,
            "right_approach": right,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await _save_patterns(patterns)
        logger.info("Sales training pattern %s logged (category: %s)", pattern_id, category)
        return f"Training pattern {pattern_id} recorded under '{category}'."

    async def get_coaching_notes(self, context: str) -> str:
        patterns = await _load_patterns()
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
        patterns = await _load_patterns()
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
        ctx = dict(context or {})

        if ctx.get("task") == "log_pattern":
            return await self.log_pattern(
                trigger=ctx["trigger"],
                wrong=ctx["wrong"],
                right=ctx["right"],
                category=ctx.get("category", "general"),
            )
        if ctx.get("task") == "coaching":
            return await self.get_coaching_notes(query)

        conv_mem = self._services.get(SK.CONVERSATION_MEMORY)
        if conv_mem is not None:
            contact_id = (ctx.get("perception") or {}).get("email", "")
            if contact_id:
                try:
                    recent = await conv_mem.get_history(contact_id, "CLI", limit=10)
                    sales_msgs = [
                        m for m in recent
                        if any(kw in (m.get("content") or "").lower()
                               for kw in ("price", "quote", "deal", "order", "lead", "proposal"))
                    ]
                    if sales_msgs:
                        ctx["recent_sales_context"] = [
                            m.get("content", "")[:200] for m in sales_msgs[:5]
                        ]
                except (DatabaseError, Exception):
                    logger.debug("Chiron: conversation memory lookup failed")

        return await self.run(query, ctx, system_prompt=_SYSTEM_PROMPT)
