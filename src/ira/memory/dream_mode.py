"""Dream mode — nightly memory consolidation, gap detection, and creative synthesis."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiosqlite
import httpx

from ira.config import LLMConfig, get_settings
from ira.data.models import DreamReport
from ira.memory.conversation import ConversationMemory
from ira.memory.episodic import EpisodicMemory
from ira.memory.long_term import LongTermMemory

logger = logging.getLogger(__name__)

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


class DreamMode:
    def __init__(
        self,
        long_term: LongTermMemory,
        episodic: EpisodicMemory,
        conversation: ConversationMemory,
        musculoskeletal: Any | None = None,
        retriever: Any | None = None,
        db_path: str = "conversations.db",
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._long_term = long_term
        self._episodic = episodic
        self._conversation = conversation
        self._musculoskeletal = musculoskeletal
        self._retriever = retriever
        self._db_path = db_path
        llm = llm_config or get_settings().llm
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model
        self._db: aiosqlite.Connection | None = None

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

    async def run_dream_cycle(self) -> DreamReport:
        memories_consolidated = 0
        gaps: list[dict[str, Any]] = []
        connections: list[dict[str, Any]] = []
        campaign_insights: list[str] = []

        try:
            if self._conversation._db is None:
                raise RuntimeError("ConversationMemory db not initialized")
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            cursor = await self._conversation._db.execute(
                """
                SELECT DISTINCT user_id, channel FROM conversations
                WHERE last_message_at >= ?
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for user_id, channel in rows:
                history = await self._conversation.get_history(user_id, channel)
                if len(history) >= 2:
                    await self._episodic.consolidate_episode(history, user_id)
                    memories_consolidated += 1
        except Exception:
            logger.exception("Dream cycle Stage 1 (memory consolidation) failed")

        try:
            assert self._db is not None
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            cursor = await self._db.execute(
                """
                SELECT query, gaps FROM knowledge_gaps
                WHERE created_at >= ?
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            if rows:
                gap_text = "\n".join(
                    f"Query: {r[0]}\nGaps: {r[1]}" for r in rows
                )
                raw = await self._llm_call(_GAP_SYSTEM_PROMPT, gap_text, temperature=0)
                try:
                    parsed = json.loads(raw)
                    gaps = parsed.get("gaps", [])
                    if not isinstance(gaps, list):
                        gaps = []
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            logger.exception("Dream cycle Stage 2 (knowledge gap detection) failed")

        try:
            top_gaps = gaps[:5]
            recent_episodes: list[dict[str, Any]] = []
            if self._db is not None:
                cursor = await self._db.execute(
                    """
                    SELECT narrative, created_at FROM episodes
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
                ep_rows = await cursor.fetchall()
                await cursor.close()
                recent_episodes = [
                    {"narrative": r[0], "created_at": r[1]} for r in ep_rows
                ]
            context_parts = []
            if top_gaps:
                context_parts.append(
                    "Knowledge gaps:\n" + json.dumps(top_gaps, indent=2)
                )
            if recent_episodes:
                context_parts.append(
                    "Recent episodes:\n" + "\n".join(
                        f"[{e['created_at']}] {e['narrative']}" for e in recent_episodes
                    )
                )
            context = "\n\n".join(context_parts) if context_parts else "No gaps or episodes."
            raw = await self._llm_call(
                _CREATIVE_SYSTEM_PROMPT, context, temperature=0.3
            )
            try:
                parsed = json.loads(raw)
                connections = parsed.get("connections", [])
                if not isinstance(connections, list):
                    connections = []
            except (json.JSONDecodeError, TypeError):
                pass
        except Exception:
            logger.exception("Dream cycle Stage 3 (creative synthesis) failed")

        try:
            if self._musculoskeletal is not None:
                myokines = await self._musculoskeletal.extract_myokines(
                    period_days=7
                )
                myokines_text = json.dumps(myokines, indent=2)
                raw = await self._llm_call(
                    _CAMPAIGN_SYSTEM_PROMPT, myokines_text, temperature=0
                )
                try:
                    parsed = json.loads(raw)
                    campaign_insights = parsed.get("insights", [])
                    if not isinstance(campaign_insights, list):
                        campaign_insights = []
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            logger.exception("Dream cycle Stage 4 (campaign reflection) failed")

        report = DreamReport(
            cycle_date=date.today(),
            memories_consolidated=memories_consolidated,
            gaps_identified=[g.get("description", "") for g in gaps],
            creative_connections=[c.get("insight", "") for c in connections],
            campaign_insights=campaign_insights,
        )
        assert self._db is not None
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
        return report

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
            gaps = json.loads(r[2]) if isinstance(r[2], str) else r[2] or []
            creative = json.loads(r[3]) if isinstance(r[3], str) else r[3] or []
            campaign = json.loads(r[4]) if isinstance(r[4], str) else r[4] or []
            reports.append(
                DreamReport(
                    cycle_date=cycle_dt,
                    memories_consolidated=r[1],
                    gaps_identified=gaps,
                    creative_connections=creative,
                    campaign_insights=campaign,
                )
            )
        return reports

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

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> DreamMode:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
