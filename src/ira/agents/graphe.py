"""Graphe — Logger / Scribe agent.

Records Cursor chat sessions to a structured store so Ira can learn
from them during dream/sleep cycles.  Runs at the end of the pipeline
after the response is shaped.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("graphe_system")
_DB_PATH = Path("data/brain/cursor_sessions.db")


class Graphe(BaseAgent):
    name = "graphe"
    role = "Logger / Scribe"
    description = "Records Cursor chat sessions for dream/sleep learning"
    knowledge_categories = []
    timeout = 15

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="log_session",
            description="Record a Cursor chat turn to the session log.",
            parameters={
                "query": "The user's query",
                "agents_used": "Comma-separated list of agents that handled the query",
                "response_summary": "1-2 sentence summary of the response",
                "sources": "Sources cited (comma-separated)",
                "email_threads": "Email thread IDs accessed (comma-separated, or empty)",
            },
            handler=self._tool_log_session,
        ))

        self.register_tool(AgentTool(
            name="get_recent_sessions",
            description="Retrieve recent session logs for analysis.",
            parameters={"limit": "Number of recent sessions to retrieve (default 20)"},
            handler=self._tool_get_recent,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def log_turn(
        self,
        query: str,
        agents_used: list[str],
        response_summary: str,
        sources: list[str] | None = None,
        email_threads: list[str] | None = None,
        user_feedback: str | None = None,
    ) -> None:
        """Direct API for pipeline to log a turn without the ReAct loop."""
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(_DB_PATH), timeout=30.0) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=30000")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS cursor_sessions (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    query TEXT NOT NULL,
                    agents_used TEXT NOT NULL,
                    response_summary TEXT NOT NULL,
                    sources TEXT NOT NULL DEFAULT '[]',
                    email_threads TEXT NOT NULL DEFAULT '[]',
                    user_feedback TEXT
                )
                """
            )
            await db.execute(
                """
                INSERT INTO cursor_sessions
                    (id, timestamp, query, agents_used, response_summary, sources, email_threads, user_feedback)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    time.time(),
                    query,
                    json.dumps(agents_used),
                    response_summary[:500],
                    json.dumps(sources or []),
                    json.dumps(email_threads or []),
                    user_feedback,
                ),
            )
            await db.commit()
        logger.info("GRAPHE | logged session: %s → %s", query[:60], agents_used)

    async def get_recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve recent sessions for dream learning."""
        if not _DB_PATH.exists():
            return []
        async with aiosqlite.connect(str(_DB_PATH), timeout=30.0) as db:
            await db.execute("PRAGMA busy_timeout=30000")
            cursor = await db.execute(
                "SELECT * FROM cursor_sessions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in rows]

    async def _tool_log_session(
        self,
        query: str,
        agents_used: str = "",
        response_summary: str = "",
        sources: str = "",
        email_threads: str = "",
    ) -> str:
        await self.log_turn(
            query=query,
            agents_used=[a.strip() for a in agents_used.split(",") if a.strip()],
            response_summary=response_summary,
            sources=[s.strip() for s in sources.split(",") if s.strip()],
            email_threads=[t.strip() for t in email_threads.split(",") if t.strip()],
        )
        return "Session logged."

    async def _tool_get_recent(self, limit: str = "20") -> str:
        sessions = await self.get_recent_sessions(int(limit))
        if not sessions:
            return "No sessions logged yet."
        lines = []
        for s in sessions:
            lines.append(
                f"- [{s.get('timestamp', '?')}] Q: {s.get('query', '?')[:80]} "
                f"→ agents: {s.get('agents_used', '[]')}"
            )
        return "\n".join(lines)
