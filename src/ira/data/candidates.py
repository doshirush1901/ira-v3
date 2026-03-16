"""Candidate database for Anu — applicant datasheets built from imports and mailbox.

Stores one row per candidate (keyed by email), with parsed profile, optional score,
and source (email thread or file path). Used for engagement via Rushabh's email:
Anu drafts replies using this datasheet context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = _REPO_ROOT / "data" / "brain" / "candidates.db"


async def _ensure_table(conn: aiosqlite.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT,
            source_type TEXT,
            source_id TEXT,
            profile_json TEXT,
            score_json TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidates_email ON candidates(email)"
    )
    await conn.commit()
    # Add cv_parsed_json if missing (existing DBs)
    try:
        await conn.execute(
            "ALTER TABLE candidates ADD COLUMN cv_parsed_json TEXT"
        )
        await conn.commit()
    except aiosqlite.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


class CandidateStore:
    """Async store for applicant datasheets (SQLite)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DB_PATH

    async def _conn(self) -> aiosqlite.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self._path)
        conn.row_factory = aiosqlite.Row
        await _ensure_table(conn)
        return conn

    async def upsert(
        self,
        email: str,
        *,
        name: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        profile: dict[str, Any] | None = None,
        score: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert or update candidate by email. Returns row id."""
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("Invalid email")
        now = datetime.now(timezone.utc).isoformat()
        conn = await self._conn()
        try:
            profile_json = json.dumps(profile) if profile else None
            score_json = json.dumps(score) if score else None
            await conn.execute(
                """
                INSERT INTO candidates (email, name, source_type, source_id, profile_json, score_json, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    name = COALESCE(excluded.name, name),
                    source_type = COALESCE(excluded.source_type, source_type),
                    source_id = COALESCE(excluded.source_id, source_id),
                    profile_json = COALESCE(excluded.profile_json, profile_json),
                    score_json = COALESCE(excluded.score_json, score_json),
                    notes = COALESCE(excluded.notes, notes),
                    updated_at = excluded.updated_at
                """,
                (email, name or None, source_type, source_id, profile_json, score_json, notes, now, now),
            )
            await conn.commit()
            cur = await conn.execute("SELECT id FROM candidates WHERE email = ?", (email,))
            row = await cur.fetchone()
            return row["id"] if row else 0
        finally:
            await conn.close()

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Return candidate row as dict or None."""
        email = (email or "").strip().lower()
        conn = await self._conn()
        try:
            cur = await conn.execute(
                "SELECT * FROM candidates WHERE email = ?", (email,)
            )
            row = await cur.fetchone()
            if not row:
                return None
            out = dict(row)
            if out.get("profile_json"):
                try:
                    out["profile"] = json.loads(out["profile_json"])
                except Exception:
                    out["profile"] = {}
            else:
                out["profile"] = {}
            if out.get("score_json"):
                try:
                    out["score"] = json.loads(out["score_json"])
                except Exception:
                    out["score"] = {}
            else:
                out["score"] = {}
            if out.get("cv_parsed_json"):
                try:
                    out["cv_parsed"] = json.loads(out["cv_parsed_json"])
                except Exception:
                    out["cv_parsed"] = {}
            else:
                out["cv_parsed"] = None
            return out
        finally:
            await conn.close()

    async def update_cv_parsed(self, email: str, cv_profile: dict[str, Any]) -> None:
        """Update only cv_parsed_json and updated_at for this candidate."""
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("Invalid email")
        now = datetime.now(timezone.utc).isoformat()
        conn = await self._conn()
        try:
            cv_json = json.dumps(cv_profile) if cv_profile else None
            await conn.execute(
                """
                UPDATE candidates SET cv_parsed_json = ?, updated_at = ?
                WHERE email = ?
                """,
                (cv_json, now, email),
            )
            await conn.commit()
        finally:
            await conn.close()

    async def list_all(
        self,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all candidates (email, name, source_type, updated_at, profile summary)."""
        conn = await self._conn()
        try:
            cur = await conn.execute(
                """
                SELECT id, email, name, source_type, source_id, profile_json, score_json, cv_parsed_json, updated_at
                FROM candidates ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = await cur.fetchall()
            out = []
            for row in rows:
                d = dict(row)
                if d.get("profile_json"):
                    try:
                        d["profile"] = json.loads(d["profile_json"])
                    except Exception:
                        d["profile"] = {}
                else:
                    d["profile"] = {}
                if d.get("score_json"):
                    try:
                        d["score"] = json.loads(d["score_json"])
                    except Exception:
                        d["score"] = {}
                else:
                    d["score"] = {}
                if d.get("cv_parsed_json"):
                    try:
                        d["cv_parsed"] = json.loads(d["cv_parsed_json"])
                    except Exception:
                        d["cv_parsed"] = {}
                else:
                    d["cv_parsed"] = None
                out.append(d)
            return out
        finally:
            await conn.close()

    async def count(self) -> int:
        """Total number of candidates."""
        conn = await self._conn()
        try:
            cur = await conn.execute("SELECT COUNT(*) AS c FROM candidates")
            row = await cur.fetchone()
            return row["c"] if row else 0
        finally:
            await conn.close()
