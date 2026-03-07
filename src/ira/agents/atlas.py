"""Atlas — Project Manager agent.

Tracks projects, logs events, monitors production schedules, and
alerts on overdue payment milestones using a local SQLite logbook.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("atlas_system")

_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "brain" / "atlas_logbook.db"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    customer    TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    event_type  TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
"""


class Atlas(BaseAgent):
    name = "atlas"
    role = "Project Manager"
    description = "Project tracking, event logging, production scheduling, and payment milestone alerts"
    knowledge_categories = [
        "orders_and_pos",
        "production",
        "current machine orders",
        "project_case_studies",
        "company_internal",
        "contracts_and_legal",
        "business plans",
    ]

    _db_initialised: bool = False

    # ── tool registration ─────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="get_project_status",
            description="Get a full project summary including logbook events and KB data.",
            parameters={"project_id": "Project name or identifier"},
            handler=self._tool_get_project_status,
        ))
        self.register_tool(AgentTool(
            name="log_project_event",
            description="Log an event to a project's logbook (creates the project if new).",
            parameters={
                "project_id": "Project name or identifier",
                "event": "Description of the event to log",
            },
            handler=self._tool_log_project_event,
        ))
        self.register_tool(AgentTool(
            name="get_overdue_milestones",
            description="Check for overdue payment milestones and pending invoices across projects.",
            parameters={},
            handler=self._tool_get_overdue_milestones,
        ))
        self.register_tool(AgentTool(
            name="get_production_schedule",
            description="Get the current production schedule with active project timelines.",
            parameters={"project_id": "Optional project name to filter (empty for all)"},
            handler=self._tool_get_production_schedule,
        ))

        if self._services.get("pantheon"):
            self.register_tool(AgentTool(
                name="ask_hephaestus",
                description="Delegate a production/machine specs question to the Hephaestus agent.",
                parameters={"query": "The production or machine question"},
                handler=self._tool_ask_hephaestus,
            ))

    # ── tool handlers ─────────────────────────────────────────────────────

    async def _tool_get_project_status(self, project_id: str) -> str:
        return await self.project_summary(project_id)

    async def _tool_log_project_event(self, project_id: str, event: str) -> str:
        return await self.log_event(project_id, "note", event)

    async def _tool_get_overdue_milestones(self) -> str:
        return await self.payment_alerts()

    async def _tool_get_production_schedule(self, project_id: str = "") -> str:
        return await self.production_schedule()

    async def _tool_ask_hephaestus(self, query: str) -> str:
        pantheon = self._services.get("pantheon")
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("hephaestus")
        if agent is None:
            return "Hephaestus agent not available."
        try:
            return await agent.handle(query)
        except Exception as exc:
            return f"Hephaestus error: {exc}"

    # ── DB setup ──────────────────────────────────────────────────────────

    async def _ensure_db(self) -> None:
        if self._db_initialised:
            return
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(_DB_PATH)) as db:
            await db.executescript(_INIT_SQL)
            await db.commit()
        self._db_initialised = True

    # ── main handler ──────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        await self._ensure_db()
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "project_summary":
            return await self.project_summary(ctx.get("project_name", query))

        if action == "log_event":
            return await self.log_event(
                ctx.get("project_name", ""),
                ctx.get("event_type", "note"),
                ctx.get("description", query),
            )

        if action == "production_schedule":
            return await self.production_schedule()

        if action == "payment_alerts":
            return await self.payment_alerts()

        if action == "meeting_notes":
            return await self.use_skill(
                "generate_meeting_notes",
                transcript=ctx.get("transcript", query),
                attendees=ctx.get("attendees", []),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    # ── existing methods ──────────────────────────────────────────────────

    async def project_summary(self, project_name: str) -> str:
        """Combine KB data with logbook entries for a project summary."""
        kb_results = await self.search_domain_knowledge(
            f"project {project_name} status timeline", limit=8,
        )
        kb_context = self._format_context(kb_results)

        logbook_context = ""
        async with aiosqlite.connect(str(_DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM projects WHERE name = ? COLLATE NOCASE",
                (project_name,),
            ) as cursor:
                project = await cursor.fetchone()

            if project:
                pid = project["id"]
                async with db.execute(
                    "SELECT event_type, description, created_at "
                    "FROM events WHERE project_id = ? ORDER BY created_at DESC LIMIT 20",
                    (pid,),
                ) as cursor:
                    events = await cursor.fetchall()

                logbook_context = (
                    f"Project: {project['name']} | Customer: {project['customer']} | "
                    f"Status: {project['status']} | Created: {project['created_at']}\n"
                    f"Recent events ({len(events)}):\n"
                ) + "\n".join(
                    f"  [{e['event_type']}] {e['description']} ({e['created_at']})"
                    for e in events
                )

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Provide a project summary for: {project_name}\n\n"
            f"Logbook data:\n{logbook_context or '(no logbook entries)'}\n\n"
            f"Knowledge base data:\n{kb_context}",
        )

    async def log_event(
        self,
        project_name: str,
        event_type: str,
        description: str,
    ) -> str:
        """Log an event to the project logbook, creating the project if needed."""
        now = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(str(_DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id FROM projects WHERE name = ? COLLATE NOCASE",
                (project_name,),
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                pid = row["id"]
            else:
                cursor = await db.execute(
                    "INSERT INTO projects (name, customer, status, created_at) VALUES (?, '', 'active', ?)",
                    (project_name, now),
                )
                pid = cursor.lastrowid

            await db.execute(
                "INSERT INTO events (project_id, event_type, description, created_at) VALUES (?, ?, ?, ?)",
                (pid, event_type, description, now),
            )
            await db.commit()

        return json.dumps({
            "status": "logged",
            "project": project_name,
            "event_type": event_type,
            "description": description,
            "timestamp": now,
        })

    async def production_schedule(self) -> str:
        """Search KB for current production schedule data."""
        results = await self.search_domain_knowledge(
            "production schedule timeline delivery dates manufacturing", limit=10,
        )
        kb_context = self._format_context(results)

        logbook_context = ""
        async with aiosqlite.connect(str(_DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT p.name, p.customer, p.status, "
                "(SELECT COUNT(*) FROM events e WHERE e.project_id = p.id) as event_count "
                "FROM projects p WHERE p.status = 'active' ORDER BY p.created_at DESC",
            ) as cursor:
                projects = await cursor.fetchall()

            if projects:
                logbook_context = "Active projects in logbook:\n" + "\n".join(
                    f"  - {p['name']} (customer: {p['customer'] or 'N/A'}, events: {p['event_count']})"
                    for p in projects
                )

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Compile the current production schedule.\n\n"
            f"Logbook:\n{logbook_context or '(no active projects in logbook)'}\n\n"
            f"Knowledge base data:\n{kb_context}",
        )

    async def payment_alerts(self) -> str:
        """Check for overdue payment milestones across projects."""
        results = await self.search_domain_knowledge(
            "payment milestone overdue invoice pending receivable", limit=10,
        )
        kb_context = self._format_context(results)

        logbook_context = ""
        async with aiosqlite.connect(str(_DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT p.name, e.event_type, e.description, e.created_at "
                "FROM events e JOIN projects p ON e.project_id = p.id "
                "WHERE e.event_type IN ('payment', 'invoice', 'milestone') "
                "ORDER BY e.created_at DESC LIMIT 20",
            ) as cursor:
                events = await cursor.fetchall()

            if events:
                logbook_context = "Payment-related events:\n" + "\n".join(
                    f"  - [{e['event_type']}] {e['name']}: {e['description']} ({e['created_at']})"
                    for e in events
                )

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Identify any overdue payment milestones or pending invoices.\n\n"
            f"Logbook payment events:\n{logbook_context or '(no payment events logged)'}\n\n"
            f"Knowledge base data:\n{kb_context}",
        )
