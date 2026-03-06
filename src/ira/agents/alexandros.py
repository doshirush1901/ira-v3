"""Alexandros — The Librarian.

Gatekeeper of ``data/imports/``.  Every file in the archive has been
catalogued with an LLM-generated summary, entities, machines, topics,
and keywords.  Alexandros holds this catalogue in memory and serves
three functions:

1. **ask** — hybrid search (keyword NN + Voyage semantic) over the
   catalogue, extract text from the best matching files, return raw content.
2. **browse** — list files in a folder with summaries.
3. **read_file** — read a specific file by name.

After every retrieval, the accessed file is queued for proper Qdrant
ingestion during the next sleep cycle.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.brain.imports_fallback_retriever import (
    extract_file_text,
    hybrid_search,
    queue_for_deferred_ingestion,
)
from ira.brain.imports_metadata_index import load_index
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("alexandros_system")


class Alexandros(BaseAgent):
    name = "alexandros"
    role = "Librarian"
    description = (
        "Gatekeeper of the raw document archive. Searches, browses, "
        "and reads files from data/imports/ using LLM-generated metadata."
    )

    # ── main handler (orchestrator entry point) ──────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        context = context or {}
        action = context.get("action", "ask")

        if action == "browse":
            return await self.browse(
                context.get("folder", query),
                doc_type=context.get("doc_type", ""),
            )
        if action == "read_file":
            return await self.read_file(context.get("filename", query))
        if action == "stats":
            return self.stats()

        return await self.ask(query, context)

    # ── Tool 1: ask — the main search interface ─────────────────────────

    async def ask(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Hybrid search the catalogue, extract text, return raw content."""
        context = context or {}

        limit = 5 if context.get("full_text_in_body") else 3
        candidates = await hybrid_search(query, limit=limit)

        if context.get("full_text_in_body") and candidates:
            query_terms = set(re.findall(r"\w+", query.lower())) - {
                "a", "an", "the", "is", "are", "for", "from", "with",
                "and", "or", "in", "on", "to",
            }
            query_terms = {t for t in query_terms if len(t) > 2}
            filtered = []
            for c in candidates:
                path = c.get("path", "")
                if not path or not Path(path).exists():
                    continue
                text = extract_file_text(path).lower()
                if query_terms and any(term in text for term in query_terms):
                    filtered.append(c)
            if filtered:
                candidates = filtered[:3]

        if not candidates:
            folder = self._match_folder(query)
            if folder:
                return await self.browse(folder)
            index = load_index()
            total = len(index.get("files", {}))
            return (
                f"Alexandros: I searched the archive ({total} files) "
                f"but found nothing matching '{query}'. Try different keywords, "
                f"a customer name, machine model, or project number."
            )

        results: list[str] = []
        for candidate in candidates:
            filepath = candidate.get("path", "")
            filename = candidate.get("name", "")
            if not filepath or not Path(filepath).exists():
                continue

            text = extract_file_text(filepath)
            if not text or len(text.strip()) < 30:
                continue

            header = (
                f"━━━ {filename} ━━━\n"
                f"Type: {candidate.get('doc_type', 'unknown')} | "
                f"Summary: {candidate.get('summary', 'N/A')[:200]}\n"
            )
            results.append(header + text)

            queue_for_deferred_ingestion(
                filepath, filename, query,
                candidate.get("doc_type", "other"),
            )

        if not results:
            return "Alexandros: Found candidates but couldn't extract text. Files may be images or corrupted."

        preamble = (
            f"**Alexandros retrieved {len(results)} document(s) from the archive "
            f'for: "{query}"**\n\n'
        )
        return preamble + "\n\n".join(results)

    # ── Tool 2: browse — list files in a folder ─────────────────────────

    async def browse(self, folder_or_query: str, doc_type: str = "") -> str:
        """List files in a folder with summaries."""
        index = load_index()
        files = index.get("files", {})

        folder = self._match_folder(folder_or_query)
        q_lower = folder_or_query.lower()

        matching: list[tuple[str, dict[str, Any]]] = []
        for rel_path, meta in files.items():
            include = False
            if folder and rel_path.startswith(folder + "/"):
                include = True
            elif not folder:
                if q_lower in rel_path.lower() or q_lower in meta.get("summary", "").lower():
                    include = True

            if include and doc_type and meta.get("doc_type", "") != doc_type:
                include = False

            if include:
                matching.append((rel_path, meta))

        if not matching:
            folders = sorted({
                rp.split("/")[0] for rp in files if "/" in rp
            })
            return (
                f"Alexandros: No files found matching '{folder_or_query}'.\n\n"
                f"Available folders:\n"
                + "\n".join(f"  - {f}" for f in folders)
            )

        matching.sort(key=lambda x: x[0])

        lines = [f"**Archive: {folder or folder_or_query}** ({len(matching)} files)\n"]

        by_subfolder: dict[str, list[dict[str, Any]]] = {}
        for rel_path, meta in matching:
            parts = rel_path.split("/")
            subfolder = parts[1] if len(parts) > 2 else "(root)"
            by_subfolder.setdefault(subfolder, []).append(meta)

        for subfolder, metas in sorted(by_subfolder.items()):
            if subfolder != "(root)":
                lines.append(f"\n**{subfolder}/**")
            for meta in metas:
                name = meta.get("name", "?")
                summary = meta.get("summary", "")[:120]
                doc_t = meta.get("doc_type", "")
                machines = ", ".join(meta.get("machines", [])[:3])
                size = meta.get("size_kb", 0)

                line = f"- **{name}** ({doc_t}, {size}KB)"
                if machines:
                    line += f" [{machines}]"
                if summary and not summary.startswith("Document:"):
                    line += f"\n  _{summary}_"
                lines.append(line)

        return "\n".join(lines)

    # ── Tool 3: read_file — read a specific file ────────────────────────

    async def read_file(self, filename_or_path: str) -> str:
        """Read a specific file from the archive by name or path."""
        index = load_index()
        files = index.get("files", {})

        target: dict[str, Any] | None = None
        fn_lower = filename_or_path.lower().strip()

        for rel_path, meta in files.items():
            if rel_path.lower() == fn_lower or meta.get("name", "").lower() == fn_lower:
                target = meta
                break

        if not target:
            for _rel_path, meta in files.items():
                if fn_lower in meta.get("name", "").lower():
                    target = meta
                    break

        if not target:
            return f"Alexandros: File '{filename_or_path}' not found in the archive."

        filepath = target.get("path", "")
        if not filepath or not Path(filepath).exists():
            return f"Alexandros: File '{target.get('name', '')}' is indexed but missing from disk."

        text = extract_file_text(filepath)
        if not text or len(text.strip()) < 10:
            return f"Alexandros: Could not extract text from '{target.get('name', '')}'. It may be an image or corrupted PDF."

        queue_for_deferred_ingestion(
            filepath,
            target.get("name", ""),
            f"file_detail:{filename_or_path}",
            target.get("doc_type", "other"),
        )

        header = (
            f"━━━ {target.get('name', '')} ━━━\n"
            f"Type: {target.get('doc_type', 'unknown')} | "
            f"Size: {target.get('size_kb', 0)}KB | "
            f"Summary: {target.get('summary', 'N/A')[:200]}\n"
            f"Machines: {', '.join(target.get('machines', []))}\n"
            f"Entities: {', '.join(target.get('entities', []))}\n\n"
        )
        return header + text

    # ── stats ────────────────────────────────────────────────────────────

    def stats(self) -> str:
        """Quick stats about the archive."""
        index = load_index()
        files = index.get("files", {})
        total = len(files)

        if total == 0:
            return "Alexandros: Archive is empty. Run `ira index-imports` to build the metadata index."

        by_folder: dict[str, int] = {}
        by_type: dict[str, int] = {}
        llm_count = 0
        for rel_path, meta in files.items():
            folder = rel_path.split("/")[0] if "/" in rel_path else "(root)"
            by_folder[folder] = by_folder.get(folder, 0) + 1
            dt = meta.get("doc_type", "other")
            by_type[dt] = by_type.get(dt, 0) + 1
            s = meta.get("summary", "")
            if not s.startswith("Document:") and len(s) > 20:
                llm_count += 1

        pct = llm_count * 100 // total if total else 0
        lines = [
            "**Alexandros Archive Stats**",
            f"Total files: {total} | LLM-summarized: {llm_count} ({pct}%)",
            f"Built at: {index.get('built_at', 'unknown')}",
            "",
            "**By folder:**",
        ]
        for folder in sorted(by_folder, key=lambda f: -by_folder[f]):
            lines.append(f"  {folder}: {by_folder[folder]}")

        lines.append("\n**By type:**")
        for dt in sorted(by_type, key=lambda t: -by_type[t]):
            lines.append(f"  {dt}: {by_type[dt]}")

        return "\n".join(lines)

    # ── helpers ──────────────────────────────────────────────────────────

    def _match_folder(self, query: str) -> str | None:
        """Try to match a query to a folder name in the index."""
        q = query.lower().strip()
        index = load_index()
        folders: set[str] = set()
        for rel_path in index.get("files", {}):
            if "/" in rel_path:
                folders.add(rel_path.split("/")[0])

        for folder in folders:
            if q in folder.lower() or folder.lower() in q:
                return folder
            parts = folder.lower().replace("_", " ").split()
            if any(p in q for p in parts if len(p) > 3):
                return folder
        return None
