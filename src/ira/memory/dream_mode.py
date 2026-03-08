"""Dream mode — nightly memory consolidation, gap detection, and creative synthesis.

Implements an 11-stage dream cycle:
  0.   Deferred Ingestion — ingest files accessed via Alexandros fallback.
  0.5  Sleep Training — run Nemesis corrections on pending items.
  1.   Memory Ingestion — pull recent interactions from the CRM.
  2.   Episodic Consolidation — group related interactions into narrative episodes.
  3a.  Cross-episode Insights — LLM-driven pattern/contradiction detection.
  3b.  Gap Detection — identify knowledge gaps from metacognition table.
  3c.  Creative Synthesis — connect gaps and episodes for novel insights.
  3d.  Campaign Reflection — review campaign myokines for marketing insights.
  3e.  Active Gap Resolution — research and resolve top priority gaps.
  4.   Procedural Learning — turn repeatable successful patterns into procedures.
  5.   Memory Pruning — archive or summarise older, less-relevant memories.
  6.   Price Conflict Check — scan pricing data for inconsistencies.
  7.   Conversation Quality Review — review retrieval quality via co-access matrix.
  8.   Graph Consolidation — tune knowledge graph relationships.
  9.   Follow-up Automation — detect stale quotes for follow-up.
  10.  Morning Summary — log dream cycle results.

Each cycle is logged to ``data/dream_log.json`` for auditability.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
from langfuse.decorators import observe

from ira.config import get_settings
from ira.data.models import DreamReport
from ira.exceptions import ConfigurationError, DatabaseError, IngestionError, IraError, LLMError
from ira.memory.conversation import ConversationMemory
from ira.memory.episodic import EpisodicMemory
from ira.memory.long_term import LongTermMemory
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import (
    DreamCampaignInsights,
    DreamCreative,
    DreamGaps,
    DreamInsight,
    DreamProcedures,
    DreamPrune,
)
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_DREAM_LOG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "dream_log.json"

_GAP_SYSTEM_PROMPT = load_prompt("dream_gap_analysis")

_CREATIVE_SYSTEM_PROMPT = load_prompt("dream_creative")

_CAMPAIGN_SYSTEM_PROMPT = load_prompt("dream_campaign")

_INSIGHT_SYSTEM_PROMPT = load_prompt("dream_insight")

_PROCEDURAL_SYSTEM_PROMPT = load_prompt("dream_procedural")

_PRUNE_SYSTEM_PROMPT = load_prompt("dream_prune")


class DreamMode:
    def __init__(
        self,
        long_term: LongTermMemory,
        episodic: EpisodicMemory,
        conversation: ConversationMemory,
        musculoskeletal: Any | None = None,
        retriever: Any | None = None,
        crm: Any | None = None,
        procedural_memory: Any | None = None,
        data_event_bus: Any | None = None,
        db_path: str = "data/conversations.db",
        dream_log_path: str | Path | None = None,
    ) -> None:
        self._long_term = long_term
        self._episodic = episodic
        self._conversation = conversation
        self._musculoskeletal = musculoskeletal
        self._retriever = retriever
        self._crm = crm
        self._procedural = procedural_memory
        self._event_bus = data_event_bus
        self._db_path = db_path
        self._llm = get_llm_client()
        self._db: aiosqlite.Connection | None = None
        self._dream_log_path = Path(dream_log_path) if dream_log_path else _DREAM_LOG_PATH

    def configure(self, **kwargs: Any) -> None:
        """Late-bind optional dependencies after construction."""
        if "procedural_memory" in kwargs:
            self._procedural = kwargs["procedural_memory"]
        if "crm" in kwargs:
            self._crm = kwargs["crm"]
        if "musculoskeletal" in kwargs:
            self._musculoskeletal = kwargs["musculoskeletal"]
        if "retriever" in kwargs:
            self._retriever = kwargs["retriever"]

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS dream_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_date TEXT NOT NULL UNIQUE,
                memories_consolidated INTEGER NOT NULL,
                gaps_identified TEXT NOT NULL,
                creative_connections TEXT NOT NULL,
                campaign_insights TEXT NOT NULL,
                stage_results TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        try:
            await self._db.execute(
                "ALTER TABLE dream_reports ADD COLUMN stage_results TEXT NOT NULL DEFAULT '{}'"
            )
        except Exception:
            pass
        await self._db.commit()

    # ── public API ────────────────────────────────────────────────────────

    @observe()
    async def run_dream_cycle(self) -> DreamReport:
        """Execute the full 11-stage dream cycle and return a report."""
        logger.info("DREAM CYCLE starting")
        stage_log: dict[str, Any] = {"cycle_date": date.today().isoformat(), "stages": {}}

        # Stage 0 — Deferred Ingestion (files accessed via Alexandros fallback)
        await self._stage0_deferred_ingestion(stage_log)

        # Stage 0.5 — Sleep Training (Nemesis corrections)
        await self._stage0_5_sleep_training(stage_log)

        # Stage 1 — Memory Ingestion (CRM interactions)
        interactions = await self._stage1_memory_ingestion(stage_log)

        # Stage 2 — Episodic Consolidation
        episodes, memories_consolidated = await self._stage2_episodic_consolidation(
            interactions, stage_log
        )

        # Stage 3 — Insight Generation
        insights, gaps, connections, campaign_insights = (
            await self._stage3_insight_generation(episodes, stage_log)
        )

        # Stage 3e — Active Gap Resolution
        await self._stage3e_gap_resolution(gaps, stage_log)

        # Stage 4 — Procedural Learning
        await self._stage4_procedural_learning(insights, episodes, stage_log)

        # Stage 5 — Memory Pruning
        await self._stage5_memory_pruning(stage_log)

        # Stage 6 — Price Conflict Check
        price_conflicts = await self._stage6_price_conflict_check(stage_log)

        # Stages 7 & 8 — Quality Review + Graph Consolidation (shared graph)
        await self._stage7_and_8_graph(stage_log)

        # Stage 9 — Follow-up Automation
        await self._stage9_follow_up_automation(stage_log)

        # Stage 10 — Morning Summary
        await self._stage10_morning_summary(stage_log, memories_consolidated, gaps, connections, price_conflicts)

        stage_results = {
            name: info.get("status", "unknown")
            for name, info in stage_log.get("stages", {}).items()
        }

        report = DreamReport(
            cycle_date=date.today(),
            memories_consolidated=memories_consolidated,
            gaps_identified=[g.get("description", "") for g in gaps],
            creative_connections=[c.get("insight", "") for c in connections],
            campaign_insights=campaign_insights,
            stage_results=stage_results,
        )

        await self._persist_report(report)
        self._write_dream_log(stage_log, report)

        logger.info(
            "DREAM CYCLE complete: consolidated=%d gaps=%d connections=%d insights=%d",
            memories_consolidated,
            len(gaps),
            len(connections),
            len(campaign_insights),
        )
        return report

    # ── Stage 0: Deferred Ingestion ──────────────────────────────────────

    async def _stage0_deferred_ingestion(self, stage_log: dict[str, Any]) -> None:
        """Ingest files that were accessed via Alexandros fallback since the last dream."""
        try:
            from ira.brain.imports_fallback_retriever import (
                load_deferred_queue,
                mark_deferred_ingested,
            )

            queue = await load_deferred_queue()
            if not queue:
                logger.debug("Stage 0: no deferred ingestion items")
                stage_log["stages"]["0_deferred_ingestion"] = {"status": "ok", "files_ingested": 0}
                return

            ingested = 0
            if self._retriever is not None:
                from ira.brain.document_ingestor import DocumentIngestor
                from ira.brain.embeddings import EmbeddingService
                from ira.brain.qdrant_manager import QdrantManager

                embedding = EmbeddingService()
                qdrant = QdrantManager(embedding_service=embedding)
                await qdrant.ensure_collection()
                ingestor = DocumentIngestor(qdrant)
                try:
                    for entry in queue:
                        filepath = entry.get("filepath", "")
                        if not filepath or not Path(filepath).exists():
                            continue
                        try:
                            file_info = {
                                "path": filepath,
                                "category": entry.get("doc_type", "uncategorised"),
                                "extension": Path(filepath).suffix.lower(),
                                "size": Path(filepath).stat().st_size,
                            }
                            chunks = await ingestor.ingest_file(file_info, force=True)
                            if chunks > 0:
                                await mark_deferred_ingested(filepath)
                                ingested += 1
                                logger.info("Deferred ingestion: %s -> %d chunks", entry.get("filename", ""), chunks)
                        except (IngestionError, Exception):
                            logger.exception("Deferred ingestion failed for %s", filepath)
                finally:
                    ingestor.close()
                    await qdrant.close()

            stage_log["stages"]["0_deferred_ingestion"] = {"status": "ok", "files_ingested": ingested}
            logger.info("Stage 0: deferred ingestion complete — %d files", ingested)
        except ImportError:
            logger.debug("Stage 0: imports fallback retriever not available")
            stage_log["stages"]["0_deferred_ingestion"] = {"status": "skipped"}
        except (IngestionError, Exception):
            logger.exception("Dream Stage 0 (deferred ingestion) failed")
            stage_log["stages"]["0_deferred_ingestion"] = {"status": "error"}

    # ── Stage 1: Memory Ingestion ─────────────────────────────────────────

    async def _stage1_memory_ingestion(
        self, stage_log: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Pull recent interactions from the CRM (last 24 h)."""
        interactions: list[dict[str, Any]] = []
        try:
            if self._crm is not None:
                raw = await self._crm.list_interactions()
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                for ix in raw:
                    d = ix.to_dict() if hasattr(ix, "to_dict") else ix
                    created = d.get("created_at", "")
                    if isinstance(created, str) and created:
                        try:
                            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            if dt < cutoff:
                                continue
                        except ValueError:
                            pass
                    interactions.append(d)
                logger.info("Stage 1: ingested %d recent CRM interactions", len(interactions))
            else:
                logger.debug("Stage 1: no CRM configured, skipping")

            stage_log["stages"]["1_memory_ingestion"] = {
                "status": "ok",
                "interactions_found": len(interactions),
            }
        except (DatabaseError, Exception):
            logger.exception("Dream Stage 1 (memory ingestion) failed")
            stage_log["stages"]["1_memory_ingestion"] = {"status": "error"}

        return interactions

    # ── Stage 2: Episodic Consolidation ───────────────────────────────────

    async def _stage2_episodic_consolidation(
        self,
        interactions: list[dict[str, Any]],
        stage_log: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """Group related interactions into narrative episodes."""
        episodes: list[dict[str, Any]] = []
        memories_consolidated = 0

        try:
            # Group interactions by contact_id to form per-contact episodes
            by_contact: dict[str, list[dict[str, Any]]] = {}
            for ix in interactions:
                cid = ix.get("contact_id", "unknown")
                by_contact.setdefault(cid, []).append(ix)

            for contact_id, contact_interactions in by_contact.items():
                if len(contact_interactions) < 1:
                    continue
                transcript = []
                for ix in contact_interactions:
                    direction = ix.get("direction", "OUTBOUND")
                    role = "assistant" if direction == "OUTBOUND" else "user"
                    content = ix.get("content") or ix.get("subject") or "(no content)"
                    transcript.append({"role": role, "content": content})

                episode = await self._episodic.consolidate_episode(transcript, contact_id)
                episodes.append(episode)
                memories_consolidated += 1

            # Also consolidate conversation-memory sessions (original behaviour)
            try:
                if self._conversation._db is not None:
                    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                    cursor = await self._conversation._db.execute(
                        "SELECT DISTINCT user_id, channel FROM conversations WHERE last_message_at >= ?",
                        (cutoff,),
                    )
                    rows = await cursor.fetchall()
                    await cursor.close()
                    for user_id, channel in rows:
                        history = await self._conversation.get_history(user_id, channel)
                        if len(history) >= 2:
                            ep = await self._episodic.consolidate_episode(history, user_id)
                            episodes.append(ep)
                            memories_consolidated += 1
            except (LLMError, Exception):
                logger.exception("Stage 2: conversation-memory consolidation failed")

            logger.info(
                "Stage 2: consolidated %d episodes from %d contact groups + conversations",
                memories_consolidated,
                len(by_contact),
            )
            stage_log["stages"]["2_episodic_consolidation"] = {
                "status": "ok",
                "episodes_created": len(episodes),
                "memories_consolidated": memories_consolidated,
            }
        except (IraError, Exception):
            logger.exception("Dream Stage 2 (episodic consolidation) failed")
            stage_log["stages"]["2_episodic_consolidation"] = {"status": "error"}

        return episodes, memories_consolidated

    # ── Stage 3: Insight Generation ───────────────────────────────────────

    async def _stage3_insight_generation(
        self,
        episodes: list[dict[str, Any]],
        stage_log: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict], list[dict], list[str]]:
        """Use LLM to find patterns, contradictions, and insights across episodes."""
        insights: dict[str, Any] = {}
        gaps: list[dict[str, Any]] = []
        connections: list[dict[str, Any]] = []
        campaign_insights: list[str] = []

        # 3a — Cross-episode insight analysis
        try:
            if episodes:
                episode_text = "\n\n".join(
                    f"Episode ({e.get('user_id', 'unknown')}): {e.get('narrative', '')}"
                    for e in episodes
                )
                result = await self._llm.generate_structured(
                    _INSIGHT_SYSTEM_PROMPT, episode_text, DreamInsight,
                    temperature=0.2, name="dream.insight",
                )
                insights = result.model_dump()
            stage_log.setdefault("stages", {})["3a_cross_episode_insights"] = {
                "status": "ok",
                "patterns": len(insights.get("patterns", [])),
                "contradictions": len(insights.get("contradictions", [])),
                "recommendations": len(insights.get("recommendations", [])),
            }
        except (LLMError, Exception):
            logger.exception("Dream Stage 3a (cross-episode insights) failed")
            stage_log.setdefault("stages", {})["3a_cross_episode_insights"] = {"status": "error"}

        # 3b — Knowledge gap detection (from metacognition table)
        try:
            if self._db is not None:
                await self._db.execute(
                    """CREATE TABLE IF NOT EXISTS knowledge_gaps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL, state TEXT NOT NULL,
                        gaps TEXT NOT NULL, created_at TEXT NOT NULL
                    )"""
                )
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                cursor = await self._db.execute(
                    "SELECT query, gaps FROM knowledge_gaps WHERE created_at >= ?",
                    (cutoff,),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                if rows:
                    gap_text = "\n".join(f"Query: {r[0]}\nGaps: {r[1]}" for r in rows)
                    result = await self._llm.generate_structured(
                        _GAP_SYSTEM_PROMPT, gap_text, DreamGaps, name="dream.gaps",
                    )
                    gaps = [g.model_dump() for g in result.gaps]
            stage_log["stages"]["3b_gap_detection"] = {
                "status": "ok",
                "gaps_found": len(gaps),
            }
        except (DatabaseError, Exception):
            logger.exception("Dream Stage 3b (gap detection) failed")
            stage_log["stages"]["3b_gap_detection"] = {"status": "error"}

        # 3c — Creative synthesis
        try:
            top_gaps = gaps[:5]
            recent_episodes: list[dict[str, Any]] = []
            ep_db = getattr(self._episodic, "_db", None) or self._db
            if ep_db is not None:
                try:
                    cursor = await ep_db.execute(
                        "SELECT narrative, created_at FROM episodes ORDER BY created_at DESC LIMIT 5"
                    )
                    ep_rows = await cursor.fetchall()
                    await cursor.close()
                    recent_episodes = [{"narrative": r[0], "created_at": r[1]} for r in ep_rows]
                except Exception:
                    logger.debug("Stage 3c: episodes table not available")

            context_parts = []
            if top_gaps:
                context_parts.append("Knowledge gaps:\n" + json.dumps(top_gaps, indent=2))
            if recent_episodes:
                context_parts.append(
                    "Recent episodes:\n"
                    + "\n".join(f"[{e['created_at']}] {e['narrative']}" for e in recent_episodes)
                )
            context = "\n\n".join(context_parts) if context_parts else "No gaps or episodes."
            result = await self._llm.generate_structured(
                _CREATIVE_SYSTEM_PROMPT, context, DreamCreative,
                temperature=0.3, name="dream.creative",
            )
            connections = [c.model_dump() for c in result.connections]
            stage_log["stages"]["3c_creative_synthesis"] = {
                "status": "ok",
                "connections_found": len(connections),
            }
        except (LLMError, Exception):
            logger.exception("Dream Stage 3c (creative synthesis) failed")
            stage_log["stages"]["3c_creative_synthesis"] = {"status": "error"}

        # 3d — Campaign reflection (via musculoskeletal myokines)
        try:
            if self._musculoskeletal is not None:
                myokines = await self._musculoskeletal.extract_myokines(period_days=7)
                myokines_text = json.dumps(myokines, indent=2)
                result = await self._llm.generate_structured(
                    _CAMPAIGN_SYSTEM_PROMPT, myokines_text, DreamCampaignInsights,
                    name="dream.campaign",
                )
                campaign_insights = result.insights
            stage_log["stages"]["3d_campaign_reflection"] = {
                "status": "ok",
                "campaign_insights": len(campaign_insights),
            }
        except (LLMError, Exception):
            logger.exception("Dream Stage 3d (campaign reflection) failed")
            stage_log["stages"]["3d_campaign_reflection"] = {"status": "error"}

        return insights, gaps, connections, campaign_insights

    # ── Stage 3e: Active Gap Resolution ───────────────────────────────────

    async def _stage3e_gap_resolution(
        self,
        gaps: list[dict[str, Any]],
        stage_log: dict[str, Any],
    ) -> None:
        """Research and resolve the highest-priority knowledge gaps."""
        resolved = 0
        try:
            from ira.brain.gap_resolver import GapResolver
            from ira.memory.metacognition import Metacognition

            metacognition: Metacognition | None = None
            try:
                metacognition = Metacognition(db_path=self._db_path)
                await metacognition.initialize()
            except (IraError, Exception):
                logger.debug("Metacognition not available for gap resolution")

            resolver = GapResolver(
                long_term_memory=self._long_term,
                metacognition=metacognition,
            )

            unresolved = await metacognition.get_unresolved_gaps(limit=20) if metacognition else []
            if not unresolved and gaps:
                unresolved = gaps

            prioritized = resolver.prioritize_gaps(unresolved)
            top_gaps = prioritized[:3]

            for gap in top_gaps:
                try:
                    result = await resolver.resolve_gap(gap)
                    if result:
                        resolved += 1
                except (IraError, Exception):
                    logger.debug("Gap resolution failed for: %s", gap.get("query", "?"), exc_info=True)

            if metacognition is not None:
                await metacognition.close()

            stage_log["stages"]["3e_gap_resolution"] = {
                "status": "ok",
                "gaps_attempted": len(top_gaps),
                "gaps_resolved": resolved,
            }
            logger.info("Stage 3e: resolved %d/%d gaps", resolved, len(top_gaps))
        except ImportError:
            stage_log["stages"]["3e_gap_resolution"] = {"status": "skipped"}
        except (IraError, Exception):
            logger.exception("Dream Stage 3e (gap resolution) failed")
            stage_log["stages"]["3e_gap_resolution"] = {"status": "error"}

    # ── Stage 4: Procedural Learning ──────────────────────────────────────

    async def _stage4_procedural_learning(
        self,
        insights: dict[str, Any],
        episodes: list[dict[str, Any]],
        stage_log: dict[str, Any],
    ) -> None:
        """Turn high-confidence insights into repeatable procedures."""
        procedures_created = 0
        try:
            if self._procedural is None:
                logger.debug("Stage 4: no ProceduralMemory configured, skipping")
                stage_log["stages"]["4_procedural_learning"] = {"status": "skipped"}
                return

            recommendations = insights.get("recommendations", [])
            high_confidence = [
                r for r in recommendations
                if (r.get("priority") if isinstance(r, dict) else getattr(r, "priority", "")) == "HIGH"
            ]

            if not high_confidence and not episodes:
                stage_log["stages"]["4_procedural_learning"] = {
                    "status": "ok",
                    "procedures_created": 0,
                }
                return

            context_parts = []
            if high_confidence:
                serializable = [
                    r.model_dump() if hasattr(r, "model_dump") else r
                    for r in high_confidence
                ]
                context_parts.append(
                    "High-priority recommendations:\n" + json.dumps(serializable, indent=2)
                )
            if episodes:
                episode_summaries = [
                    {"user_id": e.get("user_id", ""), "narrative": e.get("narrative", "")}
                    for e in episodes[:10]
                ]
                context_parts.append(
                    "Recent episodes:\n" + json.dumps(episode_summaries, indent=2)
                )

            context = "\n\n".join(context_parts)
            result = await self._llm.generate_structured(
                _PROCEDURAL_SYSTEM_PROMPT, context, DreamProcedures,
                name="dream.procedural",
            )

            for proc in result.procedures:
                trigger = proc.trigger
                steps = proc.steps
                if trigger and steps:
                    await self._procedural.learn_procedure(trigger, steps)
                    procedures_created += 1

            logger.info("Stage 4: created %d new procedures", procedures_created)
            stage_log["stages"]["4_procedural_learning"] = {
                "status": "ok",
                "procedures_created": procedures_created,
            }
        except (IraError, Exception):
            logger.exception("Dream Stage 4 (procedural learning) failed")
            stage_log["stages"]["4_procedural_learning"] = {"status": "error"}

    # ── Stage 5: Memory Pruning ───────────────────────────────────────────

    async def _stage5_memory_pruning(self, stage_log: dict[str, Any]) -> None:
        """Archive or summarise older, less-relevant memories."""
        archived = 0
        summarised = 0
        try:
            if self._db is None:
                stage_log["stages"]["5_memory_pruning"] = {"status": "skipped"}
                return

            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            cursor = await self._db.execute(
                "SELECT id, narrative, key_topics, created_at FROM episodes WHERE created_at < ? ORDER BY created_at ASC LIMIT 50",
                (cutoff,),
            )
            old_episodes = await cursor.fetchall()
            await cursor.close()

            if not old_episodes:
                logger.debug("Stage 5: no old episodes to prune")
                stage_log["stages"]["5_memory_pruning"] = {
                    "status": "ok",
                    "archived": 0,
                    "summarised": 0,
                }
                return

            episodes_text = json.dumps(
                [{"id": r[0], "narrative": r[1], "topics": r[2], "date": r[3]} for r in old_episodes],
                indent=2,
            )
            result = await self._llm.generate_structured(
                _PRUNE_SYSTEM_PROMPT, episodes_text, DreamPrune, name="dream.prune",
            )
            decisions = result.model_dump()

            archive_ids = decisions.get("archive", [])
            if archive_ids:
                placeholders = ",".join("?" for _ in archive_ids)
                await self._db.execute(
                    f"DELETE FROM episodes WHERE id IN ({placeholders})",
                    archive_ids,
                )
                archived = len(archive_ids)

            for group in decisions.get("summarise", []):
                ids = group.get("ids", [])
                summary = group.get("summary", "")
                if ids and summary:
                    placeholders = ",".join("?" for _ in ids)
                    await self._db.execute(
                        f"UPDATE episodes SET narrative = ? WHERE id IN ({placeholders})",
                        [summary, *ids],
                    )
                    summarised += len(ids)

            await self._db.commit()
            logger.info("Stage 5: archived %d, summarised %d episodes", archived, summarised)
            stage_log["stages"]["5_memory_pruning"] = {
                "status": "ok",
                "archived": archived,
                "summarised": summarised,
            }
        except (DatabaseError, Exception):
            logger.exception("Dream Stage 5 (memory pruning) failed")
            stage_log["stages"]["5_memory_pruning"] = {"status": "error"}

    # ── persistence helpers ───────────────────────────────────────────────

    async def _persist_report(self, report: DreamReport) -> None:
        """Write the dream report to the SQLite database."""
        if self._db is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT OR REPLACE INTO dream_reports
            (cycle_date, memories_consolidated, gaps_identified, creative_connections,
             campaign_insights, stage_results, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.cycle_date.isoformat(),
                report.memories_consolidated,
                json.dumps(report.gaps_identified),
                json.dumps(report.creative_connections),
                json.dumps(report.campaign_insights),
                json.dumps(report.stage_results),
                now,
            ),
        )
        await self._db.commit()

    # ── Stage 0.5: Sleep Training ────────────────────────────────────────

    async def _stage0_5_sleep_training(self, stage_log: dict[str, Any]) -> None:
        """Run Nemesis sleep trainer on pending corrections."""
        try:
            from ira.brain.correction_store import CorrectionStore
            from ira.brain.sleep_trainer import SleepTrainer
            from ira.brain.embeddings import EmbeddingService
            from ira.brain.qdrant_manager import QdrantManager

            store = CorrectionStore()
            await store.initialize()
            pending = await store.get_pending_corrections()
            if not pending:
                stage_log["stages"]["0_5_sleep_training"] = {"status": "ok", "corrections": 0}
                return

            embedding = EmbeddingService()
            qdrant = QdrantManager(embedding_service=embedding)

            mem0_client = None
            try:
                from ira.config import get_settings
                from mem0 import MemoryClient
                mem0_key = get_settings().memory.api_key.get_secret_value()
                if mem0_key:
                    mem0_client = MemoryClient(api_key=mem0_key)
            except (ConfigurationError, Exception):
                logger.debug("Mem0 not available for sleep training")

            trainer = SleepTrainer(
                correction_store=store,
                qdrant_manager=qdrant,
                embedding_service=embedding,
                mem0_client=mem0_client,
                data_event_bus=self._event_bus,
            )
            stats = await trainer.run_training()
            stage_log["stages"]["0_5_sleep_training"] = {"status": "ok", **stats}
            logger.info("Stage 0.5: sleep training complete — %s", stats)
            await qdrant.close()
        except ImportError:
            stage_log["stages"]["0_5_sleep_training"] = {"status": "skipped"}
        except (IraError, Exception):
            logger.exception("Dream Stage 0.5 (sleep training) failed")
            stage_log["stages"]["0_5_sleep_training"] = {"status": "error"}

    # ── Stage 6: Price Conflict Check ──────────────────────────────────

    async def _stage6_price_conflict_check(self, stage_log: dict[str, Any]) -> list[dict[str, Any]]:
        """Scan pricing data for inconsistencies."""
        conflicts: list[dict[str, Any]] = []
        try:
            from ira.brain.pricing_learner import PricingLearner
            learner = PricingLearner()
            learner._index = await learner._load_index()
            await learner.learn_from_quotes()
            conflicts = learner.detect_conflicts()
            if conflicts:
                await learner.send_conflict_alert(conflicts)
            stage_log["stages"]["6_price_conflict"] = {"status": "ok", "conflicts": len(conflicts)}
            logger.info("Stage 6: %d price conflicts found", len(conflicts))
        except ImportError:
            stage_log["stages"]["6_price_conflict"] = {"status": "skipped"}
        except (DatabaseError, Exception):
            logger.exception("Dream Stage 6 (price conflict) failed")
            stage_log["stages"]["6_price_conflict"] = {"status": "error"}
        return conflicts

    # ── Stages 7 & 8: Quality Review + Graph Consolidation (shared graph) ──

    async def _stage7_and_8_graph(self, stage_log: dict[str, Any]) -> None:
        """Quality review and graph consolidation using a single KnowledgeGraph."""
        try:
            from ira.brain.graph_consolidation import GraphConsolidation
            from ira.brain.knowledge_graph import KnowledgeGraph

            graph = KnowledgeGraph()
            gc = GraphConsolidation(knowledge_graph=graph)
            try:
                co_access = await gc.build_co_access_matrix()
                stage_log["stages"]["7_quality_review"] = {
                    "status": "ok",
                    "retrieval_pairs_analyzed": len(co_access),
                }
            except (DatabaseError, Exception):
                logger.exception("Dream Stage 7 (quality review) failed")
                stage_log["stages"]["7_quality_review"] = {"status": "error"}

            try:
                stats = await gc.run_consolidation()
                stats.pop("status", None)
                stage_log["stages"]["8_graph_consolidation"] = {"status": "ok", **stats}
                logger.info("Stage 8: graph consolidation — %s", stats)
            except (DatabaseError, Exception):
                logger.exception("Dream Stage 8 (graph consolidation) failed")
                stage_log["stages"]["8_graph_consolidation"] = {"status": "error"}

            await graph.close()
        except ImportError:
            stage_log["stages"]["7_quality_review"] = {"status": "skipped"}
            stage_log["stages"]["8_graph_consolidation"] = {"status": "skipped"}

    # ── Stage 9: Follow-up Automation ──────────────────────────────────

    async def _stage9_follow_up_automation(self, stage_log: dict[str, Any]) -> None:
        """Detect stale quotes and suggest follow-ups."""
        try:
            if self._crm is None:
                stage_log["stages"]["9_follow_up"] = {"status": "skipped", "reason": "no CRM"}
                return

            stale_deals = []
            deals = await self._crm.list_deals()
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            for deal in deals:
                updated = getattr(deal, "updated_at", None)
                if updated and isinstance(updated, str):
                    try:
                        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        if dt < cutoff:
                            stale_deals.append(deal)
                    except ValueError:
                        pass

            stage_log["stages"]["9_follow_up"] = {"status": "ok", "stale_deals": len(stale_deals)}
            logger.info("Stage 9: %d stale deals found for follow-up", len(stale_deals))
        except (DatabaseError, Exception):
            logger.exception("Dream Stage 9 (follow-up) failed")
            stage_log["stages"]["9_follow_up"] = {"status": "error"}

    # ── Stage 10: Morning Summary ──────────────────────────────────────

    async def _stage10_morning_summary(
        self,
        stage_log: dict[str, Any],
        memories_consolidated: int,
        gaps: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        price_conflicts: list[dict[str, Any]],
    ) -> None:
        """Log a morning summary of the dream cycle."""
        try:
            deferred = stage_log.get("stages", {}).get("0_deferred_ingestion", {}).get("files_ingested", 0)
            sleep_training = stage_log.get("stages", {}).get("0_5_sleep_training", {}).get("corrections", 0)

            failed_stages = [
                name for name, info in stage_log.get("stages", {}).items()
                if info.get("status") == "error"
            ]

            lines = [
                "Dream cycle complete.",
                f"- Memories consolidated: {memories_consolidated}",
                f"- Knowledge gaps found: {len(gaps)}",
                f"- Creative connections: {len(connections)}",
                f"- Price conflicts: {len(price_conflicts)}",
                f"- Files ingested (deferred): {deferred}",
                f"- Corrections trained: {sleep_training}",
            ]
            if failed_stages:
                lines.append(f"- FAILED stages: {', '.join(failed_stages)}")

            logger.info("Stage 10: %s", "\n".join(lines))
            stage_log["stages"]["10_morning_summary"] = {"status": "ok"}
        except (IraError, Exception):
            logger.exception("Dream Stage 10 (morning summary) failed")
            stage_log["stages"]["10_morning_summary"] = {"status": "error"}

    def _write_dream_log(self, stage_log: dict[str, Any], report: DreamReport) -> None:
        """Append the cycle results to dream_log.json."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_date": report.cycle_date.isoformat(),
            "memories_consolidated": report.memories_consolidated,
            "gaps_identified": report.gaps_identified,
            "creative_connections": report.creative_connections,
            "campaign_insights": report.campaign_insights,
            "stage_results": report.stage_results,
            "stages": stage_log.get("stages", {}),
        }

        existing: list[dict[str, Any]] = []
        if self._dream_log_path.exists():
            try:
                existing = json.loads(self._dream_log_path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = [existing]
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(entry)
        if len(existing) > 450:
            logger.warning(
                "Dream log has %d entries (cap=500). Oldest entries will be dropped.",
                len(existing),
            )
        existing = existing[-500:]
        try:
            self._dream_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._dream_log_path.write_text(
                json.dumps(existing, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write dream log to %s", self._dream_log_path)

    # ── query helpers ─────────────────────────────────────────────────────

    async def get_dream_reports(self, limit: int = 7) -> list[DreamReport]:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            SELECT cycle_date, memories_consolidated, gaps_identified,
                   creative_connections, campaign_insights, stage_results
            FROM dream_reports
            ORDER BY cycle_date DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        reports = []
        for r in rows:
            cycle_date_str = r[0]
            cycle_dt = date.fromisoformat(
                cycle_date_str.replace("Z", "").split("T")[0]
            )
            gaps_val = json.loads(r[2]) if isinstance(r[2], str) else r[2] or []
            creative = json.loads(r[3]) if isinstance(r[3], str) else r[3] or []
            campaign = json.loads(r[4]) if isinstance(r[4], str) else r[4] or []
            stages = json.loads(r[5]) if isinstance(r[5], str) and r[5] else {}
            reports.append(
                DreamReport(
                    cycle_date=cycle_dt,
                    memories_consolidated=r[1],
                    gaps_identified=gaps_val,
                    creative_connections=creative,
                    campaign_insights=campaign,
                    stage_results=stages,
                )
            )
        return reports

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> DreamMode:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


# ── Factory ───────────────────────────────────────────────────────────────


async def build_dream_mode(
    *,
    crm: Any | None = None,
    procedural_memory: Any | None = None,
    data_event_bus: Any | None = None,
    db_path: str = "data/conversations.db",
    dream_log_path: str | Path | None = None,
) -> DreamMode:
    """Build a fully-wired DreamMode instance with all optional dependencies.

    Shared by CLI, nap script, and anywhere else that needs a standalone
    DreamMode outside the server lifespan.  The server bootstrap wires
    dependencies itself and does not use this factory.
    """
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.systems.musculoskeletal import MusculoskeletalSystem

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)

    long_term = LongTermMemory()
    episodic = EpisodicMemory(long_term=long_term)
    await episodic.initialize()
    conversation = ConversationMemory()
    await conversation.initialize()
    musculoskeletal = MusculoskeletalSystem()
    try:
        await musculoskeletal.create_tables()
    except Exception:
        logger.debug("MusculoskeletalSystem table creation failed — continuing", exc_info=True)
        musculoskeletal = None  # type: ignore[assignment]

    if crm is None:
        try:
            from ira.data.crm import CRMDatabase
            crm = CRMDatabase()
            await crm.create_tables()
        except Exception:
            logger.debug("CRM not available for dream mode", exc_info=True)
            crm = None

    if procedural_memory is None:
        try:
            from ira.memory.procedural import ProceduralMemory
            procedural_memory = ProceduralMemory()
            await procedural_memory.initialize()
        except Exception:
            logger.debug("ProceduralMemory not available for dream mode", exc_info=True)
            procedural_memory = None

    dm = DreamMode(
        long_term=long_term,
        episodic=episodic,
        conversation=conversation,
        musculoskeletal=musculoskeletal,
        retriever=retriever,
        crm=crm,
        procedural_memory=procedural_memory,
        data_event_bus=data_event_bus,
        db_path=db_path,
        dream_log_path=dream_log_path,
    )
    await dm.initialize()
    return dm
