"""Relationship memory — tracks depth and quality of contact relationships."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite
import httpx
from pydantic import BaseModel, Field

from ira.config import LLMConfig, get_settings
from ira.data.models import Interaction, WarmthLevel
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_WARMTH_ORDER = list(WarmthLevel)

_MOMENTS_SYSTEM_PROMPT = load_prompt("memorable_moments")

_GREETINGS: dict[WarmthLevel, str] = {
    WarmthLevel.STRANGER: "Hello, thank you for reaching out to Machinecraft. How can I help you today?",
    WarmthLevel.ACQUAINTANCE: "Hello! Good to hear from you again. How can I assist you?",
    WarmthLevel.FAMILIAR: "Hi there! Nice to connect again. What can I do for you?",
    WarmthLevel.WARM: "Hey, great to hear from you! What's on your mind?",
    WarmthLevel.TRUSTED: "Hey! Always good to hear from you. What can I help with?",
}


class Relationship(BaseModel):
    contact_id: str
    warmth_level: WarmthLevel = WarmthLevel.STRANGER
    interaction_count: int = 0
    memorable_moments: list[str] = Field(default_factory=list)
    learned_preferences: dict[str, str] = Field(default_factory=dict)
    first_interaction: datetime | None = None
    last_interaction: datetime | None = None


class RelationshipMemory:
    def __init__(
        self,
        db_path: str = "relationships.db",
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._db_path = db_path
        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS relationships (
                contact_id TEXT PRIMARY KEY,
                warmth_level TEXT NOT NULL DEFAULT 'STRANGER',
                interaction_count INTEGER NOT NULL DEFAULT 0,
                memorable_moments TEXT NOT NULL DEFAULT '[]',
                learned_preferences TEXT NOT NULL DEFAULT '{}',
                first_interaction TEXT,
                last_interaction TEXT
            )
            """
        )
        await self._db.commit()

    async def update_relationship(self, contact_id: str, interaction: Interaction) -> Relationship:
        assert self._db is not None
        rel = await self.get_relationship(contact_id)
        rel.interaction_count += 1
        rel.last_interaction = interaction.created_at
        if rel.first_interaction is None:
            rel.first_interaction = interaction.created_at

        if interaction.content and len(interaction.content) > 50:
            raw = await self._llm_call(_MOMENTS_SYSTEM_PROMPT, interaction.content)
            try:
                parsed = json.loads(raw)
                moments = []
                if isinstance(parsed, dict) and "moments" in parsed:
                    for m in parsed["moments"]:
                        if isinstance(m, dict) and m.get("content", "").strip():
                            moments.append(m["content"].strip())
                elif isinstance(parsed, list):
                    for m in parsed:
                        if isinstance(m, str) and m.strip():
                            moments.append(m.strip())
                for m in moments:
                    rel.memorable_moments.append(m)
                rel.memorable_moments = rel.memorable_moments[-50:]
            except (json.JSONDecodeError, TypeError):
                pass

        rel.warmth_level = self._check_warmth_upgrade(rel)

        first_iso = rel.first_interaction.isoformat() if rel.first_interaction else None
        last_iso = rel.last_interaction.isoformat() if rel.last_interaction else None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO relationships
            (contact_id, warmth_level, interaction_count, memorable_moments, learned_preferences, first_interaction, last_interaction)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                rel.warmth_level.value,
                rel.interaction_count,
                json.dumps(rel.memorable_moments),
                json.dumps(rel.learned_preferences),
                first_iso,
                last_iso,
            ),
        )
        await self._db.commit()
        return rel

    def _check_warmth_upgrade(self, rel: Relationship) -> WarmthLevel:
        current = rel.warmth_level
        if current == WarmthLevel.STRANGER and rel.interaction_count >= 3:
            return WarmthLevel.ACQUAINTANCE
        if current == WarmthLevel.ACQUAINTANCE:
            if (
                rel.interaction_count >= 10
                and rel.first_interaction is not None
                and rel.last_interaction is not None
            ):
                days = (rel.last_interaction - rel.first_interaction).days
                if days >= 14:
                    return WarmthLevel.FAMILIAR
        if current == WarmthLevel.FAMILIAR:
            if rel.interaction_count >= 20 and len(rel.memorable_moments) >= 3:
                return WarmthLevel.WARM
        return current

    async def get_relationship(self, contact_id: str) -> Relationship:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT contact_id, warmth_level, interaction_count, memorable_moments, learned_preferences, first_interaction, last_interaction FROM relationships WHERE contact_id = ?",
            (contact_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return Relationship(contact_id=contact_id)
        first = None
        if row[5]:
            first = datetime.fromisoformat(row[5].replace("Z", "+00:00"))
        last = None
        if row[6]:
            last = datetime.fromisoformat(row[6].replace("Z", "+00:00"))
        try:
            warmth = WarmthLevel(row[1])
        except ValueError:
            warmth = WarmthLevel.STRANGER
        moments = json.loads(row[3]) if isinstance(row[3], str) else []
        prefs = json.loads(row[4]) if isinstance(row[4], str) else {}
        return Relationship(
            contact_id=row[0],
            warmth_level=warmth,
            interaction_count=row[2] or 0,
            memorable_moments=moments if isinstance(moments, list) else [],
            learned_preferences=prefs if isinstance(prefs, dict) else {},
            first_interaction=first,
            last_interaction=last,
        )

    def get_greeting_style(self, relationship: Relationship) -> str:
        return _GREETINGS.get(relationship.warmth_level, _GREETINGS[WarmthLevel.STRANGER])

    async def promote_to_trusted(self, contact_id: str) -> Relationship:
        rel = await self.get_relationship(contact_id)
        if rel.warmth_level != WarmthLevel.WARM:
            raise ValueError("Can only promote WARM contacts to TRUSTED")
        rel.warmth_level = WarmthLevel.TRUSTED
        assert self._db is not None
        first_iso = rel.first_interaction.isoformat() if rel.first_interaction else None
        last_iso = rel.last_interaction.isoformat() if rel.last_interaction else None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO relationships
            (contact_id, warmth_level, interaction_count, memorable_moments, learned_preferences, first_interaction, last_interaction)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                rel.warmth_level.value,
                rel.interaction_count,
                json.dumps(rel.memorable_moments),
                json.dumps(rel.learned_preferences),
                first_iso,
                last_iso,
            ),
        )
        await self._db.commit()
        return rel

    async def get_all_relationships(
        self,
        min_warmth: WarmthLevel | None = None,
    ) -> list[Relationship]:
        assert self._db is not None
        if min_warmth is not None:
            idx = _WARMTH_ORDER.index(min_warmth)
            levels = [w.value for w in _WARMTH_ORDER[idx:]]
            placeholders = ",".join("?" * len(levels))
            cursor = await self._db.execute(
                f"SELECT contact_id, warmth_level, interaction_count, memorable_moments, learned_preferences, first_interaction, last_interaction FROM relationships WHERE warmth_level IN ({placeholders})",
                levels,
            )
        else:
            cursor = await self._db.execute(
                "SELECT contact_id, warmth_level, interaction_count, memorable_moments, learned_preferences, first_interaction, last_interaction FROM relationships"
            )
        rows = await cursor.fetchall()
        await cursor.close()
        result = []
        for row in rows:
            first = None
            if row[5]:
                first = datetime.fromisoformat(row[5].replace("Z", "+00:00"))
            last = None
            if row[6]:
                last = datetime.fromisoformat(row[6].replace("Z", "+00:00"))
            try:
                warmth = WarmthLevel(row[1])
            except ValueError:
                warmth = WarmthLevel.STRANGER
            moments = json.loads(row[3]) if isinstance(row[3], str) else []
            prefs = json.loads(row[4]) if isinstance(row[4], str) else {}
            result.append(
                Relationship(
                    contact_id=row[0],
                    warmth_level=warmth,
                    interaction_count=row[2] or 0,
                    memorable_moments=moments if isinstance(moments, list) else [],
                    learned_preferences=prefs if isinstance(prefs, dict) else {},
                    first_interaction=first,
                    last_interaction=last,
                )
            )
        return result

    async def _llm_call(self, system: str, user: str) -> str:
        if not self._openai_key:
            return "[]"
        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("LLM call failed in RelationshipMemory")
            return "[]"

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> RelationshipMemory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
