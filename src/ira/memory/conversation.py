"""Per-user, per-channel conversation history backed by SQLite."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from langfuse.decorators import observe

from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import ConversationEntities
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


class ConversationMemory:
    def __init__(
        self,
        db_path: str = "conversations.db",
    ) -> None:
        self._db_path = db_path
        self._llm = get_llm_client()
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_channel "
            "ON conversations(user_id, channel)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
            "ON messages(conversation_id)"
        )
        await self._db.commit()

    async def should_start_new_conversation(self, user_id: str, channel: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            SELECT last_message_at FROM conversations
            WHERE user_id = ? AND channel = ?
            ORDER BY last_message_at DESC
            LIMIT 1
            """,
            (user_id, channel),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return True
        last_at = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - last_at > timedelta(minutes=30):
            return True
        return False

    async def add_message(
        self,
        user_id: str,
        channel: str,
        role: str,
        content: str,
    ) -> None:
        assert self._db is not None
        now = datetime.now(timezone.utc).isoformat()

        if await self.should_start_new_conversation(user_id, channel):
            cursor = await self._db.execute(
                """
                INSERT INTO conversations (user_id, channel, started_at, last_message_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, channel, now, now),
            )
            conversation_id = cursor.lastrowid
            await cursor.close()
        else:
            cursor = await self._db.execute(
                """
                SELECT id FROM conversations
                WHERE user_id = ? AND channel = ?
                ORDER BY last_message_at DESC
                LIMIT 1
                """,
                (user_id, channel),
            )
            row = await cursor.fetchone()
            await cursor.close()
            conversation_id = row[0]

        await self._db.execute(
            """
            INSERT INTO messages (conversation_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, now),
        )
        await self._db.execute(
            "UPDATE conversations SET last_message_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        await self._db.commit()

    async def get_history(
        self,
        user_id: str,
        channel: str,
        limit: int = 20,
    ) -> list[dict]:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            SELECT id FROM conversations
            WHERE user_id = ? AND channel = ?
            ORDER BY last_message_at DESC
            LIMIT 1
            """,
            (user_id, channel),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return []
        conversation_id = row[0]

        cursor = await self._db.execute(
            """
            SELECT role, content, timestamp FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        results = [
            {"role": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(rows)
        ]
        return results

    @observe()
    async def extract_entities(self, message: str) -> dict[str, list]:
        """Extract entities from a message. Returns dict with keys: companies, people, emails, machines, quote_ids, dates, amounts."""
        system = load_prompt("conversation_extract_entities")
        empty: dict[str, list] = {
            "companies": [],
            "people": [],
            "emails": [],
            "machines": [],
            "quote_ids": [],
            "dates": [],
            "amounts": [],
        }
        try:
            result = await self._llm.generate_structured(
                system, message, ConversationEntities,
                name="conversation.extract_entities",
            )
            return result.model_dump()
        except Exception:
            logger.exception("Entity extraction LLM call failed")
        return empty

    @observe()
    async def resolve_coreferences(self, message: str, history: list[dict]) -> str:
        context = "\n".join(
            f"[{h['role']}] {h['content']}" for h in history[-10:]
        )
        system = load_prompt("conversation_resolve_coreferences")
        user_text = f"Context:\n{context}\n\nMessage to rewrite:\n{message}"
        try:
            result = await self._llm.generate_text(
                system, user_text,
                name="conversation.resolve_coreferences",
            )
        except Exception:
            logger.exception("Coreference resolution LLM call failed")
            return message
        if not result or not result.strip():
            return message
        return result.strip()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> ConversationMemory:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
