"""Single-instance lock on the Ira data directory.

Only one process (CLI or API server) should use the same data directory at a time
to avoid SQLite "database is locked" and other contention. This module provides
a context manager that acquires an exclusive file lock on data/.ira.lock and
releases it on exit.

Usage:
    with data_dir_lock():
        # run pipeline (CLI)
    async with async_data_dir_lock():
        # run server lifespan
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Data directory: IRA_DATA_DIR env, or cwd/data (assumes process is run from repo root)
def get_data_dir() -> Path:
    raw = os.environ.get("IRA_DATA_DIR", "").strip()
    if raw:
        return Path(raw).resolve()
    return (Path.cwd() / "data").resolve()


def _lock_path() -> Path:
    return get_data_dir() / ".ira.lock"


def _make_lock(timeout: float = 10.0):
    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from filelock import FileLock, Timeout
    except ImportError:
        return None, None
    return FileLock(str(lock_path) + ".lock", timeout=timeout), Timeout


@contextmanager
def data_dir_lock(timeout: float = 10.0):
    """Acquire an exclusive lock on the data directory; release on exit.

    If another Ira process (CLI or server) holds the lock, blocks up to *timeout*
    seconds then raises RuntimeError with a clear message. Use from CLI (ask/chat/task)
    and from the API server lifespan so only one process runs at a time per data dir.
    """
    lock, Timeout = _make_lock(timeout)
    if lock is None:
        logger.warning(
            "filelock not installed — skipping data-dir single-instance lock. "
            "Install with: pip install filelock"
        )
        yield
        return

    try:
        lock.acquire()
        logger.debug("Acquired data-dir lock at %s", _lock_path())
        yield
    except Timeout:
        raise RuntimeError(
            "Another Ira process is using this data directory (CLI or API server). "
            "Stop the other process or use a different IRA_DATA_DIR. "
            f"Lock file: {_lock_path()}"
        ) from None
    finally:
        try:
            lock.release()
            logger.debug("Released data-dir lock")
        except Exception:
            pass


@asynccontextmanager
async def async_data_dir_lock(timeout: float = 10.0):
    """Async version: acquire lock in a thread so the event loop is not blocked."""
    lock, Timeout = _make_lock(timeout)
    if lock is None:
        logger.warning(
            "filelock not installed — skipping data-dir single-instance lock."
        )
        yield
        return

    try:
        await asyncio.to_thread(lock.acquire)
        logger.debug("Acquired data-dir lock at %s (server)", _lock_path())
        yield
    except Timeout:
        raise RuntimeError(
            "Another Ira process is using this data directory (CLI or API server). "
            "Stop the other process or use a different IRA_DATA_DIR. "
            f"Lock file: {_lock_path()}"
        ) from None
    finally:
        try:
            await asyncio.to_thread(lock.release)
            logger.debug("Released data-dir lock (server)")
        except Exception:
            pass
