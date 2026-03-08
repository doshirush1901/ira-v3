"""Mnemon — The Memory Guardian.

Maintains a correction ledger as the single source of truth for all
user corrections.  Intercepts stale data at every retrieval point
(pipeline responses, retriever results, Alexandros file reads) and
overrides contradictions with the corrected facts.

Also flags data that appears outdated based on source timestamps,
even when no explicit correction exists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("mnemon_system")
_LEDGER_PATH = Path("data/brain/correction_ledger.json")
_STALENESS_MONTHS = 3


def _load_ledger() -> dict[str, Any]:
    """Load the correction ledger from disk."""
    if not _LEDGER_PATH.exists():
        return {"entities": {}, "_metadata": {"last_updated": ""}}
    try:
        return json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read correction ledger; starting fresh")
        return {"entities": {}, "_metadata": {"last_updated": ""}}


def _save_ledger(ledger: dict[str, Any]) -> None:
    """Persist the correction ledger to disk."""
    ledger["_metadata"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER_PATH.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class Mnemon(BaseAgent):
    name = "mnemon"
    role = "Memory Guardian"
    description = (
        "Correction authority agent. Maintains the correction ledger and "
        "intercepts stale data at every retrieval point, overriding it "
        "with the corrected truth."
    )

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="lookup_correction",
            description="Check if an entity has a correction in the ledger.",
            parameters={"entity": "Company name or topic to look up"},
            handler=self._tool_lookup_correction,
        ))
        self.register_tool(AgentTool(
            name="record_correction",
            description="Record a new correction in the ledger.",
            parameters={
                "entity": "Company name or topic",
                "current_status": "The corrected, current truth",
                "stale_values": "Comma-separated list of old/wrong values to watch for",
            },
            handler=self._tool_record_correction,
        ))
        self.register_tool(AgentTool(
            name="list_all_corrections",
            description="List all entities in the correction ledger.",
            parameters={},
            handler=self._tool_list_all,
        ))

    async def _tool_lookup_correction(self, entity: str) -> str:
        ledger = await asyncio.to_thread(_load_ledger)
        entry = ledger["entities"].get(entity.lower())
        if not entry:
            for key, val in ledger["entities"].items():
                if entity.lower() in key:
                    entry = val
                    break
        if not entry:
            return f"No correction found for '{entity}'."
        return json.dumps(entry, default=str)

    async def _tool_record_correction(
        self, entity: str, current_status: str, stale_values: str = "",
    ) -> str:
        stale_list = [v.strip() for v in stale_values.split(",") if v.strip()]
        await self.record_correction(entity, current_status, stale_list)
        return f"Correction recorded for '{entity}'."

    async def _tool_list_all(self) -> str:
        ledger = await asyncio.to_thread(_load_ledger)
        entities = ledger.get("entities", {})
        if not entities:
            return "Correction ledger is empty."
        lines = [f"Correction ledger ({len(entities)} entities):"]
        for key, val in entities.items():
            lines.append(f"- **{key}**: {val.get('current_status', '')[:120]}")
        return "\n".join(lines)

    # ── core methods (called from pipeline, retriever, alexandros) ────────

    async def check_and_correct(self, text: str) -> str:
        """Scan text for entities with known corrections and override stale values.

        This is the fast, non-LLM check called from the pipeline,
        retriever, and Alexandros.  It does pure string matching
        against the correction ledger.
        """
        if not text:
            return text

        ledger = await asyncio.to_thread(_load_ledger)
        entities = ledger.get("entities", {})
        if not entities:
            return text

        corrections_applied: list[str] = []
        text_lower = text.lower()

        for entity_key, entry in entities.items():
            if entity_key not in text_lower:
                continue

            for stale in entry.get("stale_values", []):
                if stale.lower() in text_lower:
                    corrections_applied.append(
                        f"[CORRECTION] {entity_key}: "
                        f"'{stale}' is outdated. "
                        f"Current status: {entry['current_status']}"
                    )

        if not corrections_applied:
            return text

        correction_block = (
            "\n\n--- MNEMON CORRECTIONS (override stale data above) ---\n"
            + "\n".join(corrections_applied)
            + "\n--- END CORRECTIONS ---"
        )
        logger.info(
            "Mnemon applied %d corrections to response",
            len(corrections_applied),
        )
        return text + correction_block

    async def flag_staleness(self, text: str, source_date: str | None = None) -> str:
        """Append a staleness warning if the source data is old."""
        if not source_date:
            return text
        try:
            src = datetime.fromisoformat(source_date.replace("Z", "+00:00"))
            if src.tzinfo is None:
                src = src.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - src).days
            if age_days > _STALENESS_MONTHS * 30:
                months = age_days // 30
                text += (
                    f"\n\n[STALENESS WARNING] This data is from {source_date} "
                    f"({months} months old). It may be outdated. "
                    f"Cross-reference with recent emails or corrections."
                )
        except (ValueError, TypeError):
            pass
        return text

    async def record_correction(
        self,
        entity: str,
        current_status: str,
        stale_values: list[str] | None = None,
        source: str = "user_correction",
    ) -> None:
        """Add or update an entry in the correction ledger."""
        ledger = await asyncio.to_thread(_load_ledger)
        key = entity.lower().strip()

        existing = ledger["entities"].get(key, {})
        old_stale = existing.get("stale_values", [])
        merged_stale = list(set(old_stale + (stale_values or [])))

        ledger["entities"][key] = {
            "current_status": current_status,
            "stale_values": merged_stale,
            "corrected_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": source,
        }

        await asyncio.to_thread(_save_ledger, ledger)
        logger.info("Mnemon: recorded correction for '%s'", key)

    async def record_correction_from_feedback(
        self, previous_query: str, correction_text: str,
    ) -> None:
        """Extract entity and status from a feedback correction and record it.

        Uses simple heuristics to parse the correction text.  For complex
        corrections, the LLM-based handle() method is more appropriate.
        """
        entity = previous_query[:100].strip()
        words = entity.split()
        if len(words) > 5:
            entity = " ".join(words[:5])

        await self.record_correction(
            entity=entity,
            current_status=correction_text[:500],
            source="feedback",
        )

    # ── agent handle (for delegation from Athena) ─────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        return await self.run(query, ctx, system_prompt=_SYSTEM_PROMPT)
