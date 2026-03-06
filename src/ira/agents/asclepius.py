"""Asclepius -- Quality Management agent.

Tracks punch items across projects and phases (FAT, Installation,
Commissioning), flags aging items, and provides a cross-project
quality dashboard.  Data is persisted in an aiosqlite database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("asclepius_system")
_DB_PATH = Path("data/brain/asclepius.db")

_VALID_PHASES = frozenset({"FAT", "INSTALLATION", "COMMISSIONING"})
_VALID_SEVERITIES = frozenset({"CRITICAL", "MAJOR", "MINOR", "OBSERVATION"})
_VALID_CATEGORIES = frozenset({
    "mechanical", "electrical", "software",
    "hydraulic", "pneumatic", "safety",
})
_VALID_STATUSES = frozenset({"OPEN", "IN_PROGRESS", "CLOSED"})

_AGING_THRESHOLD_DAYS = 14


class Asclepius(BaseAgent):
    name = "asclepius"
    role = "Quality Manager"
    description = "Punch-list tracking, quality dashboards, and project quality oversight"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._db: aiosqlite.Connection | None = None

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is not None:
            return self._db
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(_DB_PATH))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS punch_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                phase       TEXT NOT NULL,
                severity    TEXT NOT NULL,
                category    TEXT NOT NULL,
                description TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'OPEN',
                created_at  TEXT NOT NULL,
                closed_at   TEXT
            )
            """
        )
        await self._db.commit()
        logger.info("Asclepius DB initialised at %s", _DB_PATH)
        return self._db

    # ── public API ────────────────────────────────────────────────────────

    async def log_punch_item(
        self,
        project_name: str,
        phase: str,
        severity: str,
        category: str,
        description: str,
    ) -> str:
        phase = phase.upper()
        severity = severity.upper()
        category = category.lower()

        if phase not in _VALID_PHASES:
            return f"Invalid phase '{phase}'. Must be one of: {', '.join(sorted(_VALID_PHASES))}"
        if severity not in _VALID_SEVERITIES:
            return f"Invalid severity '{severity}'. Must be one of: {', '.join(sorted(_VALID_SEVERITIES))}"
        if category not in _VALID_CATEGORIES:
            return f"Invalid category '{category}'. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}"

        db = await self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            """
            INSERT INTO punch_items (project_name, phase, severity, category, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (project_name, phase, severity, category, description, now),
        )
        await db.commit()
        item_id = cursor.lastrowid or 0
        logger.info("Punch item #%d logged for project '%s'", item_id, project_name)
        return f"Punch item #{item_id} logged for {project_name} ({phase}/{severity}/{category})."

    async def get_punch_list(self, project_name: str) -> str:
        db = await self._ensure_db()
        cursor = await db.execute(
            "SELECT id, phase, severity, category, description, status, created_at, closed_at "
            "FROM punch_items WHERE project_name = ? ORDER BY created_at ASC",
            (project_name,),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        if not rows:
            return f"No punch items found for project '{project_name}'."

        now = datetime.now(timezone.utc)
        lines = [f"Punch list for {project_name} ({len(rows)} items):\n"]
        for row in rows:
            item_id, phase, severity, category, desc, status, created_at, closed_at = row
            age_days = (now - datetime.fromisoformat(created_at)).days
            aging_flag = " [AGING]" if status != "CLOSED" and age_days > _AGING_THRESHOLD_DAYS else ""
            lines.append(
                f"  #{item_id} [{status}] {phase}/{severity}/{category} — {desc} "
                f"(age: {age_days}d){aging_flag}"
            )

        open_count = sum(1 for r in rows if r[5] != "CLOSED")
        lines.append(f"\nOpen items: {open_count}/{len(rows)}")
        return "\n".join(lines)

    async def close_punch_item(self, item_id: int) -> str:
        db = await self._ensure_db()
        cursor = await db.execute(
            "SELECT id, status, project_name FROM punch_items WHERE id = ?",
            (item_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if not row:
            return f"Punch item #{item_id} not found."
        if row[1] == "CLOSED":
            return f"Punch item #{item_id} is already closed."

        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "UPDATE punch_items SET status = 'CLOSED', closed_at = ? WHERE id = ?",
            (now, item_id),
        )
        await db.commit()
        logger.info("Punch item #%d closed for project '%s'", item_id, row[2])
        return f"Punch item #{item_id} closed for project '{row[2]}'."

    async def quality_dashboard(self) -> str:
        db = await self._ensure_db()

        cursor = await db.execute(
            "SELECT project_name, status, COUNT(*) FROM punch_items GROUP BY project_name, status"
        )
        status_rows = await cursor.fetchall()
        await cursor.close()

        if not status_rows:
            return "No punch items recorded across any project."

        projects: dict[str, dict[str, int]] = {}
        for project, status, count in status_rows:
            projects.setdefault(project, {})
            projects[project][status] = count

        cursor = await db.execute(
            "SELECT project_name, severity, COUNT(*) FROM punch_items "
            "WHERE status != 'CLOSED' GROUP BY project_name, severity"
        )
        severity_rows = await cursor.fetchall()
        await cursor.close()

        open_severities: dict[str, dict[str, int]] = {}
        for project, severity, count in severity_rows:
            open_severities.setdefault(project, {})
            open_severities[project][severity] = count

        now = datetime.now(timezone.utc)
        cursor = await db.execute(
            "SELECT project_name, COUNT(*) FROM punch_items "
            "WHERE status != 'CLOSED' AND julianday(?) - julianday(created_at) > ? "
            "GROUP BY project_name",
            (now.isoformat(), _AGING_THRESHOLD_DAYS),
        )
        aging_rows = dict(await cursor.fetchall())
        await cursor.close()

        lines = ["# Quality Dashboard\n"]
        for project, statuses in sorted(projects.items()):
            total = sum(statuses.values())
            open_count = total - statuses.get("CLOSED", 0)
            aging = aging_rows.get(project, 0)
            lines.append(f"## {project}")
            lines.append(f"  Total: {total} | Open: {open_count} | Closed: {statuses.get('CLOSED', 0)}")
            if aging:
                lines.append(f"  Aging (>{_AGING_THRESHOLD_DAYS}d): {aging}")
            sev = open_severities.get(project, {})
            if sev:
                sev_parts = [f"{k}: {v}" for k, v in sorted(sev.items())]
                lines.append(f"  Open by severity: {', '.join(sev_parts)}")
            lines.append("")

        return "\n".join(lines)

    # ── BaseAgent interface ───────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if ctx.get("task") == "log_punch_item":
            return await self.log_punch_item(
                project_name=ctx["project_name"],
                phase=ctx["phase"],
                severity=ctx["severity"],
                category=ctx["category"],
                description=ctx["description"],
            )
        if ctx.get("task") == "close_punch_item":
            return await self.close_punch_item(ctx["item_id"])
        if ctx.get("task") == "punch_list":
            return await self.get_punch_list(ctx["project_name"])
        if ctx.get("task") == "quality_dashboard":
            return await self.quality_dashboard()

        kb_results = await self.search_knowledge(query, limit=5)
        kb_context = self._format_context(kb_results)

        dashboard = await self.quality_dashboard()

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nQuality Dashboard:\n{dashboard}\n\nKnowledge Base:\n{kb_context}",
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
