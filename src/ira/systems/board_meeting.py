"""Board Meeting — multi-agent collaborative discussion system.

Orchestrates structured meetings where multiple Pantheon agents
contribute their specialist perspectives on a topic.  Athena
synthesises the contributions into a final decision with action items.
Meeting minutes are persisted in a local SQLite database.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import httpx

from ira.config import get_settings
from ira.data.models import BoardMeetingMinutes

logger = logging.getLogger(__name__)

_DB_PATH = "board_meetings.db"

_SYNTHESIS_PROMPT = """\
You are Athena, the CEO of Machinecraft, chairing a board meeting.

You have received contributions from your specialist agents on the
topic below.  Your job is to:
1. Identify the key themes across all contributions.
2. Resolve any disagreements by weighing evidence.
3. Produce a concise synthesis (2-4 paragraphs).
4. List concrete action items.

Respond with JSON:
{
  "synthesis": "...",
  "action_items": ["item 1", "item 2"]
}"""


class BoardMeeting:
    """Run collaborative multi-agent discussions and persist minutes."""

    _DEFAULT_BOARD = [
        "prometheus", "plutus", "hermes", "hephaestus", "themis", "clio",
    ]

    def __init__(
        self,
        agent_handler: Any = None,
        db_path: str = _DB_PATH,
    ) -> None:
        self._agent_handler = agent_handler
        self._db_path = db_path
        self._settings = get_settings()

    async def _ensure_table(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                participants TEXT NOT NULL,
                contributions TEXT NOT NULL,
                synthesis TEXT NOT NULL,
                action_items TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        await db.commit()

    async def run_meeting(
        self,
        topic: str,
        participants: list[str] | None = None,
    ) -> BoardMeetingMinutes:
        """Collect contributions from each participant and synthesise."""
        agent_names = participants or list(self._DEFAULT_BOARD)

        contributions = await self._gather_contributions(agent_names, topic)
        synthesis, action_items = await self._synthesise(topic, contributions)

        minutes = BoardMeetingMinutes(
            topic=topic,
            participants=["athena"] + list(contributions.keys()),
            contributions=contributions,
            synthesis=synthesis,
            action_items=action_items,
        )

        await self._store_minutes(minutes)
        return minutes

    async def run_focused_meeting(
        self,
        topic: str,
        lead_agent: str,
        supporting_agents: list[str],
    ) -> BoardMeetingMinutes:
        """Two-round meeting: lead analyses first, then supporters respond."""
        lead_contributions = await self._gather_contributions([lead_agent], topic)
        lead_analysis = lead_contributions.get(lead_agent, "")

        enriched_topic = (
            f"{topic}\n\n{lead_agent}'s analysis:\n{lead_analysis}"
        )
        support_contributions = await self._gather_contributions(
            supporting_agents, enriched_topic,
        )

        all_contributions = {**lead_contributions, **support_contributions}
        synthesis, action_items = await self._synthesise(topic, all_contributions)

        minutes = BoardMeetingMinutes(
            topic=topic,
            participants=["athena", lead_agent] + list(support_contributions.keys()),
            contributions=all_contributions,
            synthesis=synthesis,
            action_items=action_items,
        )

        await self._store_minutes(minutes)
        return minutes

    async def get_past_meetings(
        self,
        topic_filter: str | None = None,
        limit: int = 10,
    ) -> list[BoardMeetingMinutes]:
        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure_table(db)
            if topic_filter:
                cursor = await db.execute(
                    "SELECT topic, participants, contributions, synthesis, action_items, created_at "
                    "FROM meetings WHERE topic LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{topic_filter}%", limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT topic, participants, contributions, synthesis, action_items, created_at "
                    "FROM meetings ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()

        results: list[BoardMeetingMinutes] = []
        for row in rows:
            results.append(BoardMeetingMinutes(
                topic=row[0],
                participants=json.loads(row[1]),
                contributions=json.loads(row[2]),
                synthesis=row[3],
                action_items=json.loads(row[4]),
            ))
        return results

    # ── internal helpers ──────────────────────────────────────────────────

    async def _gather_contributions(
        self,
        agent_names: list[str],
        topic: str,
    ) -> dict[str, str]:
        """Ask each agent for their perspective on the topic."""
        contributions: dict[str, str] = {}
        if self._agent_handler is None:
            for name in agent_names:
                contributions[name] = f"(No handler configured for {name})"
            return contributions

        for name in agent_names:
            try:
                response = await self._agent_handler(name, topic)
                contributions[name] = response
            except Exception:
                logger.exception("Agent '%s' failed during board meeting", name)
                contributions[name] = f"(Agent '{name}' encountered an error)"
        return contributions

    async def _synthesise(
        self,
        topic: str,
        contributions: dict[str, str],
    ) -> tuple[str, list[str]]:
        """Use an LLM to synthesise contributions into a decision."""
        formatted = "\n\n".join(
            f"**{agent}**: {text}" for agent, text in contributions.items()
        )
        user_msg = f"Topic: {topic}\n\nContributions:\n{formatted}"

        api_key = self._settings.llm.openai_api_key.get_secret_value()
        if not api_key:
            return "No LLM key configured — raw contributions only.", []

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": self._settings.llm.openai_model,
                        "temperature": 0.3,
                        "messages": [
                            {"role": "system", "content": _SYNTHESIS_PROMPT},
                            {"role": "user", "content": user_msg[:12_000]},
                        ],
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError):
            logger.exception("LLM synthesis failed")
            return "Synthesis failed — see raw contributions.", []

        try:
            data = json.loads(raw)
            return data.get("synthesis", raw), data.get("action_items", [])
        except (json.JSONDecodeError, TypeError):
            return raw, []

    async def _store_minutes(self, minutes: BoardMeetingMinutes) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                "INSERT INTO meetings (topic, participants, contributions, synthesis, action_items, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    minutes.topic,
                    json.dumps(minutes.participants),
                    json.dumps(minutes.contributions),
                    minutes.synthesis,
                    json.dumps(minutes.action_items),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
