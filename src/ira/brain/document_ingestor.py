"""Document ingestion pipeline for Ira's knowledge base.

Walks the ``data/imports/`` directory tree, reads files in every supported
format (PDF, XLSX, DOCX, CSV, TXT), splits them into token-counted
overlapping chunks, and upserts the resulting :class:`KnowledgeItem` objects
into Qdrant via :class:`QdrantManager`.

A lightweight SQLite ledger (``data/ingested_files.db``) tracks which files
have already been processed so that re-running ingestion is idempotent.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tiktoken

from ira.brain.qdrant_manager import QdrantManager
from ira.data.models import KnowledgeItem

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ira.brain.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".docx", ".txt", ".csv"}
_DEFAULT_CHUNK_SIZE = 512
_DEFAULT_OVERLAP = 128
_TIKTOKEN_ENCODING = "cl100k_base"

_LEDGER_PATH = Path("data/ingested_files.db")

_CATEGORY_PATTERN = re.compile(r"^\d{2}_(.+)$")


# ── SQLite ledger ────────────────────────────────────────────────────────────


def _init_ledger(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingested_files (
            path        TEXT PRIMARY KEY,
            hash        TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            ingested_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# ── file readers ─────────────────────────────────────────────────────────────


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        parts.append(f"[Sheet: {sheet}]")
        for row in ws.iter_rows(values_only=True):
            parts.append("\t".join(str(cell) if cell is not None else "" for cell in row))
    wb.close()
    return "\n".join(parts)


def read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(para.text for para in doc.paragraphs)


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_csv(path: Path) -> str:
    buf = io.StringIO()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            buf.write("\t".join(row) + "\n")
    return buf.getvalue()


_READERS = {
    ".pdf": read_pdf,
    ".xlsx": read_xlsx,
    ".docx": read_docx,
    ".txt": read_txt,
    ".csv": read_csv,
}


# ── chunking ─────────────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[str]:
    """Split *text* into overlapping chunks measured in tokens.

    Uses tiktoken's ``cl100k_base`` encoding for accurate token counts.
    Returns raw text strings (not token IDs).
    """
    enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
    tokens = enc.encode(text)

    if len(tokens) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += chunk_size - overlap

    return chunks


# ── category extraction ──────────────────────────────────────────────────────


def _category_from_path(file_path: Path, base_path: Path) -> str:
    """Derive a source_category slug from the first directory under *base_path*.

    Expects folder names like ``01_Quotes_and_Proposals``.  Returns the part
    after the numeric prefix, lowercased (e.g. ``quotes_and_proposals``).
    Falls back to ``"uncategorised"`` if the pattern doesn't match.
    """
    try:
        relative = file_path.relative_to(base_path)
        top_dir = relative.parts[0] if relative.parts else ""
    except ValueError:
        return "uncategorised"

    m = _CATEGORY_PATTERN.match(top_dir)
    return m.group(1).lower() if m else top_dir.lower() or "uncategorised"


# ── ingestor class ───────────────────────────────────────────────────────────


class DocumentIngestor:
    """Reads, chunks, and upserts documents from the imports directory."""

    def __init__(
        self,
        qdrant: QdrantManager,
        *,
        knowledge_graph: "KnowledgeGraph | None" = None,
        ledger_path: Path = _LEDGER_PATH,
    ) -> None:
        self._qdrant = qdrant
        self._graph = knowledge_graph
        self._ledger = _init_ledger(ledger_path)

    # ── discovery ────────────────────────────────────────────────────────

    def discover_files(self, base_path: str = "data/imports") -> list[dict[str, Any]]:
        """Walk *base_path* and return metadata for every supported file."""
        root = Path(base_path)
        if not root.exists():
            logger.warning("Import directory does not exist: %s", root)
            return []

        files: list[dict[str, Any]] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in _SUPPORTED_EXTENSIONS:
                continue
            files.append(
                {
                    "path": str(p),
                    "category": _category_from_path(p, root),
                    "extension": ext,
                    "size": p.stat().st_size,
                }
            )

        logger.info("Discovered %d importable files under %s", len(files), root)
        return files

    # ── single-file ingestion ────────────────────────────────────────────

    def is_already_ingested(self, file_info: dict[str, Any]) -> bool:
        """Check whether a file has already been ingested with the same hash."""
        path = Path(file_info["path"])
        return self._already_ingested(str(path), _file_hash(path))

    async def ingest_file(
        self,
        file_info: dict[str, Any],
        *,
        force: bool = False,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        overlap: int = _DEFAULT_OVERLAP,
    ) -> int:
        """Read, chunk, and upsert one file.  Returns the chunk count.

        When *force* is ``True`` the ledger check is skipped and any
        existing Qdrant points for this source path are deleted first.
        """
        path = Path(file_info["path"])
        category = file_info["category"]
        ext = file_info["extension"]

        current_hash = _file_hash(path)
        if not force and self._already_ingested(str(path), current_hash):
            logger.debug("Skipping already-ingested file: %s", path)
            return 0

        if force:
            await self._qdrant.delete_by_source(str(path))

        reader = _READERS.get(ext)
        if reader is None:
            logger.warning("No reader for extension '%s': %s", ext, path)
            return 0

        text = reader(path)
        if not text.strip():
            logger.warning("Empty content after reading: %s", path)
            return 0

        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

        items = [
            KnowledgeItem(
                source=str(path),
                source_category=category,
                content=chunk,
                metadata={
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "extension": ext,
                },
            )
            for i, chunk in enumerate(chunks)
        ]

        upserted = await self._qdrant.upsert_items(items)

        if self._graph is not None:
            await self._extract_and_store_entities(text, str(path))

        self._record_ingestion(str(path), current_hash, upserted)
        logger.info("Ingested %s -> %d chunks (category: %s)", path, upserted, category)
        return upserted

    # ── bulk ingestion ───────────────────────────────────────────────────

    async def ingest_all(
        self,
        base_path: str = "data/imports",
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Process every supported file under *base_path*.

        Returns a summary dict with keys ``files_processed``,
        ``files_skipped``, ``total_chunks``, ``per_category``, and
        ``errors`` (a list of ``{"path": ..., "error": ...}`` dicts).
        """
        files = self.discover_files(base_path)

        files_processed = 0
        files_skipped = 0
        total_chunks = 0
        per_category: dict[str, int] = {}
        errors: list[dict[str, str]] = []

        for file_info in files:
            try:
                n = await self.ingest_file(file_info, force=force)
                if n > 0:
                    files_processed += 1
                    total_chunks += n
                    cat = file_info["category"]
                    per_category[cat] = per_category.get(cat, 0) + n
                else:
                    files_skipped += 1
            except Exception as exc:
                logger.exception("Failed to ingest %s", file_info["path"])
                errors.append({"path": file_info["path"], "error": str(exc)})

        summary: dict[str, Any] = {
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "total_chunks": total_chunks,
            "per_category": per_category,
            "errors": errors,
        }
        logger.info("Ingestion complete: %s", summary)
        return summary

    # ── entity extraction ─────────────────────────────────────────────────

    async def _extract_and_store_entities(self, text: str, source: str) -> None:
        """Extract entities from document text and store them in Neo4j."""
        assert self._graph is not None
        try:
            entities = await self._graph.extract_entities_from_text(text)
        except Exception:
            logger.exception("Entity extraction failed for %s", source)
            return

        for company in entities.get("companies", []):
            try:
                await self._graph.add_company(
                    name=company.get("name", ""),
                    region=company.get("region", ""),
                    industry=company.get("industry", ""),
                )
            except Exception:
                logger.warning("Failed to add company from %s: %s", source, company)

        for person in entities.get("people", []):
            try:
                await self._graph.add_person(
                    name=person.get("name", ""),
                    email=person.get("email", ""),
                    company_name=person.get("company", ""),
                    role=person.get("role", ""),
                )
            except Exception:
                logger.warning("Failed to add person from %s: %s", source, person)

        for machine in entities.get("machines", []):
            try:
                await self._graph.add_machine(
                    model=machine.get("model", ""),
                    category=machine.get("category", ""),
                    description=machine.get("description", ""),
                )
            except Exception:
                logger.warning("Failed to add machine from %s: %s", source, machine)

        logger.info(
            "Extracted entities from %s: %d companies, %d people, %d machines",
            source,
            len(entities.get("companies", [])),
            len(entities.get("people", [])),
            len(entities.get("machines", [])),
        )

    # ── ledger helpers ───────────────────────────────────────────────────

    def _already_ingested(self, path: str, file_hash: str) -> bool:
        row = self._ledger.execute(
            "SELECT hash FROM ingested_files WHERE path = ?", (path,)
        ).fetchone()
        return row is not None and row[0] == file_hash

    def _record_ingestion(self, path: str, file_hash: str, chunk_count: int) -> None:
        self._ledger.execute(
            """
            INSERT INTO ingested_files (path, hash, chunk_count, ingested_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash = excluded.hash,
                chunk_count = excluded.chunk_count,
                ingested_at = excluded.ingested_at
            """,
            (path, file_hash, chunk_count, datetime.now(timezone.utc).isoformat()),
        )
        self._ledger.commit()

    def close(self) -> None:
        self._ledger.close()
