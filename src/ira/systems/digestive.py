"""Digestive system — data ingestion with nutrient extraction.

Orchestrates the full data ingestion pipeline using a biological metaphor:
MOUTH (receive) → STOMACH (LLM nutrient extraction) → DUODENUM (LLM
summarization into searchable statements) → SMALL INTESTINE (chunk +
embed + upsert) → LIVER (entity extraction into knowledge graph).

The key insight: not all data is equal.  The nutrient extraction step ensures
only high-value information is stored, and the summarization step rewrites
raw facts into clean, self-contained statements that embed well for retrieval.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langfuse.decorators import observe

from ira.brain.document_ingestor import DocumentIngestor, chunk_text
from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.quality_filter import QualityFilter
from ira.brain.qdrant_manager import QdrantManager
from ira.data.models import Email, KnowledgeItem
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import DigestiveSummary, EmailMetadata, NutrientClassification
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_NUTRIENT_SYSTEM_PROMPT = load_prompt("digestive_nutrient")
_SUMMARIZE_SYSTEM_PROMPT = load_prompt("digestive_summarize")
_EMAIL_META_SYSTEM_PROMPT = load_prompt("digestive_email_meta")


class DigestiveSystem:
    """Orchestrates the full data ingestion pipeline."""

    def __init__(
        self,
        ingestor: DocumentIngestor,
        knowledge_graph: KnowledgeGraph,
        embedding_service: EmbeddingService,
        qdrant: QdrantManager,
    ) -> None:
        self._ingestor = ingestor
        self._graph = knowledge_graph
        self._embeddings = embedding_service
        self._qdrant = qdrant
        self._quality_filter = QualityFilter(
            qdrant_manager=qdrant, embedding_service=embedding_service,
        )
        self._llm = get_llm_client()

    _WINDOW_SIZE = 10_000
    _WINDOW_OVERLAP = 500

    # ── STOMACH: nutrient extraction ──────────────────────────────────────

    async def _extract_nutrients(self, raw_data: str) -> dict[str, list[str]]:
        """Use an LLM to classify text into protein / carbs / waste.

        Long documents are split into overlapping windows so that every
        part of the text is seen by the model.  Results from each window
        are merged into a single nutrient dict.
        """
        if self._llm._openai is None:
            logger.warning("No OpenAI API key — skipping nutrient extraction")
            return {"protein": [raw_data], "carbs": [], "waste": []}

        windows = self._split_windows(raw_data)
        merged: dict[str, list[str]] = {"protein": [], "carbs": [], "waste": []}

        for i, window in enumerate(windows):
            result = await self._classify_window(window)
            for key in ("protein", "carbs", "waste"):
                merged[key].extend(result.get(key, []))
            if len(windows) > 1:
                logger.debug(
                    "Nutrient window %d/%d: protein=%d carbs=%d waste=%d",
                    i + 1, len(windows),
                    len(result.get("protein", [])),
                    len(result.get("carbs", [])),
                    len(result.get("waste", [])),
                )

        return merged

    def _split_windows(self, text: str) -> list[str]:
        """Split *text* into overlapping character windows for nutrient extraction."""
        if len(text) <= self._WINDOW_SIZE:
            return [text]

        windows: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self._WINDOW_SIZE, len(text))
            windows.append(text[start:end])
            if end == len(text):
                break
            start += self._WINDOW_SIZE - self._WINDOW_OVERLAP
        return windows

    async def _classify_window(self, text: str) -> dict[str, list[str]]:
        """Send a single text window to the LLM for nutrient classification."""
        result = await self._llm.generate_structured(
            _NUTRIENT_SYSTEM_PROMPT, text, NutrientClassification,
            name="digestive.classify",
        )
        return result.model_dump()

    # ── DUODENUM: summarization ─────────────────────────────────────────

    async def _summarize_nutrients(
        self, nutrients: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Rewrite raw protein + carbs items as clean, searchable statements.

        This bridges the gap between raw extracted facts and high-quality
        embeddings.  Each statement is self-contained so it retrieves well
        in semantic search.  Waste is passed through unchanged.
        """
        if self._llm._openai is None:
            return nutrients

        summarized: dict[str, list[str]] = {"protein": [], "carbs": [], "waste": nutrients.get("waste", [])}

        for nutrient_type in ("protein", "carbs"):
            items = nutrients.get(nutrient_type, [])
            if not items:
                continue

            batch_text = "\n".join(f"- {item}" for item in items)
            for window in self._split_windows(batch_text):
                statements = await self._call_summarize(window)
                summarized[nutrient_type].extend(statements)

        logger.debug(
            "Summarized: protein %d->%d, carbs %d->%d statements",
            len(nutrients.get("protein", [])), len(summarized["protein"]),
            len(nutrients.get("carbs", [])), len(summarized["carbs"]),
        )
        return summarized

    async def _call_summarize(self, text: str) -> list[str]:
        """Send nutrient items to the LLM for summarization into searchable statements."""
        result = await self._llm.generate_structured(
            _SUMMARIZE_SYSTEM_PROMPT, text, DigestiveSummary,
            name="digestive.summarize",
        )
        return [s for s in result.statements if isinstance(s, str) and s.strip()]

    # ── SMALL INTESTINE: absorption ───────────────────────────────────────

    async def _absorb(
        self,
        nutrients: dict[str, list[str]],
        source: str,
        source_category: str,
    ) -> int:
        """Chunk protein + carbs and upsert into Qdrant."""
        protein_text = "\n".join(nutrients.get("protein", []))
        carbs_text = "\n".join(nutrients.get("carbs", []))

        items: list[KnowledgeItem] = []

        if protein_text.strip():
            for i, chunk in enumerate(chunk_text(protein_text)):
                items.append(
                    KnowledgeItem(
                        source=source,
                        source_category=source_category,
                        content=chunk,
                        metadata={"nutrient": "protein", "chunk_index": i},
                    )
                )

        if carbs_text.strip():
            for i, chunk in enumerate(chunk_text(carbs_text)):
                items.append(
                    KnowledgeItem(
                        source=source,
                        source_category=source_category,
                        content=chunk,
                        metadata={"nutrient": "carbs", "chunk_index": i},
                    )
                )

        if not items:
            return 0

        filtered = []
        for item in items:
            result = self._quality_filter.filter_chunk(item.content)
            if result["pass"]:
                filtered.append(item)
            else:
                logger.debug("Quality filter rejected chunk (score=%.2f): %s",
                             result["quality_score"], result["reason"])
        items = filtered

        if not items:
            return 0

        return await self._qdrant.upsert_items(items)

    # ── LIVER: entity extraction ──────────────────────────────────────────

    async def _extract_entities(self, protein_text: str) -> dict[str, int]:
        """Extract entities from protein content and add to the knowledge graph."""
        if not protein_text.strip():
            return {"companies": 0, "people": 0, "machines": 0, "relationships": 0}

        extracted = await self._graph.extract_entities_from_text(protein_text)

        counts: dict[str, int] = {"companies": 0, "people": 0, "machines": 0}

        for company in extracted.get("companies", []):
            if company.get("name"):
                await self._graph.add_company(
                    name=company["name"],
                    region=company.get("region", ""),
                    industry=company.get("industry", ""),
                    website=company.get("website", ""),
                )
                counts["companies"] += 1

        for person in extracted.get("people", []):
            if person.get("name"):
                await self._graph.add_person(
                    name=person["name"],
                    email=person.get("email", ""),
                    company_name=person.get("company", ""),
                    role=person.get("role", ""),
                )
                counts["people"] += 1

        for machine in extracted.get("machines", []):
            if machine.get("model"):
                await self._graph.add_machine(
                    model=machine["model"],
                    category=machine.get("category", ""),
                    description=machine.get("description", ""),
                )
                counts["machines"] += 1

        rel_count = 0
        for rel in extracted.get("relationships", []):
            try:
                ok = await self._graph.add_relationship(
                    from_type=rel.get("from_type", ""),
                    from_key=rel.get("from_key", ""),
                    rel_type=rel.get("rel", ""),
                    to_type=rel.get("to_type", ""),
                    to_key=rel.get("to_key", ""),
                    properties={k: v for k, v in rel.items()
                                if k not in ("from_type", "from_key", "rel", "to_type", "to_key")},
                )
                if ok:
                    rel_count += 1
            except Exception:
                logger.debug("Failed to add relationship: %s", rel, exc_info=True)
        counts["relationships"] = rel_count

        return counts

    # ── public API ────────────────────────────────────────────────────────

    @observe()
    async def ingest(
        self,
        raw_data: str,
        source: str,
        source_category: str,
    ) -> dict[str, Any]:
        """Run the full ingestion pipeline on raw text."""
        start = time.monotonic()

        if not raw_data or not raw_data.strip():
            return {
                "nutrients_extracted": {"protein": 0, "carbs": 0, "waste": 0},
                "chunks_created": 0,
                "entities_found": {"companies": 0, "people": 0, "machines": 0},
                "processing_time": 0.0,
            }

        # STOMACH
        nutrients = await self._extract_nutrients(raw_data)

        nutrient_counts = {
            k: len(v) for k, v in nutrients.items()
        }

        # DUODENUM — rewrite raw facts as searchable statements
        nutrients = await self._summarize_nutrients(nutrients)

        # SMALL INTESTINE
        chunks_created = await self._absorb(nutrients, source, source_category)

        # LIVER
        protein_text = "\n".join(nutrients.get("protein", []))
        entities_found = await self._extract_entities(protein_text)

        elapsed = time.monotonic() - start
        logger.info(
            "DIGEST complete: source=%s nutrients=%s chunks=%d entities=%s time=%.2fs",
            source, nutrient_counts, chunks_created, entities_found, elapsed,
        )

        return {
            "nutrients_extracted": nutrient_counts,
            "chunks_created": chunks_created,
            "entities_found": entities_found,
            "processing_time": round(elapsed, 3),
        }

    @observe()
    async def ingest_email(self, email: Email) -> dict[str, Any]:
        """Ingest an email through the full pipeline with extra metadata extraction."""
        result = await self.ingest(
            raw_data=email.body,
            source=email.from_address,
            source_category="email",
        )

        email_metadata = await self._extract_email_metadata(email.body)
        result["email_metadata"] = email_metadata
        result["email_id"] = email.id
        result["subject"] = email.subject
        return result

    async def _extract_email_metadata(self, body: str) -> dict[str, Any]:
        """Extract email-specific metadata (sender info, mentions, dates)."""
        result = await self._llm.generate_structured(
            _EMAIL_META_SYSTEM_PROMPT, body[:12_000], EmailMetadata,
            name="digestive.email_meta",
        )
        return result.model_dump()

    async def batch_ingest(self, items: list[dict[str, str]]) -> dict[str, Any]:
        """Process multiple items, logging progress and handling errors."""
        total_processed = 0
        total_failed = 0
        total_chunks = 0
        total_entities: dict[str, int] = {"companies": 0, "people": 0, "machines": 0, "relationships": 0}
        errors: list[str] = []

        for i, item in enumerate(items):
            try:
                result = await self.ingest(
                    raw_data=item.get("raw_data", ""),
                    source=item.get("source", "unknown"),
                    source_category=item.get("source_category", "uncategorised"),
                )
                total_processed += 1
                total_chunks += result["chunks_created"]
                for key in total_entities:
                    total_entities[key] += result["entities_found"].get(key, 0)
            except Exception:
                total_failed += 1
                errors.append(item.get("source", f"item_{i}"))
                logger.exception("Batch ingest failed for item %d", i)

            if (i + 1) % 10 == 0:
                logger.info("Batch progress: %d/%d processed", i + 1, len(items))

        return {
            "total_processed": total_processed,
            "total_failed": total_failed,
            "total_chunks": total_chunks,
            "total_entities": total_entities,
            "errors": errors,
        }
