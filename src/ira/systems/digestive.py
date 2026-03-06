"""Digestive system — data ingestion with nutrient extraction.

Orchestrates the full data ingestion pipeline using a biological metaphor:
MOUTH (receive) → STOMACH (LLM nutrient extraction) → SMALL INTESTINE
(chunk + embed + upsert) → LIVER (entity extraction into knowledge graph).

The key insight: not all data is equal.  The nutrient extraction step ensures
only high-value information is stored, keeping the knowledge base clean.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from ira.brain.document_ingestor import DocumentIngestor, chunk_text
from ira.brain.embeddings import EmbeddingService
from ira.brain.knowledge_graph import KnowledgeGraph
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings
from ira.data.models import Email, KnowledgeItem
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_NUTRIENT_SYSTEM_PROMPT = load_prompt("digestive_nutrient")

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

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

    # ── STOMACH: nutrient extraction ──────────────────────────────────────

    async def _extract_nutrients(self, raw_data: str) -> dict[str, list[str]]:
        """Use an LLM to classify text into protein / carbs / waste."""
        empty: dict[str, list[str]] = {"protein": [], "carbs": [], "waste": []}

        if not self._openai_key:
            logger.warning("No OpenAI API key — skipping nutrient extraction")
            return {"protein": [raw_data], "carbs": [], "waste": []}

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _NUTRIENT_SYSTEM_PROMPT},
                {"role": "user", "content": raw_data[:12_000]},
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
                content = resp.json()["choices"][0]["message"]["content"]
                result = json.loads(content)
                for key in ("protein", "carbs", "waste"):
                    if key not in result or not isinstance(result[key], list):
                        result[key] = []
                return result
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            logger.exception("Nutrient extraction failed")
            return empty

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

        return await self._qdrant.upsert_items(items)

    # ── LIVER: entity extraction ──────────────────────────────────────────

    async def _extract_entities(self, protein_text: str) -> dict[str, int]:
        """Extract entities from protein content and add to the knowledge graph."""
        if not protein_text.strip():
            return {"companies": 0, "people": 0, "machines": 0}

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

        return counts

    # ── public API ────────────────────────────────────────────────────────

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
        empty: dict[str, Any] = {
            "sender_info": {},
            "company_mentions": [],
            "machine_mentions": [],
            "pricing_mentions": [],
            "dates_deadlines": [],
        }

        if not self._openai_key:
            return empty

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _EMAIL_META_SYSTEM_PROMPT},
                {"role": "user", "content": body[:12_000]},
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
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            logger.exception("Email metadata extraction failed")
            return empty

    async def batch_ingest(self, items: list[dict[str, str]]) -> dict[str, Any]:
        """Process multiple items, logging progress and handling errors."""
        total_processed = 0
        total_failed = 0
        total_chunks = 0
        total_entities: dict[str, int] = {"companies": 0, "people": 0, "machines": 0}
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
