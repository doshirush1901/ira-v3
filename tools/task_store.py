"""
Minimal task/ticket store for Phase 4.6. SQLite-backed; tasks have title, assignee, due, status.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent
TASKS_DB = PROJECT_ROOT / "data" / "tasks.db"


def _conn():
    TASKS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(TASKS_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            assignee TEXT DEFAULT '',
            due TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    return conn


def task_create(title: str, assignee: str = "", due: str = "", notes: str = "") -> str:
    """Create a task. Returns task id and confirmation."""
    with _conn() as c:
        c.execute(
            "INSERT INTO tasks (title, assignee, due, notes) VALUES (?, ?, ?, ?)",
            (title.strip(), (assignee or "").strip(), (due or "").strip(), (notes or "").strip()),
        )
        c.commit()
        row_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return f"Task #{row_id} created: {title[:50]}"


def task_list(status: str = "", assignee: str = "", limit: int = 30) -> str:
    """List tasks. status: open|done|all (default open). assignee: filter by assignee."""
    with _conn() as c:
        q = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        status_lower = (status or "open").strip().lower()
        if status_lower == "all":
            pass
        elif status_lower == "done":
            q += " AND status = 'done'"
        else:
            q += " AND status = 'open'"
        if assignee:
            q += " AND assignee LIKE ?"
            params.append(f"%{assignee}%")
        q += " ORDER BY due ASC, id DESC LIMIT ?"
        params.append(limit)
        rows = c.execute(q, params).fetchall()
    if not rows:
        return "No tasks found."
    lines = ["# Tasks", ""]
    for r in rows:
        lines.append(f"- **#{r['id']}** {r['title'][:60]} | {r['assignee'] or '—'} | due: {r['due'] or '—'} | {r['status']}")
    return "\n".join(lines)


def task_complete(task_id: int) -> str:
    """Mark a task done."""
    with _conn() as c:
        c.execute("UPDATE tasks SET status = 'done', updated_at = datetime('now') WHERE id = ?", (task_id,))
        c.commit()
        if c.total_changes:
            return f"Task #{task_id} marked done."
    return f"Task #{task_id} not found."
