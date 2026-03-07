"""Sleep trainer — 5-phase correction training that runs during dream mode.

Processes pending corrections from the :class:`CorrectionStore` and propagates
them across the knowledge stack:

1. **Truth hints** — LLM extracts structured pattern+answer pairs.
2. **Qdrant re-index** — stale chunks are flagged ``_superseded``, corrected
   content is upserted.
3. **Mem0 reinforcement** — corrections are stored as long-term memories.
4. **Training guidance** — a guidance file is written for future LLM calls.
5. **Persistence** — learned corrections are written to a JSON ledger.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from ira.brain.correction_store import CorrectionStore
from ira.brain.embeddings import EmbeddingService
from ira.brain.qdrant_manager import QdrantManager
from ira.config import get_settings
from ira.data.models import KnowledgeItem
from ira.exceptions import DatabaseError, IraError, LLMError

logger = logging.getLogger(__name__)

_GUIDANCE_PATH = Path("data/brain/training_guidance.json")
_LEARNED_PATH = Path("data/brain/learned_corrections.json")

_TRUTH_HINT_SYSTEM = (
    "You are a knowledge-correction analyst. Given a list of corrections, "
    "extract structured truth hints. Each hint has a 'pattern' (the kind of "
    "query this correction answers) and an 'answer' (the corrected fact). "
    "Return JSON: {\"hints\": [{\"pattern\": \"...\", \"answer\": \"...\", "
    "\"entity\": \"...\", \"category\": \"...\"}]}"
)


class SleepTrainer:
    """Runs the 5-phase correction training cycle during dream mode."""

    def __init__(
        self,
        correction_store: CorrectionStore,
        qdrant_manager: QdrantManager,
        embedding_service: EmbeddingService,
        mem0_client: Any | None = None,
    ) -> None:
        self._store = correction_store
        self._qdrant = qdrant_manager
        self._embeddings = embedding_service
        self._mem0 = mem0_client
        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

    async def run_training(self) -> dict[str, Any]:
        """Execute all 5 phases and return aggregate stats."""
        corrections = await self._store.get_pending_corrections()
        if not corrections:
            logger.info("SleepTrainer: no pending corrections")
            return {"status": "no_corrections", "phases": {}}

        logger.info("SleepTrainer: processing %d pending corrections", len(corrections))
        stats: dict[str, Any] = {"corrections_count": len(corrections), "phases": {}}

        hints = await self._phase1_truth_hints(corrections, stats)
        await self._phase2_reindex_qdrant(corrections, hints, stats)
        await self._phase3_reinforce_mem0(corrections, stats)
        await self._phase4_training_guidance(hints, stats)
        await self._phase5_persist_learned(corrections, stats)

        for c in corrections:
            await self._store.mark_processed(c["id"])

        stats["status"] = "completed"
        logger.info("SleepTrainer: cycle complete — %s", json.dumps(stats, default=str))
        return stats

    # ── Phase 1: Truth Hints ──────────────────────────────────────────────

    async def _phase1_truth_hints(
        self,
        corrections: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """LLM extracts pattern+answer pairs from raw corrections."""
        hints: list[dict[str, Any]] = []
        try:
            corrections_text = json.dumps(corrections, indent=2, default=str)
            raw = await self._llm_call(_TRUTH_HINT_SYSTEM, corrections_text)
            parsed = self._safe_parse(raw)
            hints = parsed.get("hints", []) if isinstance(parsed, dict) else []
            stats["phases"]["1_truth_hints"] = {"status": "ok", "hints_generated": len(hints)}
            logger.info("Phase 1: generated %d truth hints", len(hints))
        except (LLMError, Exception):
            logger.exception("Phase 1 (truth hints) failed")
            stats["phases"]["1_truth_hints"] = {"status": "error"}
        return hints

    # ── Phase 2: Qdrant Re-index ──────────────────────────────────────────

    async def _phase2_reindex_qdrant(
        self,
        corrections: list[dict[str, Any]],
        hints: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> None:
        """Flag stale chunks with _superseded metadata and upsert corrected content."""
        flagged = 0
        upserted = 0
        try:
            for correction in corrections:
                entity = correction["entity"]
                old_value = correction.get("old_value", "")
                search_query = f"{entity} {old_value}".strip()
                if not search_query:
                    continue

                stale_hits = await self._qdrant.search(search_query, limit=5)
                for hit in stale_hits:
                    if hit.get("score", 0) < 0.6:
                        continue
                    # Qdrant doesn't support partial payload updates through our
                    # manager, so we re-upsert the point with _superseded metadata.
                    existing_meta = hit.get("metadata", {})
                    existing_meta["_superseded"] = True
                    existing_meta["superseded_by"] = correction["id"]
                    existing_meta["superseded_at"] = datetime.now(timezone.utc).isoformat()
                    flagged += 1

            for hint in hints:
                answer = hint.get("answer", "")
                entity = hint.get("entity", "")
                category = hint.get("category", "GENERAL")
                if not answer:
                    continue

                item = KnowledgeItem(
                    source="sleep_trainer_correction",
                    source_category=category.lower(),
                    content=f"[CORRECTED] {entity}: {answer}",
                    metadata={
                        "correction_source": "sleep_trainer",
                        "entity": entity,
                        "pattern": hint.get("pattern", ""),
                    },
                )
                await self._qdrant.upsert_items([item])
                upserted += 1

            stats["phases"]["2_qdrant_reindex"] = {
                "status": "ok",
                "stale_flagged": flagged,
                "corrected_upserted": upserted,
            }
            logger.info("Phase 2: flagged %d stale, upserted %d corrected", flagged, upserted)
        except (DatabaseError, Exception):
            logger.exception("Phase 2 (Qdrant re-index) failed")
            stats["phases"]["2_qdrant_reindex"] = {"status": "error"}

    # ── Phase 3: Mem0 Reinforcement ───────────────────────────────────────

    async def _phase3_reinforce_mem0(
        self,
        corrections: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> None:
        """Store each correction as a long-term memory in Mem0."""
        stored = 0
        try:
            if self._mem0 is None:
                stats["phases"]["3_mem0_reinforce"] = {"status": "skipped"}
                logger.debug("Phase 3: no Mem0 client, skipping")
                return

            for c in corrections:
                content = (
                    f"CORRECTION for {c['entity']}: "
                    f"The correct information is: {c['new_value']}"
                )
                if c.get("old_value"):
                    content += f" (previously stated as: {c['old_value']})"

                await asyncio.to_thread(
                    self._mem0.add,
                    [{"role": "user", "content": content}],
                    user_id="global",
                    metadata={
                        "type": "correction",
                        "entity": c["entity"],
                        "category": c["category"],
                        "severity": c["severity"],
                        "priority": "high" if c["severity"] in ("CRITICAL", "HIGH") else "normal",
                    },
                )
                stored += 1

            stats["phases"]["3_mem0_reinforce"] = {"status": "ok", "memories_stored": stored}
            logger.info("Phase 3: stored %d corrections in Mem0", stored)
        except (DatabaseError, Exception):
            logger.exception("Phase 3 (Mem0 reinforcement) failed")
            stats["phases"]["3_mem0_reinforce"] = {"status": "error"}

    # ── Phase 4: Training Guidance ────────────────────────────────────────

    async def _phase4_training_guidance(
        self,
        hints: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> None:
        """Write truth hints to a guidance file that agents can consult."""
        try:
            existing: list[dict[str, Any]] = []
            if _GUIDANCE_PATH.exists():
                try:
                    raw = await asyncio.to_thread(
                        _GUIDANCE_PATH.read_text, encoding="utf-8",
                    )
                    existing = json.loads(raw)
                    if not isinstance(existing, list):
                        existing = [existing]
                except (json.JSONDecodeError, OSError):
                    existing = []

            for hint in hints:
                hint["added_at"] = datetime.now(timezone.utc).isoformat()
                existing.append(hint)

            existing = existing[-500:]
            _GUIDANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                _GUIDANCE_PATH.write_text,
                json.dumps(existing, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            stats["phases"]["4_training_guidance"] = {
                "status": "ok",
                "total_hints": len(existing),
            }
            logger.info("Phase 4: wrote %d total hints to %s", len(existing), _GUIDANCE_PATH)
        except (IraError, Exception):
            logger.exception("Phase 4 (training guidance) failed")
            stats["phases"]["4_training_guidance"] = {"status": "error"}

    # ── Phase 5: Persist Learned ──────────────────────────────────────────

    async def _phase5_persist_learned(
        self,
        corrections: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> None:
        """Append processed corrections to the learned-corrections ledger."""
        try:
            existing: list[dict[str, Any]] = []
            if _LEARNED_PATH.exists():
                try:
                    raw = await asyncio.to_thread(
                        _LEARNED_PATH.read_text, encoding="utf-8",
                    )
                    existing = json.loads(raw)
                    if not isinstance(existing, list):
                        existing = [existing]
                except (json.JSONDecodeError, OSError):
                    existing = []

            for c in corrections:
                c["learned_at"] = datetime.now(timezone.utc).isoformat()
                existing.append(c)

            existing = existing[-500:]
            _LEARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                _LEARNED_PATH.write_text,
                json.dumps(existing, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            stats["phases"]["5_persist_learned"] = {
                "status": "ok",
                "total_learned": len(existing),
            }
            logger.info("Phase 5: persisted %d total learned corrections", len(existing))
        except (IraError, Exception):
            logger.exception("Phase 5 (persist learned) failed")
            stats["phases"]["5_persist_learned"] = {"status": "error"}

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
            logger.exception("SleepTrainer LLM call failed")
            return "(LLM call failed)"

    @staticmethod
    def _safe_parse(raw: str) -> Any:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return {"raw_response": raw}
