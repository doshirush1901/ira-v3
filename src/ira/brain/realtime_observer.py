"""Real-time observer — extracts learnings from every conversation turn.

After each response, the observer fires a lightweight LLM call to extract
corrections, facts, and preferences from the exchange.  These are persisted
to ``data/brain/realtime_learnings.jsonl`` and injected into the next turn's
system prompt so Ira immediately benefits from what it just learned.

Designed to run fire-and-forget so it never blocks the response path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ira.config import get_settings

logger = logging.getLogger(__name__)

_LEARNINGS_PATH = Path("data/brain/realtime_learnings.jsonl")

_EXTRACT_SYSTEM = (
    "You are analyzing a conversation turn between a user and an AI assistant. "
    "Extract any new facts, corrections, or preferences the user revealed. "
    "Return JSON: {\"facts\": [\"...\"], \"corrections\": [\"...\"], \"preferences\": [\"...\"]}\n"
    "If nothing new was learned, return {\"facts\": [], \"corrections\": [], \"preferences\": []}"
)

_MAX_LEARNINGS_PER_CONTACT = 50


class RealTimeObserver:
    """Extracts and persists learnings from each conversation turn."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.llm.openai_api_key.get_secret_value()
        self._model = "gpt-4.1-mini"
        self._learnings: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not _LEARNINGS_PATH.exists():
            return
        try:
            for line in _LEARNINGS_PATH.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                cid = entry.get("contact_id", "unknown")
                self._learnings.setdefault(cid, []).append(entry)
        except Exception:
            logger.debug("Failed to load realtime learnings")

    def _persist(self, entry: dict[str, Any]) -> None:
        _LEARNINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LEARNINGS_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")

    async def observe_turn(
        self,
        query: str,
        response: str,
        contact_id: str,
    ) -> dict[str, Any]:
        """Extract learnings from a conversation turn (fire-and-forget safe)."""
        if not self._api_key:
            return {"facts": [], "corrections": [], "preferences": []}

        prompt = f"USER: {query[:2000]}\n\nASSISTANT: {response[:2000]}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": self._model,
                        "temperature": 0,
                        "max_tokens": 300,
                        "messages": [
                            {"role": "system", "content": _EXTRACT_SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                extracted = json.loads(raw)
        except Exception:
            logger.debug("RealTimeObserver extraction failed")
            return {"facts": [], "corrections": [], "preferences": []}

        has_content = any(
            extracted.get(k) for k in ("facts", "corrections", "preferences")
        )
        if not has_content:
            return extracted

        entry = {
            "contact_id": contact_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **extracted,
        }
        self._learnings.setdefault(contact_id, []).append(entry)

        if len(self._learnings[contact_id]) > _MAX_LEARNINGS_PER_CONTACT:
            self._learnings[contact_id] = self._learnings[contact_id][-_MAX_LEARNINGS_PER_CONTACT:]

        self._persist(entry)
        logger.info(
            "RealTimeObserver: %d facts, %d corrections, %d preferences for %s",
            len(extracted.get("facts", [])),
            len(extracted.get("corrections", [])),
            len(extracted.get("preferences", [])),
            contact_id,
        )
        return extracted

    def format_for_prompt(self, contact_id: str, limit: int = 10) -> str:
        """Return recent learnings formatted for system prompt injection."""
        entries = self._learnings.get(contact_id, [])
        if not entries:
            return ""

        recent = entries[-limit:]
        lines: list[str] = []
        for e in recent:
            for fact in e.get("facts", []):
                lines.append(f"- Learned fact: {fact}")
            for corr in e.get("corrections", []):
                lines.append(f"- Correction: {corr}")
            for pref in e.get("preferences", []):
                lines.append(f"- Preference: {pref}")

        if not lines:
            return ""
        return "Recent learnings about this contact:\n" + "\n".join(lines[-15:])
