"""On-the-fly knowledge gap detection and filling.

When retrieval results are thin or miss the mark, :class:`KnowledgeDiscovery`
detects the gap via an LLM call, scans the raw imports archive for candidate
files, deep-extracts relevant facts, and stores them in Qdrant so future
queries hit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from ira.brain.document_ingestor import chunk_text
from ira.brain.embeddings import EmbeddingService
from ira.brain.imports_metadata_index import (
    IMPORTS_DIR,
    SUPPORTED_EXTENSIONS,
    _extract_preview,
    search_index,
)
from ira.brain.qdrant_manager import QdrantManager
from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.data.models import KnowledgeItem
from ira.exceptions import DatabaseError, PathTraversalError

logger = logging.getLogger(__name__)

_GAP_DETECT_SYSTEM = (
    "You are a knowledge-gap analyst. The user asked a question and received "
    "search results. Determine whether the results adequately answer the query. "
    "If there is a gap, return JSON: "
    '{"gap_type": "missing|partial|outdated", '
    '"description": "what is missing", '
    '"suggested_search": "keywords to find the missing info"}. '
    "If the results are sufficient, return null."
)

_DEEP_EXTRACT_SYSTEM = (
    "You are a fact-extraction engine. Given a document excerpt and a user "
    "query, extract every fact from the document that is relevant to the query. "
    "Return JSON: "
    '{"facts": [{"content": "...", "entity": "...", "category": "..."}]}'
)


class KnowledgeDiscovery:
    """Detect retrieval gaps and fill them from the raw imports archive."""

    def __init__(
        self,
        retriever: UnifiedRetriever,
        qdrant_manager: QdrantManager,
        embedding_service: EmbeddingService,
        imports_dir: Path = Path("data/imports"),
    ) -> None:
        self._retriever = retriever
        self._qdrant = qdrant_manager
        self._embeddings = embedding_service
        self._imports_dir = imports_dir
        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

    # ── public API ────────────────────────────────────────────────────────

    async def detect_gap(
        self,
        query: str,
        search_results: list[dict],
    ) -> dict | None:
        """LLM analyzes query vs results and returns a gap descriptor or None."""
        results_summary = json.dumps(
            [
                {
                    "content": r.get("content", "")[:300],
                    "score": r.get("score", 0),
                    "source": r.get("source", ""),
                }
                for r in search_results[:10]
            ],
            default=str,
        )
        user_msg = f"QUERY: {query}\n\nSEARCH RESULTS:\n{results_summary}"
        raw = await self._llm_call(_GAP_DETECT_SYSTEM, user_msg)
        parsed = self._safe_parse(raw)

        if parsed is None or parsed == "null":
            return None
        if isinstance(parsed, dict) and "gap_type" in parsed:
            logger.info("Gap detected for '%s': %s", query[:60], parsed.get("gap_type"))
            return parsed
        return None

    async def find_candidate_files(self, gap: dict) -> list[dict]:
        """Score files in the imports directory by relevance to the gap.

        Uses the imports metadata index for keyword/entity/doc_type scoring.
        Returns the top 5 candidates.
        """
        search_query = gap.get("suggested_search", gap.get("description", ""))
        if not search_query:
            return []

        candidates = await search_index(search_query, limit=5)
        logger.info(
            "Found %d candidate files for gap '%s'",
            len(candidates),
            gap.get("description", "")[:60],
        )
        return candidates

    async def deep_scan_and_extract(
        self,
        filepath: str,
        query: str,
    ) -> list[dict]:
        """Extract text from a file and use LLM to pull relevant facts."""
        path = Path(filepath)
        project_root = Path(__file__).resolve().parents[3]
        data_root = project_root / "data"
        if not path.resolve().is_relative_to(data_root):
            raise PathTraversalError(f"Path {filepath} is outside the data directory")

        if not path.exists():
            logger.warning("Candidate file not found: %s", filepath)
            return []

        text = _extract_preview(path)
        if not text:
            return []

        if path.suffix in (".txt", ".csv", ".md", ".json"):
            full_text = await asyncio.to_thread(path.read_text, errors="ignore")
        else:
            full_text = text

        user_msg = f"QUERY: {query}\n\nDOCUMENT ({path.name}):\n{full_text[:8000]}"
        raw = await self._llm_call(_DEEP_EXTRACT_SYSTEM, user_msg)
        parsed = self._safe_parse(raw)

        if isinstance(parsed, dict):
            facts = parsed.get("facts", [])
            logger.info("Extracted %d facts from %s", len(facts), path.name)
            return facts
        return []

    async def discover_and_store(
        self,
        query: str,
        search_results: list[dict],
    ) -> list[dict]:
        """Full pipeline: detect gap -> find candidates -> deep scan -> store.

        Returns the list of newly discovered knowledge items.
        """
        gap = await self.detect_gap(query, search_results)
        if gap is None:
            return []

        candidates = await self.find_candidate_files(gap)
        if not candidates:
            logger.info("No candidate files found for gap: %s", gap.get("description", ""))
            return []

        discovered: list[dict] = []
        for candidate in candidates:
            filepath = candidate.get("path", "")
            if not filepath:
                continue

            facts = await self.deep_scan_and_extract(filepath, query)
            for fact in facts:
                content = fact.get("content", "")
                if not content:
                    continue

                item = KnowledgeItem(
                    source=f"discovery:{filepath}",
                    source_category=fact.get("category", "discovered").lower(),
                    content=content,
                    metadata={
                        "discovery_source": filepath,
                        "entity": fact.get("entity", ""),
                        "gap_type": gap.get("gap_type", ""),
                        "original_query": query[:200],
                    },
                )
                try:
                    await self._qdrant.upsert_items([item])
                    discovered.append(fact)
                except (DatabaseError, Exception):
                    logger.exception("Failed to store discovered fact from %s", filepath)

        logger.info(
            "Discovery complete: %d new facts stored for query '%s'",
            len(discovered),
            query[:60],
        )
        return discovered

    # ── LLM ───────────────────────────────────────────────────────────────

    async def _llm_call(self, system: str, user: str, temperature: float = 0.0) -> str:
        if not self._openai_key:
            return "(No OpenAI key configured)"
        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("KnowledgeDiscovery LLM call failed")
            return "(LLM call failed)"

    @staticmethod
    def _safe_parse(raw: str) -> Any:
        cleaned = raw.strip()
        if cleaned.lower() == "null":
            return None
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return {"raw_response": raw}
