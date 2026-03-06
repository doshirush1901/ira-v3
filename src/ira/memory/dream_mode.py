"""Dream mode — nightly memory consolidation, gap detection, and creative synthesis.

Implements a 5-stage dream cycle:
  1. Memory Ingestion — pull recent interactions from the CRM.
  2. Episodic Consolidation — group related interactions into narrative episodes.
  3. Insight Generation — LLM-driven pattern/contradiction detection across episodes.
  4. Procedural Learning — turn repeatable successful patterns into procedures.
  5. Memory Pruning — archive or summarise older, less-relevant memories.

Each cycle is logged to ``dream_log.json`` for auditability.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import httpx

from ira.config import LLMConfig, get_settings
from ira.data.models import DreamReport
from ira.memory.conversation import ConversationMemory
from ira.memory.episodic import EpisodicMemory
from ira.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

_DREAM_LOG_PATH = Path("dream_log.json")

_GAP_SYSTEM_PROMPT = (
    "You are a knowledge gap analyst. Given these queries where knowledge was insufficient, "
    "group them by topic and generate a prioritized list of knowledge gaps.\n\n"
    'Return ONLY valid JSON:\n'
    '{"gaps": [{"topic": "", "description": "", "priority": "HIGH|MEDIUM|LOW", "related_queries": []}]}'
)

_CREATIVE_SYSTEM_PROMPT = (
    "You are Ira's creative subconscious. During this dream cycle, you are processing recent "
    "memories and knowledge gaps. Find novel, non-obvious connections between these pieces of "
    "information. Think like a strategist: what patterns emerge? What market trends might be "
    "forming? What cross-customer insights can you surface?\n\n"
    'Return ONLY valid JSON:\n'
    '{"connections": [{"insight": "", "supporting_evidence": [], "confidence": "HIGH|MEDIUM|LOW"}]}'
)

_CAMPAIGN_SYSTEM_PROMPT = (
    "You are a campaign performance analyst. Given these action outcomes and learning signals "
    "from the past 7 days, analyze patterns and generate improvement suggestions. Focus on: "
    "email reply rates, quote conversion, lead qualification accuracy, and outreach effectiveness.\n\n"
    'Return ONLY valid JSON:\n'
    '{"insights": []}'
)

_INSIGHT_SYSTEM_PROMPT = (
    "You are Ira's deep-analysis engine. You are given a set of recent episodic memories "
    "(narrative summaries of interactions). Your job is to find:\n"
    "1. Recurring patterns (e.g. the same objection keeps appearing).\n"
    "2. Contradictions (e.g. one customer says X, another says the opposite).\n"
    "3. Strategic insights (e.g. a new market trend, a competitor move).\n"
    "4. Actionable recommendations.\n\n"
    "Return ONLY valid JSON:\n"
    '{"patterns": [{"description": "", "frequency": 0, "examples": []}], '
    '"contradictions": [{"description": "", "sources": []}], '
    '"insights": [{"insight": "", "confidence": "HIGH|MEDIUM|LOW", "evidence": []}], '
    '"recommendations": [{"action": "", "priority": "HIGH|MEDIUM|LOW", "rationale": ""}]}'
)

_PROCEDURAL_SYSTEM_PROMPT = (
    "You are a process optimisation engine. Given a set of strategic insights and the "
    "episodes they were derived from, identify any repeatable successful action patterns "
    "that should be codified as standard procedures.\n\n"
    "Return ONLY valid JSON:\n"
    '{"procedures": [{"trigger": "when this situation occurs", '
    '"steps": ["step 1", "step 2"], "expected_outcome": "", "confidence": "HIGH|MEDIUM|LOW"}]}'
)

_PRUNE_SYSTEM_PROMPT = (
    "You are a memory curator. Given a list of older episodic memories, decide which ones "
    "to KEEP (still strategically relevant), SUMMARISE (merge into a shorter form), or "
    "ARCHIVE (no longer useful for active decision-making).\n\n"
    "Return ONLY valid JSON:\n"
    '{"keep": [<episode ids>], "summarise": [{"ids": [<ids>], "summary": "merged summary"}], '
    '"archive": [<episode ids>]}'
)


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
        db_path: str = "conversations.db",
        llm_config: LLMConfig | None = None,
        dream_log_path: str | Path | None = None,
    ) -> None:
        self._long_term = long_term
        self._episodic = episodic
        self._conversation = conversation
        self._musculoskeletal = musculoskeletal
        self._retriever = retriever
        self._crm = crm
        self._procedural = procedural_memory
        self._db_path = db_path
        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model
        self._db: aiosqlite.Connection | None = None
        self._dream_log_path = Path(dream_log_path) if dream_log_path else _DREAM_LOG_PATH

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
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()

    # ── public API ────────────────────────────────────────────────────────

    async def run_dream_cycle(self) -> DreamReport:
        """Execute the full 5-stage dream cycle and return a report."""
        logger.info("DREAM CYCLE starting")
        stage_log: dict[str, Any] = {"cycle_date": date.today().isoformat(), "stages": {}}

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

        # Stage 4 — Procedural Learning
        await self._stage4_procedural_learning(insights, episodes, stage_log)

        # Stage 5 — Memory Pruning
        await self._stage5_memory_pruning(stage_log)

        report = DreamReport(
            cycle_date=date.today(),
            memories_consolidated=memories_consolidated,
            gaps_identified=[g.get("description", "") for g in gaps],
            creative_connections=[c.get("insight", "") for c in connections],
            campaign_insights=campaign_insights,
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
        except Exception:
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
            except Exception:
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
        except Exception:
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
                raw = await self._llm_call(_INSIGHT_SYSTEM_PROMPT, episode_text, temperature=0.2)
                try:
                    insights = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    insights = {}
            stage_log.setdefault("stages", {})["3a_cross_episode_insights"] = {
                "status": "ok",
                "patterns": len(insights.get("patterns", [])),
                "contradictions": len(insights.get("contradictions", [])),
                "recommendations": len(insights.get("recommendations", [])),
            }
        except Exception:
            logger.exception("Dream Stage 3a (cross-episode insights) failed")
            stage_log.setdefault("stages", {})["3a_cross_episode_insights"] = {"status": "error"}

        # 3b — Knowledge gap detection (from metacognition table)
        try:
            if self._db is not None:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                cursor = await self._db.execute(
                    "SELECT query, gaps FROM knowledge_gaps WHERE created_at >= ?",
                    (cutoff,),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                if rows:
                    gap_text = "\n".join(f"Query: {r[0]}\nGaps: {r[1]}" for r in rows)
                    raw = await self._llm_call(_GAP_SYSTEM_PROMPT, gap_text, temperature=0)
                    try:
                        parsed = json.loads(raw)
                        gaps = parsed.get("gaps", [])
                        if not isinstance(gaps, list):
                            gaps = []
                    except (json.JSONDecodeError, TypeError):
                        pass
            stage_log["stages"]["3b_gap_detection"] = {
                "status": "ok",
                "gaps_found": len(gaps),
            }
        except Exception:
            logger.exception("Dream Stage 3b (gap detection) failed")
            stage_log["stages"]["3b_gap_detection"] = {"status": "error"}

        # 3c — Creative synthesis
        try:
            top_gaps = gaps[:5]
            recent_episodes: list[dict[str, Any]] = []
            if self._db is not None:
                cursor = await self._db.execute(
                    "SELECT narrative, created_at FROM episodes ORDER BY created_at DESC LIMIT 5"
                )
                ep_rows = await cursor.fetchall()
                await cursor.close()
                recent_episodes = [{"narrative": r[0], "created_at": r[1]} for r in ep_rows]

            context_parts = []
            if top_gaps:
                context_parts.append("Knowledge gaps:\n" + json.dumps(top_gaps, indent=2))
            if recent_episodes:
                context_parts.append(
                    "Recent episodes:\n"
                    + "\n".join(f"[{e['created_at']}] {e['narrative']}" for e in recent_episodes)
                )
            context = "\n\n".join(context_parts) if context_parts else "No gaps or episodes."
            raw = await self._llm_call(_CREATIVE_SYSTEM_PROMPT, context, temperature=0.3)
            try:
                parsed = json.loads(raw)
                connections = parsed.get("connections", [])
                if not isinstance(connections, list):
                    connections = []
            except (json.JSONDecodeError, TypeError):
                pass
            stage_log["stages"]["3c_creative_synthesis"] = {
                "status": "ok",
                "connections_found": len(connections),
            }
        except Exception:
            logger.exception("Dream Stage 3c (creative synthesis) failed")
            stage_log["stages"]["3c_creative_synthesis"] = {"status": "error"}

        # 3d — Campaign reflection (via musculoskeletal myokines)
        try:
            if self._musculoskeletal is not None:
                myokines = await self._musculoskeletal.extract_myokines(period_days=7)
                myokines_text = json.dumps(myokines, indent=2)
                raw = await self._llm_call(_CAMPAIGN_SYSTEM_PROMPT, myokines_text, temperature=0)
                try:
                    parsed = json.loads(raw)
                    campaign_insights = parsed.get("insights", [])
                    if not isinstance(campaign_insights, list):
                        campaign_insights = []
                except (json.JSONDecodeError, TypeError):
                    pass
            stage_log["stages"]["3d_campaign_reflection"] = {
                "status": "ok",
                "campaign_insights": len(campaign_insights),
            }
        except Exception:
            logger.exception("Dream Stage 3d (campaign reflection) failed")
            stage_log["stages"]["3d_campaign_reflection"] = {"status": "error"}

        return insights, gaps, connections, campaign_insights

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
                r for r in recommendations if r.get("priority") == "HIGH"
            ]

            if not high_confidence and not episodes:
                stage_log["stages"]["4_procedural_learning"] = {
                    "status": "ok",
                    "procedures_created": 0,
                }
                return

            # Ask LLM to derive procedures from insights + episodes
            context_parts = []
            if high_confidence:
                context_parts.append(
                    "High-priority recommendations:\n" + json.dumps(high_confidence, indent=2)
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
            raw = await self._llm_call(_PROCEDURAL_SYSTEM_PROMPT, context, temperature=0)

            derived: list[dict[str, Any]] = []
            try:
                parsed = json.loads(raw)
                derived = parsed.get("procedures", [])
                if not isinstance(derived, list):
                    derived = []
            except (json.JSONDecodeError, TypeError):
                pass

            for proc in derived:
                trigger = proc.get("trigger", "")
                steps = proc.get("steps", [])
                if trigger and steps:
                    await self._procedural.learn_procedure(trigger, steps)
                    procedures_created += 1

            logger.info("Stage 4: created %d new procedures", procedures_created)
            stage_log["stages"]["4_procedural_learning"] = {
                "status": "ok",
                "procedures_created": procedures_created,
            }
        except Exception:
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
            raw = await self._llm_call(_PRUNE_SYSTEM_PROMPT, episodes_text, temperature=0)

            try:
                decisions = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                decisions = {}

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
        except Exception:
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
             campaign_insights, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report.cycle_date.isoformat(),
                report.memories_consolidated,
                json.dumps(report.gaps_identified),
                json.dumps(report.creative_connections),
                json.dumps(report.campaign_insights),
                now,
            ),
        )
        await self._db.commit()

    def _write_dream_log(self, stage_log: dict[str, Any], report: DreamReport) -> None:
        """Append the cycle results to dream_log.json."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_date": report.cycle_date.isoformat(),
            "memories_consolidated": report.memories_consolidated,
            "gaps_identified": report.gaps_identified,
            "creative_connections": report.creative_connections,
            "campaign_insights": report.campaign_insights,
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
                   creative_connections, campaign_insights
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
            reports.append(
                DreamReport(
                    cycle_date=cycle_dt,
                    memories_consolidated=r[1],
                    gaps_identified=gaps_val,
                    creative_connections=creative,
                    campaign_insights=campaign,
                )
            )
        return reports

    # ── LLM ───────────────────────────────────────────────────────────────

    async def _llm_call(
        self, system: str, user: str, temperature: float = 0
    ) -> str:
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
            logger.exception("DreamMode LLM call failed")
            return "(LLM call failed)"

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> DreamMode:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
