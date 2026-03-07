"""LLM-summarised metadata index for every file in ``data/imports/``.

Scans the imports directory, extracts a short text preview from each file,
and uses GPT-4.1-mini to generate structured metadata (summary, doc_type,
machines, topics, entities, keywords).  The index is persisted to
``data/brain/imports_metadata.json`` and powers Alexandros's hybrid search.

The index is idempotent — files are fingerprinted by name+size+mtime and
only re-indexed when they change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from ira.brain.document_ingestor import (
    read_csv,
    read_docx,
    read_pdf,
    read_pptx,
    read_txt,
    read_xls,
    read_xlsx,
)
from ira.config import get_settings
from ira.exceptions import IngestionError, IraError, LLMError

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMPORTS_DIR = _PROJECT_ROOT / "data" / "imports"
INDEX_PATH = _PROJECT_ROOT / "data" / "brain" / "imports_metadata.json"
INDEX_PROGRESS_PATH = _PROJECT_ROOT / "data" / "brain" / "imports_index_progress.json"

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".txt", ".pptx", ".json", ".md"}
_TEXT_PREVIEW_CHARS = 2000
_LLM_MODEL = "gpt-4.1-mini"

_READERS: dict[str, Callable[[Path], str]] = {
    ".pdf": read_pdf,
    ".xlsx": read_xlsx,
    ".xls": read_xls,
    ".docx": read_docx,
    ".txt": read_txt,
    ".csv": read_csv,
    ".pptx": read_pptx,
}


# ── text extraction (lightweight preview) ────────────────────────────────


def _extract_preview(filepath: Path) -> str:
    """Extract the first ~2000 chars of text from a file."""
    reader = _READERS.get(filepath.suffix.lower())
    if reader is not None:
        try:
            return reader(filepath)[:_TEXT_PREVIEW_CHARS]
        except (IngestionError, Exception):
            logger.debug("Reader failed for %s, trying plain text", filepath.name)

    if filepath.suffix.lower() in (".txt", ".json", ".csv", ".md"):
        try:
            return filepath.read_text(errors="ignore")[:_TEXT_PREVIEW_CHARS]
        except (IraError, Exception):
            logger.debug("Plain-text read failed for %s", filepath.name)
    return ""


def _file_fingerprint(filepath: Path) -> str:
    """Quick hash based on name+size+mtime (not content — too slow for 700+ files)."""
    stat = filepath.stat()
    key = f"{filepath.name}:{stat.st_size}:{int(stat.st_mtime)}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ── LLM metadata generation ─────────────────────────────────────────────


async def _generate_metadata_llm(filename: str, text_preview: str) -> dict[str, Any] | None:
    """Use GPT-4.1-mini to produce structured metadata from a file preview."""
    settings = get_settings()
    api_key = settings.llm.openai_api_key.get_secret_value()
    if not api_key:
        return None

    prompt = f"""Analyze this document and return structured metadata as JSON.

FILENAME: {filename}

TEXT PREVIEW (first {_TEXT_PREVIEW_CHARS} chars):
{text_preview[:_TEXT_PREVIEW_CHARS]}

Return ONLY valid JSON with these fields:
{{
    "summary": "1-2 sentence description of what this document is about",
    "doc_type": "one of: quote, catalogue, order, presentation, email, spreadsheet, report, manual, contract, lead_list, customer_data, technical_spec, brochure, invoice, other",
    "machines": ["list of machine models mentioned, e.g. PF1-C-2015, AM-5060"],
    "topics": ["list from: pricing, specs, customer, application, lead, order, contract, presentation, marketing, technical, installation, warranty, shipping, competitor, market_research, training"],
    "entities": ["company names, person names, countries mentioned"],
    "keywords": ["5-10 important searchable terms from the document"]
}}"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _LLM_MODEL,
        "temperature": 0.1,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": "Extract structured metadata from documents. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)
    except (LLMError, Exception) as exc:
        logger.warning("LLM metadata failed for %s: %s", filename, exc)
        return None


def _generate_metadata_local(filename: str, text_preview: str) -> dict[str, Any]:
    """Fast local metadata extraction without LLM (fallback)."""
    name_lower = filename.lower()

    machines = re.findall(
        r"(PF1[-\s]?[A-Z]?[-\s]?\d+[-\s]?\d*|AM[-\s]?\w+\d+|IMG[-\s]?\d+|FCS[-\s]?\w+|UNO[-\s]?\w+|DUO[-\s]?\w+)",
        filename + " " + text_preview[:500],
        re.IGNORECASE,
    )
    machines = list({m.upper().replace(" ", "-") for m in machines})

    doc_type = "other"
    type_keywords: dict[str, list[str]] = {
        "quote": ["quote", "quotation", "offer", "price"],
        "catalogue": ["catalogue", "catalog", "brochure"],
        "order": ["order", "po", "purchase"],
        "presentation": ["ppt", "presentation", "pptx"],
        "email": ["gmail", "email", "mail"],
        "spreadsheet": ["xlsx", "xls", "csv"],
        "manual": ["manual", "instruction", "operating"],
        "contract": ["contract", "nda", "agreement"],
        "lead_list": ["lead", "contact", "inquiry", "visitor"],
        "technical_spec": ["spec", "technical", "table"],
    }
    for dtype, kws in type_keywords.items():
        if any(kw in name_lower for kw in kws):
            doc_type = dtype
            break

    words = re.findall(r"\b\w{4,}\b", (filename + " " + text_preview[:300]).lower())
    keywords = list(set(words))[:10]

    return {
        "summary": f"Document: {filename}",
        "doc_type": doc_type,
        "machines": machines,
        "topics": [],
        "entities": [],
        "keywords": keywords,
    }


# ── index persistence ────────────────────────────────────────────────────


async def load_index() -> dict[str, Any]:
    """Load the metadata index from disk."""
    if INDEX_PATH.exists():
        try:
            raw = await asyncio.to_thread(INDEX_PATH.read_text)
            return json.loads(raw)
        except (json.JSONDecodeError, IOError):
            logger.error("Corrupt metadata index at %s", INDEX_PATH)
    return {"files": {}, "built_at": None, "total_files": 0, "version": 2}


async def _save_index(index: dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(
        INDEX_PATH.write_text, json.dumps(index, indent=2, ensure_ascii=False),
    )


async def _save_progress(done: int, total: int, current_file: str) -> None:
    INDEX_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(INDEX_PROGRESS_PATH.write_text, json.dumps({
        "done": done,
        "total": total,
        "current": current_file,
        "percent": round(done / total * 100, 1) if total else 0,
        "updated_at": datetime.now().isoformat(),
    }, indent=2))


# ── index building ───────────────────────────────────────────────────────


async def build_index(
    *,
    use_llm: bool = True,
    force: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Build or incrementally update the metadata index.

    Returns stats: ``{"total", "new", "skipped", "errors"}``.
    """
    index = (await load_index()) if not force else {"files": {}, "built_at": None, "total_files": 0, "version": 2}

    all_files = [
        fp for fp in IMPORTS_DIR.rglob("*")
        if fp.is_file() and not fp.name.startswith(".") and fp.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    total = len(all_files)
    new_count = 0
    skipped = 0
    errors = 0

    for i, fp in enumerate(all_files):
        fhash = _file_fingerprint(fp)
        rel_path = str(fp.relative_to(IMPORTS_DIR))

        if not force and rel_path in index["files"] and index["files"][rel_path].get("hash") == fhash:
            skipped += 1
            continue

        if progress_callback:
            progress_callback(i + 1, total, fp.name)
        await _save_progress(i + 1, total, fp.name)

        try:
            preview = _extract_preview(fp)

            metadata: dict[str, Any] | None = None
            if use_llm and preview and len(preview) > 50:
                metadata = await _generate_metadata_llm(fp.name, preview)
            if metadata is None:
                metadata = _generate_metadata_local(fp.name, preview)

            index["files"][rel_path] = {
                "name": fp.name,
                "path": str(fp),
                "hash": fhash,
                "size_kb": fp.stat().st_size // 1024,
                "extension": fp.suffix.lower(),
                "indexed_at": datetime.now().isoformat(),
                **metadata,
            }
            new_count += 1

            if new_count % 20 == 0:
                await _save_index(index)

            if use_llm and preview and len(preview) > 50:
                await asyncio.sleep(0.3)

        except (IngestionError, Exception) as exc:
            logger.warning("Error indexing %s: %s", fp.name, exc)
            errors += 1

    index["built_at"] = datetime.now().isoformat()
    index["total_files"] = len(index["files"])
    await _save_index(index)

    if INDEX_PROGRESS_PATH.exists():
        INDEX_PROGRESS_PATH.unlink()

    stats = {"total": total, "new": new_count, "skipped": skipped, "errors": errors}
    logger.info("Index built: %s", stats)
    return stats


# ── keyword search ───────────────────────────────────────────────────────


_STEM_MAP: dict[str, str] = {
    "quotes": "quote", "quotations": "quote", "quotation": "quote",
    "machines": "machine", "specifications": "spec", "specs": "spec",
    "proposals": "proposal", "orders": "order", "invoices": "invoice",
    "contracts": "contract", "presentations": "presentation",
    "customers": "customer", "companies": "company",
    "documents": "document", "files": "file",
    "brochures": "brochure", "catalogues": "catalogue", "catalogs": "catalogue",
    "manuals": "manual", "reports": "report", "emails": "email",
}

_TOPIC_TRIGGERS: dict[str, set[str]] = {
    "pricing": {"price", "cost", "quote", "lakh", "usd", "inr", "euro", "budget"},
    "specs": {"spec", "specification", "technical", "heater", "vacuum", "forming", "dimension"},
    "customer": {"customer", "order", "client", "company", "buyer"},
    "application": {"application", "automotive", "bathtub", "packaging", "food", "medical"},
    "lead": {"lead", "prospect", "inquiry", "visitor", "contact"},
    "marketing": {"marketing", "campaign", "drip", "newsletter", "linkedin"},
    "shipping": {"shipping", "freight", "logistics", "delivery", "transport"},
    "installation": {"installation", "commissioning", "setup", "assembly"},
    "competitor": {"competitor", "competition", "illig", "kiefel", "brown", "maac"},
}


def _stem_words(words: set[str]) -> set[str]:
    """Expand a word set with basic stem normalisations."""
    expanded = set(words)
    for w in words:
        if w in _STEM_MAP:
            expanded.add(_STEM_MAP[w])
        for full, stem in _STEM_MAP.items():
            if stem == w:
                expanded.add(full)
    return expanded


async def search_index(
    query: str,
    limit: int = 10,
    doc_type_filter: str = "",
) -> list[dict[str, Any]]:
    """Score files against a query using metadata fields.

    Weights: machine match (5), entity match (3), topic match (2),
    keyword overlap (1), summary hit (0.5), filename hit (0.3).

    *doc_type_filter*: if set, only return files of this doc_type.
    """
    index = await load_index()
    if not index.get("files"):
        return []

    query_lower = query.lower()
    query_words = _stem_words(set(re.findall(r"\b\w{3,}\b", query_lower)))

    query_machines = {
        m.upper().replace(" ", "-")
        for m in re.findall(
            r"(PF1[-\s]?[A-Z]?[-\s]?\d+[-\s]?\d*|AM[-\s]?\w+|IMG[-\s]?\d+|FCS[-\s]?\w+|UNO[-\s]?\w+|DUO[-\s]?\w+)",
            query,
            re.IGNORECASE,
        )
    }

    results: list[dict[str, Any]] = []
    for rel_path, meta in index["files"].items():
        if doc_type_filter and meta.get("doc_type", "") != doc_type_filter:
            continue

        score = 0.0

        file_machines = {m.upper() for m in meta.get("machines", [])}
        score += len(query_machines & file_machines) * 5.0

        file_keywords = {k.lower() for k in meta.get("keywords", [])}
        score += len(query_words & file_keywords) * 1.0

        file_topics = {t.lower() for t in meta.get("topics", [])}
        for topic, triggers in _TOPIC_TRIGGERS.items():
            if triggers & query_words and topic in file_topics:
                score += 2.0

        for entity in meta.get("entities", []):
            if entity.lower() in query_lower:
                score += 3.0

        summary = meta.get("summary", "").lower()
        score += sum(0.5 for w in query_words if w in summary and len(w) > 3)

        name_lower = meta.get("name", "").lower()
        score += sum(0.3 for w in query_words if w in name_lower and len(w) > 3)

        if score > 0.3:
            results.append({
                "path": meta.get("path", ""),
                "name": meta.get("name", ""),
                "score": round(score, 2),
                "summary": meta.get("summary", ""),
                "doc_type": meta.get("doc_type", ""),
                "machines": meta.get("machines", []),
                "topics": meta.get("topics", []),
            })

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


# ── stats ────────────────────────────────────────────────────────────────


async def get_index_stats() -> dict[str, Any]:
    """Return summary statistics about the current index."""
    index = await load_index()
    files = index.get("files", {})
    if not files:
        return {"indexed": 0, "built_at": None}

    doc_types: dict[str, int] = {}
    all_machines: set[str] = set()
    for meta in files.values():
        dt = meta.get("doc_type", "other")
        doc_types[dt] = doc_types.get(dt, 0) + 1
        all_machines.update(meta.get("machines", []))

    on_disk = sum(
        1 for f in IMPORTS_DIR.rglob("*")
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ) if IMPORTS_DIR.exists() else 0

    return {
        "indexed": len(files),
        "total_on_disk": on_disk,
        "unindexed": on_disk - len(files),
        "built_at": index.get("built_at"),
        "doc_types": doc_types,
        "unique_machines": len(all_machines),
        "top_machines": sorted(all_machines)[:20],
    }
