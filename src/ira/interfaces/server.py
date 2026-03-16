"""FastAPI server — main entry point for the Ira application.

Bootstraps every subsystem during startup, exposes REST endpoints for
querying, health, pipeline, ingestion, board meetings, dream reports,
and email drafting, then tears everything down gracefully on shutdown.

Run with::

    uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000 --limit-concurrency 5 --timeout-keep-alive 30
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ira.middleware.auth import require_api_key
from ira.middleware.request_context import RequestContextMiddleware, RequestIdFilter

from ira.config import get_settings
from ira.exceptions import ConfigurationError, IraError
from ira.systems.data_dir_lock import async_data_dir_lock
from ira.services.structured_logging import configure_root_logging
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)


# ── Request / response schemas ────────────────────────────────────────────


class QueryRequest(BaseModel):
    query: str
    user_id: str | None = None
    context: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    response: str
    agents_consulted: list[str] | None = None


class QueryAgentRequest(BaseModel):
    """Ask a specific agent directly (bypasses pipeline routing). Use for Cursor/Ira flows where Ira must contribute a minimum share."""
    query: str
    agent_name: str  # e.g. "themis", "calliope", "clio"
    user_id: str | None = None
    context: dict[str, Any] | None = None


class BoardMeetingRequest(BaseModel):
    topic: str
    participants: list[str] | None = None


class FeedbackRequest(BaseModel):
    correction: str
    previous_query: str
    previous_response: str
    user_id: str | None = None
    severity: str = "HIGH"


class FeedbackResponse(BaseModel):
    status: str
    polarity: str
    correction_id: int | None = None
    micro_learning_triggered: bool = False


class EmailSearchRequest(BaseModel):
    from_address: str = ""
    to_address: str = ""
    subject: str = ""
    label: str = ""
    query: str = ""
    after: str = ""
    before: str = ""
    max_results: int = 10


class EmailDraftRequest(BaseModel):
    to: str
    subject: str
    context: str
    tone: str = "professional"


class EmailSendRequest(BaseModel):
    """Payload for sending an email (only when user explicitly said 'send')."""

    to: str
    subject: str
    body: str
    cc: str | None = None
    thread_id: str | None = None


class OutboundMessageRequest(BaseModel):
    to: str
    subject: str
    body: str


class OutboundDraftBatchRequest(BaseModel):
    campaign_name: str
    created_by: str
    messages: list[OutboundMessageRequest]


class OutboundApproveRequest(BaseModel):
    batch_id: str
    approved_by: str


class TaskRequest(BaseModel):
    goal: str
    user_id: str | None = None
    output_format: str = "markdown"


class TaskClarificationRequest(BaseModel):
    task_id: str
    answer: str
    user_id: str | None = None


class TaskAbortRequest(BaseModel):
    task_id: str
    reason: str = ""


class TaskRetryRequest(BaseModel):
    task_id: str
    from_phase: int | None = None


# ── Anu (AI Recruiter) ─────────────────────────────────────────────────────

class AnuScoreRequest(BaseModel):
    candidate_profile: dict[str, Any]
    job_description: str = ""


class AnuChatRequest(BaseModel):
    candidate_profile: dict[str, Any]
    message: str
    conversation_history: list[dict[str, str]] | None = None


class AnuParseTextRequest(BaseModel):
    resume_text: str


class AnuCvParsedUpdateRequest(BaseModel):
    """Body for updating a candidate's CV-parsed profile (from Anu parse-resume)."""

    candidate_profile: dict[str, Any]


class AnuDraftRecruitmentStage2Request(BaseModel):
    """Inputs for drafting Stage 2 recruitment email (case study + DICE + skills)."""

    candidate_name: str = ""
    role: str = ""
    case_study_text: str = ""
    dice_questions: str = ""
    skills_questions: str = ""
    company_intro_short: str = ""
    job_description_or_context: str = ""


class AnuExportRequest(BaseModel):
    candidate_profile: dict[str, Any]
    scoring: dict[str, Any] | None = None
    format: str = "text"  # "text" or "pdf"


class RecruitmentUpsertRequest(BaseModel):
    """Upsert a candidate in the recruitment database."""
    email: str
    name: str | None = None
    phone: str | None = None
    role_applied: str | None = None
    profile: dict[str, Any] | None = None
    cv_parsed: dict[str, Any] | None = None
    score: dict[str, Any] | None = None
    ctc_current: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    notes: str | None = None


class RecruitmentStageEventRequest(BaseModel):
    """Record a stage event for a candidate (e.g. stage2_sent, call_invited)."""
    stage: str
    event_at: str | None = None  # ISO datetime; default now
    metadata: dict[str, Any] | None = None


class RecruitmentCandidateUpdateRequest(BaseModel):
    """Update candidate fields (ctc_current, notes, etc.)."""
    ctc_current: str | None = None
    notes: str | None = None
    name: str | None = None
    phone: str | None = None
    role_applied: str | None = None


# ── Service registry ──────────────────────────────────────────────────────
#
# Populated during the lifespan startup phase and cleared on shutdown.
# Endpoints access services through this dict rather than globals.

_services: dict[str, Any] = {}

# WebSocket connections for Command Center event stream (DataEventBus broadcast).
_ws_connections: set[WebSocket] = set()


async def _broadcast_ws(payload: dict[str, Any]) -> None:
    """Send a JSON payload to all connected WebSocket clients; remove dead connections."""
    dead: list[WebSocket] = []
    for ws in _ws_connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
            logger.debug("WS send failed, dropping connection", exc_info=True)
    for ws in dead:
        _ws_connections.discard(ws)


def _svc(name: str) -> Any:
    """Retrieve a service by name; raise 503 if not yet initialised."""
    svc = _services.get(name)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"Service '{name}' not available")
    return svc


def _normalize_task_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize task stream payloads to a stable event contract."""
    normalized = dict(event)
    normalized.setdefault("event_version", "v1")
    normalized.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    return normalized


# ── Lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap all Ira subsystems on startup, tear down on shutdown."""
    settings = get_settings()
    _data_dir_lock = async_data_dir_lock()
    await _data_dir_lock.__aenter__()
    try:
            # ── Sentry (must be first so it captures all boot errors) ────
        sentry_dsn = settings.sentry.dsn
        if sentry_dsn:
            try:
                import sentry_sdk
    
                sentry_sdk.init(
                    dsn=sentry_dsn,
                    traces_sample_rate=settings.sentry.traces_sample_rate,
                    environment=settings.app.environment,
                    send_default_pii=False,
                )
                logger.info("Sentry initialised (env=%s)", settings.app.environment)
            except Exception:
                logger.warning("Sentry init failed — continuing without error tracking", exc_info=True)
    
        configure_root_logging(
            log_level=settings.app.log_level,
            log_format=settings.app.log_format,
        )
        for handler in logging.root.handlers:
            handler.addFilter(RequestIdFilter())
    
        from ira.systems.legacy_guard import enforce_legacy_quarantine
    
        legacy_violations = enforce_legacy_quarantine(strict=settings.app.legacy_quarantine_strict)
        if legacy_violations:
            logger.warning(
                "Legacy quarantine found %d runtime import violations",
                len(legacy_violations),
            )
    
        # ── Redis ─────────────────────────────────────────────────────────
        from ira.systems.redis_cache import RedisCache
    
        redis_cache = RedisCache()
        await redis_cache.connect()
        _services[SK.REDIS] = redis_cache
        from ira.services.llm_client import get_llm_client, reset_llm_circuit_breakers
        get_llm_client().set_redis_cache(redis_cache)
    
        # ── Google Docs / Drive ──────────────────────────────────────────
        from ira.systems.google_docs import GoogleDocsService
    
        google_docs = GoogleDocsService()
        try:
            await google_docs.connect()
        except Exception:
            logger.warning("Google Docs/Drive unavailable — continuing without it")
        _services[SK.GOOGLE_DOCS] = google_docs
    
        # ── Google Document AI ────────────────────────────────────────────
        from ira.systems.document_ai import DocumentAIService
    
        document_ai = DocumentAIService()
        try:
            await document_ai.connect()
        except Exception:
            logger.warning("Document AI unavailable — continuing without it")
        _services[SK.DOCUMENT_AI] = document_ai
    
        # ── PDF.co ────────────────────────────────────────────────────────
        from ira.systems.pdfco import PdfCoService
    
        pdfco = PdfCoService()
        _services[SK.PDFCO] = pdfco
    
        # ── Google DLP ────────────────────────────────────────────────────
        from ira.systems.dlp import DlpService
    
        dlp = DlpService()
        try:
            await dlp.connect()
        except Exception:
            logger.warning("DLP unavailable — continuing without it")
        _services[SK.DLP] = dlp
    
        # ── Brain layer ───────────────────────────────────────────────────
        from ira.brain.document_ingestor import DocumentIngestor
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.knowledge_graph import KnowledgeGraph
        from ira.brain.qdrant_manager import QdrantManager
        from ira.brain.retriever import UnifiedRetriever
    
        embedding = EmbeddingService()
        if redis_cache.available:
            embedding.set_redis_cache(redis_cache)
        qdrant = QdrantManager(embedding_service=embedding)
        await qdrant.ensure_collection()
        graph = KnowledgeGraph()
    
        mem0_client = None
        mem0_key = settings.memory.api_key.get_secret_value()
        if mem0_key:
            try:
                from mem0 import MemoryClient
                mem0_client = MemoryClient(api_key=mem0_key)
                logger.info("Mem0 client initialised")
            except (ConfigurationError, Exception):
                logger.warning("Mem0 init failed — continuing without conversational memory")
    
        retriever = UnifiedRetriever(qdrant=qdrant, graph=graph, mem0_client=mem0_client)
        ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)
    
        _services["embedding"] = embedding
        _services["qdrant"] = qdrant
        _services["graph"] = graph
        _services["retriever"] = retriever
        _services["ingestor"] = ingestor
    
        # ── Data layer ────────────────────────────────────────────────────
        from ira.data.crm import CRMDatabase
        from ira.data.quotes import QuoteManager
    
        crm = CRMDatabase()
        await crm.create_tables()
        quotes = QuoteManager(session_factory=crm.session_factory)
    
        from ira.data.vendors import VendorDatabase
    
        vendor_db = VendorDatabase()
        await vendor_db.create_tables()
    
        _services[SK.CRM] = crm
        _services[SK.QUOTES] = quotes
        _services[SK.VENDOR_DB] = vendor_db
    
        # ── Circulatory system (data sync) ────────────────────────────────
        from ira.systems.circulatory import CirculatorySystem
        from ira.systems.data_event_bus import DataEventBus
    
        data_event_bus = DataEventBus()
        await data_event_bus.start()
    
        crm.set_event_bus(data_event_bus)
        graph.set_event_bus(data_event_bus)
        qdrant.set_event_bus(data_event_bus)
    
        circulatory = CirculatorySystem(
            data_event_bus,
            crm=crm,
            graph=graph,
            qdrant=qdrant,
            embedding=embedding,
        )
    
        from ira.brain.correction_learner import CorrectionLearner
        from ira.systems.data_event_bus import DataEvent, EventType
    
        correction_learner = CorrectionLearner()
        data_event_bus.subscribe(EventType.KNOWLEDGE_CORRECTED, correction_learner.on_knowledge_corrected)
    
        async def _ws_bus_handler(evt: DataEvent) -> None:
            """Broadcast DataEventBus events to Command Center WebSocket clients."""
            payload = {
                "ts": evt.timestamp.isoformat(),
                "type": evt.event_type.value,
                "entity_type": evt.entity_type,
                "entity_id": evt.entity_id,
                "source_store": evt.source_store.value,
                "payload_keys": list(evt.payload.keys()),
            }
            await _broadcast_ws(payload)
    
        data_event_bus.subscribe_all(_ws_bus_handler)
    
        _services[SK.DATA_EVENT_BUS] = data_event_bus
        _services[SK.CIRCULATORY] = circulatory
    
        # ── Pricing engine ────────────────────────────────────────────────
        from ira.brain.pricing_engine import PricingEngine
    
        pricing_engine = PricingEngine(retriever=retriever, crm=crm)
    
        _services[SK.PRICING_ENGINE] = pricing_engine
    
        # ── Pantheon ──────────────────────────────────────────────────────
        from ira.message_bus import MessageBus
        from ira.pantheon import Pantheon
    
        bus = MessageBus()
        if redis_cache.available:
            bus.set_redis(redis_cache)
        pantheon = Pantheon(retriever=retriever, bus=bus)
    
        shared_services = {
            SK.CRM: crm,
            SK.QUOTES: quotes,
            SK.PRICING_ENGINE: pricing_engine,
            SK.RETRIEVER: retriever,
            SK.VENDOR_DB: vendor_db,
        }
    
        pantheon.inject_services(shared_services)
    
        from ira.skills.handlers import bind_services as bind_skill_services
        bind_skill_services(shared_services)
    
        await pantheon.start()
    
        _services["bus"] = bus
        _services["pantheon"] = pantheon
    
        # ── Body systems ──────────────────────────────────────────────────
        from ira.systems.digestive import DigestiveSystem
        from ira.systems.endocrine import EndocrineSystem
        from ira.systems.immune import ImmuneSystem
        from ira.systems.sensory import SensorySystem
        from ira.systems.voice import VoiceSystem
    
        digestive = DigestiveSystem(
            ingestor=ingestor,
            knowledge_graph=graph,
            embedding_service=embedding,
            qdrant=qdrant,
        )
        immune = ImmuneSystem(
            qdrant=qdrant,
            knowledge_graph=graph,
            embedding_service=embedding,
        )
        sensory = SensorySystem(knowledge_graph=graph)  # memory wired after init below
        try:
            await asyncio.wait_for(sensory.create_tables(), timeout=30)
        except (asyncio.TimeoutError, Exception):
            logger.warning("SensorySystem table creation slow/failed — continuing")
        voice = VoiceSystem()
        endocrine = EndocrineSystem()
        immune.set_endocrine(endocrine)
    
        _services["digestive"] = digestive
        _services["immune"] = immune
        _services["sensory"] = sensory
        _services["voice"] = voice
        _services["endocrine"] = endocrine
    
        # ── Memory systems ────────────────────────────────────────────────
        from ira.memory.conversation import ConversationMemory
        from ira.memory.dream_mode import DreamMode
        from ira.memory.episodic import EpisodicMemory
        from ira.memory.long_term import LongTermMemory
        from ira.systems.musculoskeletal import MusculoskeletalSystem
    
        _INIT_TIMEOUT = 30
    
        async def _safe_init(name: str, coro: Any) -> None:
            try:
                await asyncio.wait_for(coro, timeout=_INIT_TIMEOUT)
                logger.info("Initialised %s", name)
            except asyncio.TimeoutError:
                logger.warning("Timed out initialising %s after %ds — skipping", name, _INIT_TIMEOUT)
            except (ConfigurationError, Exception):
                logger.warning("Failed to initialise %s — skipping", name, exc_info=True)
    
        long_term = LongTermMemory()
        episodic = EpisodicMemory(long_term=long_term)
        await _safe_init("episodic", episodic.initialize())
        conversation = ConversationMemory()
        await _safe_init("conversation", conversation.initialize())
        musculoskeletal = MusculoskeletalSystem()
        await _safe_init("musculoskeletal", musculoskeletal.create_tables())
    
        dream_mode = DreamMode(
            long_term=long_term,
            episodic=episodic,
            conversation=conversation,
            musculoskeletal=musculoskeletal,
            retriever=retriever,
            crm=crm,
            data_event_bus=data_event_bus,
        )
        await _safe_init("dream_mode", dream_mode.initialize())
    
        _services["long_term"] = long_term
        _services["episodic"] = episodic
        _services["conversation"] = conversation
        _services["musculoskeletal"] = musculoskeletal
        _services["dream_mode"] = dream_mode
    
        # ── Learning hub ──────────────────────────────────────────────────
        from ira.memory.procedural import ProceduralMemory
        from ira.systems.learning_hub import LearningHub
    
        procedural_memory = ProceduralMemory()
        await _safe_init("procedural_memory", procedural_memory.initialize())
        learning_hub = LearningHub(crm=crm, procedural_memory=procedural_memory)
    
        dream_mode.configure(procedural_memory=procedural_memory)
    
        # ── Agent journal (daily actions + nightly reflections) ─────────────
        from ira.memory.agent_journal import AgentJournal
        agent_journal = AgentJournal()
        await _safe_init("agent_journal", agent_journal.initialize())
        dream_mode.configure(agent_journal=agent_journal)
    
        _services["procedural_memory"] = procedural_memory
        _services["agent_journal"] = agent_journal
        _services["learning_hub"] = learning_hub
    
        # ── Feedback handler & power levels (trust matrix) ─────────────────
        from ira.brain.correction_store import CorrectionStore
        from ira.brain.feedback_handler import FeedbackHandler
        from ira.brain.power_levels import PowerLevelTracker
    
        correction_store = CorrectionStore()
        await _safe_init("correction_store", correction_store.initialize())
        power_level_tracker = PowerLevelTracker()
        await _safe_init("power_level_tracker", power_level_tracker._load())
    
        feedback_handler = FeedbackHandler(
            learning_hub=learning_hub,
            correction_store=correction_store,
            mem0_client=mem0_client,
            procedural_memory=procedural_memory,
            data_event_bus=data_event_bus,
            power_level_tracker=power_level_tracker,
        )
        await feedback_handler.load_scores()
    
        _services["feedback_handler"] = feedback_handler
        _services["correction_store"] = correction_store
        _services["power_level_tracker"] = power_level_tracker
    
        nemesis = pantheon.get_agent("nemesis")
        if nemesis is not None:
            nemesis.configure(learning_hub=learning_hub, peer_agents=pantheon.agents)
    
        # ── Additional memory systems ─────────────────────────────────────
        from ira.memory.emotional_intelligence import EmotionalIntelligence
        from ira.memory.goal_manager import GoalManager
        from ira.memory.inner_voice import InnerVoice
        from ira.memory.metacognition import Metacognition
        from ira.memory.relationship import RelationshipMemory
    
        emotional_intelligence = EmotionalIntelligence()
        await _safe_init("emotional_intelligence", emotional_intelligence.initialize())
        relationship_memory = RelationshipMemory()
        await _safe_init("relationship_memory", relationship_memory.initialize())
        goal_manager = GoalManager()
        await _safe_init("goal_manager", goal_manager.initialize())
        metacognition = Metacognition()
        await _safe_init("metacognition", metacognition.initialize())
        inner_voice = InnerVoice()
        await _safe_init("inner_voice", inner_voice.initialize())
    
        sensory.configure_memory(
            emotional_intelligence=emotional_intelligence,
            conversation_memory=conversation,
            relationship_memory=relationship_memory,
        )
    
        _services["emotional_intelligence"] = emotional_intelligence
        _services["relationship_memory"] = relationship_memory
        _services["goal_manager"] = goal_manager
        _services["metacognition"] = metacognition
        _services["inner_voice"] = inner_voice
    
        # ── Inject ALL memory services into Pantheon agents ───────────────
        pantheon.inject_services({
            SK.LONG_TERM_MEMORY: long_term,
            SK.EPISODIC_MEMORY: episodic,
            SK.CONVERSATION_MEMORY: conversation,
            SK.RELATIONSHIP_MEMORY: relationship_memory,
            SK.GOAL_MANAGER: goal_manager,
            SK.EMOTIONAL_INTELLIGENCE: emotional_intelligence,
            SK.PROCEDURAL_MEMORY: procedural_memory,
            SK.LEARNING_HUB: learning_hub,
            SK.DATA_EVENT_BUS: data_event_bus,
            SK.PANTHEON: pantheon,
            SK.REDIS: redis_cache,
            SK.GOOGLE_DOCS: google_docs,
            SK.DOCUMENT_AI: document_ai,
            SK.PDFCO: pdfco,
            SK.DLP: dlp,
            SK.AGENT_JOURNAL: agent_journal,
            SK.IMMUNE: immune,
            SK.POWER_LEVEL_TRACKER: power_level_tracker,
        })
    
        # ── Unified context ───────────────────────────────────────────────
        from ira.context import UnifiedContextManager
    
        unified_context = UnifiedContextManager()
        _services["unified_context"] = unified_context
    
        # ── Tool stats (observability) ────────────────────────────────────
        from ira.brain.tool_stats import ToolStatsTracker
        tool_stats_tracker = ToolStatsTracker()
        _services["tool_stats_tracker"] = tool_stats_tracker
    
        # ── Request pipeline ──────────────────────────────────────────────
        from ira.pipeline import RequestPipeline
    
        request_pipeline = RequestPipeline(
            sensory=sensory,
            conversation_memory=conversation,
            relationship_memory=relationship_memory,
            goal_manager=goal_manager,
            procedural_memory=procedural_memory,
            metacognition=metacognition,
            inner_voice=inner_voice,
            pantheon=pantheon,
            voice=voice,
            endocrine=endocrine,
            crm=crm,
            musculoskeletal=musculoskeletal,
            unified_context=unified_context,
            redis_cache=redis_cache,
            episodic_memory=episodic,
            long_term_memory=long_term,
            tool_stats_tracker=tool_stats_tracker,
            agent_journal=agent_journal,
            power_level_tracker=power_level_tracker,
        )
        _services["pipeline"] = request_pipeline
    
        # ── Task orchestrator ────────────────────────────────────────────
        from ira.systems.task_orchestrator import TaskOrchestrator
    
        task_orchestrator = TaskOrchestrator(
            pantheon=pantheon,
            redis_cache=redis_cache,
            voice=voice,
            pdfco=pdfco,
        )
        _services["task_orchestrator"] = task_orchestrator
    
        # ── Board meeting system ──────────────────────────────────────────
        from ira.systems.board_meeting import BoardMeeting
    
        async def _agent_handler(name: str, topic: str) -> str:
            agent = pantheon.get_agent(name)
            if agent is None:
                return f"(Agent '{name}' not found)"
            return await agent.handle(topic)
    
        board_meeting = BoardMeeting(agent_handler=_agent_handler)
        _services["board_meeting"] = board_meeting
    
        # ── Email processor ───────────────────────────────────────────────
        from ira.interfaces.email_processor import EmailProcessor
    
        delphi = pantheon.get_agent("delphi")
        email_processor = EmailProcessor(
            delphi=delphi,
            digestive=digestive,
            sensory=sensory,
            crm=crm,
            pantheon=pantheon,
            unified_context=unified_context,
        )
        _services["email_processor"] = email_processor
        pantheon.inject_services({SK.EMAIL_PROCESSOR: email_processor})
    
        # ── Drip engine ────────────────────────────────────────────────────
        from ira.interfaces.email_processor import GmailDraftSender
        from ira.systems.drip_engine import AutonomousDripEngine
        from ira.systems.outbound_approvals import OutboundApprovalService
    
        gmail_sender = GmailDraftSender(email_processor=email_processor)
        outbound_approvals = OutboundApprovalService(
            storage_path=Path("data/operations/outbound_approvals.json"),
        )
        _services[SK.OUTBOUND_APPROVALS] = outbound_approvals
        drip_engine = AutonomousDripEngine(
            crm=crm,
            quotes=quotes,
            message_bus=bus,
            gmail=gmail_sender,
        )
        _services["drip_engine"] = drip_engine
    
        # ── Respiratory system (background tasks) ─────────────────────────
        from ira.systems.respiratory import RespiratorySystem
    
        respiratory = RespiratorySystem(
            dream_mode=dream_mode,
            drip_engine=drip_engine,
            immune_system=immune,
            email_processor=email_processor,
        )
        await respiratory.start()
        _services["respiratory"] = respiratory
    
        # ── Curiosity loop (boredom-driven inter-agent exploration) ──────
        from ira.systems.curiosity_loop import CuriosityLoop
        curiosity_loop = CuriosityLoop(endocrine=endocrine, bus=bus, pantheon=pantheon)
        await curiosity_loop.start()
        _services["curiosity_loop"] = curiosity_loop
    
        # ── Dream mode: sleep phase (phantom limb, trust, curiosity) ──────
        dream_mode.configure(
            immune_system=immune,
            power_level_tracker=power_level_tracker,
            curiosity_runner=lambda: curiosity_loop.run_one_cycle(),
        )
    
        # ── Email polling background task ─────────────────────────────────
        email_poll_task = None
        if settings.google.email_poll_enabled:
            email_poll_task = asyncio.create_task(email_processor.poll_inbox())
            logger.info(
                "Email polling started (mode=%s)", settings.google.email_mode.value,
            )
        else:
            logger.info("Email polling disabled (IRA_EMAIL_POLL=false)")
    
        # ── Immune startup validation ─────────────────────────────────────
        try:
            health_report = await immune.run_startup_validation()
            healthy = all(
                v.get("status") == "healthy" for v in health_report.values()
            )
            status = "ALL HEALTHY" if healthy else "DEGRADED"
            logger.info("Startup validation: %s — %s", status, list(health_report))
        except (IraError, Exception):
            logger.exception("Startup validation failed — continuing in degraded mode")
    
        # ── Ready ─────────────────────────────────────────────────────────
        component_count = len(_services)
        agent_count = len(pantheon.agents)
        logger.info(
            "Ira is awake — %d components, %d agents, mode=%s",
            component_count,
            agent_count,
            settings.google.email_mode.value,
        )
    
        yield
    
        # ── SHUTDOWN ──────────────────────────────────────────────────────
        logger.info("Ira is going to sleep.")
    
        try:
            from langfuse import Langfuse
            Langfuse().flush()
            logger.info("Langfuse traces flushed")
        except Exception:
            logger.warning("Langfuse flush failed", exc_info=True)
    
        if email_poll_task is not None:
            email_poll_task.cancel()
            try:
                await email_poll_task
            except asyncio.CancelledError:
                pass
    
        curiosity_loop = _services.get("curiosity_loop")
        if curiosity_loop is not None and hasattr(curiosity_loop, "stop"):
            try:
                await curiosity_loop.stop()
            except (IraError, Exception):
                logger.exception("CuriosityLoop stop failed")
        await respiratory.stop()
        await data_event_bus.stop()
        await pantheon.stop()
        await redis_cache.close()
        await google_docs.close()
        await document_ai.close()
        await dlp.close()
        await sensory.close()
        await musculoskeletal.close()
        await graph.close()
        await crm.close()
        await vendor_db.close()
    
        for svc_name in (
            "crm",
            "vendor_db",
            "correction_store",
            "conversation", "episodic", "dream_mode", "emotional_intelligence",
            "relationship_memory", "goal_manager", "metacognition", "inner_voice",
            "procedural_memory",
        ):
            svc = _services.get(svc_name)
            if svc is not None and hasattr(svc, "close"):
                try:
                    await svc.close()
                except (IraError, Exception):
                    logger.exception("Failed to close %s", svc_name)
    
        _services.clear()
        logger.info("All services shut down.")
    finally:
        await _data_dir_lock.__aexit__(None, None, None)


# ── App ───────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Ira — Machinecraft AI Pantheon",
    version="3.2.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

_cors_raw = get_settings().app.cors_origins
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else ["http://localhost:3000"]
if "*" in _cors_origins:
    logger.warning(
        "CORS_ORIGINS=* with allow_credentials=True is insecure for production; restrict to specific origins."
    )
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from ira.interfaces.dashboard import router as dashboard_router  # noqa: E402

app.include_router(dashboard_router)


# ── Middleware ─────────────────────────────────────────────────────────────


@app.middleware("http")
async def request_timing(request: Request, call_next: Any) -> Any:
    """Log request duration and wrap through RespiratorySystem breath timing."""
    start = time.monotonic()
    respiratory = _services.get(SK.RESPIRATORY)

    try:
        if respiratory is not None:
            async with respiratory.breath():
                response = await call_next(request)
        else:
            response = await call_next(request)
    except (IraError, Exception) as exc:
        immune = _services.get(SK.IMMUNE)
        if immune is not None:
            immune.log_error(exc, {"path": request.url.path, "method": request.method})
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    elapsed_ms = (time.monotonic() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Route a query through the full 11-step request pipeline."""
    pipeline = _services.get("pipeline")

    sender_id = req.user_id or "anonymous"
    channel = (req.context or {}).get("channel", "API").upper()
    metadata = req.context or {}

    agents_consulted: list[str] | None = None

    if pipeline is not None:
        response, agents_consulted = await pipeline.process_request(
            raw_input=req.query,
            channel=channel,
            sender_id=sender_id,
            metadata=metadata,
        )
    else:
        pantheon = _svc(SK.PANTHEON)
        ctx = metadata.copy()
        if req.user_id:
            unified_context = _services.get("unified_context")
            if unified_context is not None:
                ctx["cross_channel_history"] = unified_context.recent_history(
                    req.user_id, limit=10,
                )
        response = await pantheon.process(req.query, ctx)
        if req.user_id:
            unified_context = _services.get("unified_context")
            if unified_context is not None:
                unified_context.record_turn(
                    req.user_id, channel, req.query, response,
                )

    return QueryResponse(response=response, agents_consulted=agents_consulted)


@app.post("/api/query/stream")
async def query_stream(req: QueryRequest) -> EventSourceResponse:
    """Stream query progress via Server-Sent Events.

    Emits events: ``routing``, ``agent_started``, ``agent_done``,
    ``synthesizing``, ``final_answer``, and ``error``.
    """
    pipeline = _services.get("pipeline")
    sender_id = req.user_id or "anonymous"
    channel = (req.context or {}).get("channel", "API").upper()
    metadata = req.context or {}

    async def _event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def _on_progress(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def _run_pipeline() -> tuple[str, list[str] | None]:
            if pipeline is not None:
                return await pipeline.process_request(
                    raw_input=req.query,
                    channel=channel,
                    sender_id=sender_id,
                    metadata=metadata,
                    on_progress=_on_progress,
                )
            pantheon = _svc(SK.PANTHEON)
            ctx = metadata.copy()
            resp = await pantheon.process(req.query, ctx, on_progress=_on_progress)
            return resp, None

        task = asyncio.create_task(_run_pipeline())

        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {
                        "event": event.get("type", "progress"),
                        "data": _json.dumps(event, default=str),
                    }
                except asyncio.TimeoutError:
                    continue

            while not queue.empty():
                event = queue.get_nowait()
                yield {
                    "event": event.get("type", "progress"),
                    "data": _json.dumps(event, default=str),
                }

            try:
                response, agents = task.result()
                yield {
                    "event": "final_answer",
                    "data": _json.dumps({
                        "response": response,
                        "agents_consulted": agents,
                    }, default=str),
                }
            except Exception as exc:
                logger.exception("Streaming query failed")
                yield {
                    "event": "error",
                    "data": _json.dumps({"error": str(exc)}),
                }
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(_event_generator())


@app.post("/api/query/agent", response_model=QueryResponse)
async def query_agent(req: QueryAgentRequest) -> QueryResponse:
    """Call a single agent by name. Use when you need Ira (e.g. Themis, Calliope) to contribute directly; bypasses Sphinx and pipeline routing."""
    pantheon = _services.get(SK.PANTHEON)
    if pantheon is None:
        return QueryResponse(
            response="Pantheon not available.",
            agents_consulted=[],
        )
    agent = pantheon.get_agent(req.agent_name.strip().lower())
    if agent is None:
        return QueryResponse(
            response=f"Agent '{req.agent_name}' not found.",
            agents_consulted=[],
        )
    ctx = (req.context or {}).copy()
    if req.user_id:
        unified_context = _services.get("unified_context")
        if unified_context is not None:
            ctx["cross_channel_history"] = unified_context.recent_history(req.user_id, limit=5)
    try:
        response = await agent.handle(req.query, ctx)
    except Exception as e:
        logger.exception("Agent %s failed", req.agent_name)
        response = f"(Agent '{req.agent_name}' failed: {e!s})"
    return QueryResponse(response=response or "(No response)", agents_consulted=[req.agent_name.strip().lower()])


@app.post("/api/feedback", response_model=FeedbackResponse)
async def feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Process a user correction through the feedback pipeline.

    Detects polarity, stores corrections, updates agent scores, and
    triggers micro-learning when severity warrants it.
    """
    handler = _svc("feedback_handler")
    user_id = req.user_id or "anonymous"

    result = await handler.process_feedback(
        message=req.correction,
        previous_query=req.previous_query,
        previous_response=req.previous_response,
        agents_used=[],
        user_id=user_id,
        severity=req.severity,
    )

    return FeedbackResponse(
        status="processed",
        polarity=result.get("polarity", "neutral"),
        correction_id=result.get("correction_id"),
        micro_learning_triggered=result.get("micro_learning_triggered", False),
    )


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    """Run the immune system health check."""
    immune = _svc(SK.IMMUNE)
    try:
        report = await immune.run_startup_validation()
    except (IraError, Exception) as exc:
        report = getattr(exc, "health_report", {"error": str(exc)})
    return {"status": "ok", "services": report}


@app.get("/api/deep-health")
async def deep_health_check() -> dict[str, Any]:
    """Check connectivity to all external services."""
    checks: dict[str, Any] = {}

    immune = _services.get(SK.IMMUNE)
    if immune is not None:
        try:
            checks["core"] = await immune.run_startup_validation()
        except (IraError, Exception) as exc:
            checks["core"] = {"status": "error", "detail": str(exc)}

    redis_svc = _services.get(SK.REDIS)
    if redis_svc is not None:
        checks["redis"] = await redis_svc.health_check()

    gdocs_svc = _services.get(SK.GOOGLE_DOCS)
    if gdocs_svc is not None:
        checks["google_docs"] = await gdocs_svc.health_check()

    docai_svc = _services.get(SK.DOCUMENT_AI)
    if docai_svc is not None:
        checks["document_ai"] = await docai_svc.health_check()

    pdfco_svc = _services.get(SK.PDFCO)
    if pdfco_svc is not None:
        checks["pdfco"] = await pdfco_svc.health_check()

    dlp_svc = _services.get(SK.DLP)
    if dlp_svc is not None:
        checks["dlp"] = await dlp_svc.health_check()

    mem0_key = get_settings().memory.api_key.get_secret_value()
    if mem0_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.mem0.ai/v1/ping/",
                    headers={"Authorization": f"Token {mem0_key}"},
                )
                checks["mem0"] = {"status": "healthy" if resp.status_code < 400 else "degraded"}
        except (ConfigurationError, Exception) as exc:
            checks["mem0"] = {"status": "unhealthy", "detail": str(exc)}

    langfuse_cfg = get_settings().langfuse
    if langfuse_cfg.public_key and langfuse_cfg.secret_key.get_secret_value():
        try:
            import base64 as _b64
            token = _b64.b64encode(
                f"{langfuse_cfg.public_key}:{langfuse_cfg.secret_key.get_secret_value()}".encode()
            ).decode()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{langfuse_cfg.base_url.rstrip('/')}/api/public/health",
                    headers={"Authorization": f"Basic {token}"},
                )
                checks["langfuse"] = {"status": "healthy" if resp.status_code < 400 else "degraded"}
        except Exception as exc:
            checks["langfuse"] = {"status": "unhealthy", "detail": str(exc)}

    _OK_STATUSES = {"healthy", "ok", "connected"}

    def _is_ok(v: Any) -> bool:
        if not isinstance(v, dict):
            return True
        if "status" in v:
            return v["status"] in _OK_STATUSES
        return all(_is_ok(sub) for sub in v.values())

    all_healthy = all(_is_ok(v) for v in checks.values())
    return {"status": "ok" if all_healthy else "degraded", "services": checks}


@app.post("/api/llm/reset-breakers")
async def reset_llm_breakers() -> dict[str, str]:
    """Clear OpenAI and Anthropic circuit breakers so the next LLM request is attempted.
    Use after reloading the OpenAI wallet or when starting Ira so prior 429s don't block."""
    try:
        from ira.services.llm_client import reset_llm_circuit_breakers
        reset_llm_circuit_breakers()
        return {"status": "ok", "message": "Circuit breakers reset. Next LLM request will be attempted."}
    except Exception as exc:
        logger.exception("Reset LLM breakers failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/pipeline")
async def pipeline_summary() -> dict[str, Any]:
    """Return the CRM sales pipeline summary."""
    crm = _svc(SK.CRM)
    summary = await crm.get_pipeline_summary()
    return {"pipeline": summary}


@app.get("/api/pipeline/proposals-sent")
async def pipeline_proposals_sent() -> dict[str, Any]:
    """Return count and list of proposals/quotes sent (from quotes table + outbound interactions).

    Use this to correct the pipeline: deals in PROPOSAL stage may be fewer than
    actual proposals sent (email/quote records).
    """
    from ira.data.models import Direction
    from ira.data.quotes import QuoteStatus

    crm = _svc(SK.CRM)
    quotes = _services.get(SK.QUOTES)
    out: dict[str, Any] = {"by_quotes_table": [], "by_outbound_email": [], "total_proposals_sent": 0}
    sent_quote_count = 0
    if quotes is not None:
        try:
            sent_quotes = await quotes.list_quotes(filters={"status": QuoteStatus.SENT})
            sent_quote_count = len(sent_quotes)
            for q in sent_quotes:
                out["by_quotes_table"].append({
                    "company": q.company_name,
                    "machine_model": q.machine_model,
                    "estimated_value": float(q.estimated_value) if q.estimated_value else None,
                    "sent_at": q.sent_at.isoformat() if q.sent_at else None,
                })
        except Exception as e:
            logger.warning("List quotes SENT failed: %s", e)
    outbound_proposal_count = 0
    if crm is not None:
        try:
            outbound = await crm.list_interactions(
                filters={"direction": Direction.OUTBOUND},
                limit=500,
            )
            for i in outbound:
                subj = (i.subject or "").lower()
                if "proposal" in subj or "quote" in subj or "quotation" in subj:
                    outbound_proposal_count += 1
                    contact = await crm.get_contact(str(i.contact_id)) if i.contact_id else None
                    cdict = contact.to_dict() if contact else {}
                    out["by_outbound_email"].append({
                        "subject": (i.subject or "")[:120],
                        "company": cdict.get("company_name"),
                        "contact_email": cdict.get("email"),
                        "created_at": i.created_at.isoformat() if i.created_at else None,
                    })
        except Exception as e:
            logger.warning("List outbound for proposals failed: %s", e)
    out["total_proposals_sent"] = sent_quote_count + len(out["by_outbound_email"])
    out["quotes_sent_count"] = sent_quote_count
    out["outbound_proposal_email_count"] = len(out["by_outbound_email"])
    return out


@app.get("/api/crm/list")
async def crm_list(limit: int = 200) -> dict[str, Any]:
    """Return CRM list: deals with contact and company for Command Center."""
    crm = _svc(SK.CRM)
    deals = await crm.list_deals_with_details(limit=limit)
    return {"deals": deals, "count": len(deals)}


class SyncApolloRequest(BaseModel):
    """Optional body for POST /api/crm/sync-apollo."""

    dry_run: bool = False
    limit: int | None = None
    contact_type: str | None = None
    contacts_only: bool = False


@app.post("/api/crm/sync-apollo")
async def crm_sync_apollo(body: SyncApolloRequest | None = None) -> dict[str, Any]:
    """Sync CRM with Apollo.io: enrich contacts (role, LinkedIn) and companies (industry, website, employees, region).

    Uses Apollo credits. Requires APOLLO_API_KEY in .env. Optional body: dry_run, limit, contact_type, contacts_only.
    """
    opts = body or SyncApolloRequest()
    crm = _svc(SK.CRM)
    from ira.systems.apollo_crm_sync import sync_crm_with_apollo

    result = await sync_crm_with_apollo(
        crm,
        dry_run=opts.dry_run,
        limit=opts.limit,
        contact_type=opts.contact_type,
        contacts_only=opts.contacts_only,
    )
    return result


@app.get("/api/deals")
async def deals_list(
    limit: int = 200,
    sort: str = "heat_desc",
) -> dict[str, Any]:
    """Return deals with heat score (hottest = quote sent + customer replied). sort: heat_desc (hottest first) or heat_asc (least hot)."""
    crm = _svc(SK.CRM)
    sort_heat = "desc" if sort == "heat_desc" else "asc"
    deals = await crm.list_deals_with_heat(limit=limit, sort_heat=sort_heat)
    return {"deals": deals, "count": len(deals)}


@app.get("/api/deals/ranked")
async def deals_ranked(
    limit: int = 200,
    sort_by_score: str = "desc",
    engagement_only: bool = True,
) -> dict[str, Any]:
    """Return deals with 0–100 lead score (order size, interest, stage, existing customer, meeting/web call).
    Sorted by lead_score descending by default. Formula: data/knowledge/lead_ranker_formula.md.
    engagement_only=True (default): only include leads who have replied at least once; excludes list-import / no-thread records."""
    crm = _svc(SK.CRM)
    deals = await crm.list_deals_with_lead_score(
        limit=limit, sort_by_score=sort_by_score, engagement_only=engagement_only
    )
    return {"deals": deals, "count": len(deals)}


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    """List all Pantheon agents with optional power level and tool success rate."""
    pantheon = _svc(SK.PANTHEON)
    leaderboard_map: dict[str, dict[str, Any]] = {}
    tool_rate_map: dict[str, float] = {}

    try:
        tracker = _services.get(SK.POWER_LEVEL_TRACKER)
        if tracker is not None:
            leaderboard = tracker.get_leaderboard()
            for row in leaderboard:
                leaderboard_map[row["agent"]] = {
                    "score": row["score"],
                    "tier": row["tier"],
                    "successes": row.get("successes", 0),
                    "failures": row.get("failures", 0),
                }
    except Exception:
        logger.debug("Power levels unavailable for /api/agents", exc_info=True)

    try:
        tool_tracker = _services.get("tool_stats_tracker")
        if tool_tracker is not None:
            rates = await tool_tracker.get_tool_success_rates(by_tool=False)
            for row in rates:
                tool_rate_map[row["agent"]] = row["rate"]
    except Exception:
        logger.debug("Tool stats unavailable for /api/agents", exc_info=True)

    agents = []
    for agent in pantheon.agents.values():
        entry: dict[str, Any] = {
            "name": agent.name,
            "role": getattr(agent, "role", ""),
            "description": getattr(agent, "description", ""),
        }
        if agent.name in leaderboard_map:
            entry["power_level"] = leaderboard_map[agent.name]["score"]
            entry["tier"] = leaderboard_map[agent.name]["tier"]
        if agent.name in tool_rate_map:
            entry["tool_success_rate"] = tool_rate_map[agent.name]
        agents.append(entry)

    return {"agents": agents, "count": len(agents)}


@app.get("/api/endocrine")
async def endocrine_status() -> dict[str, Any]:
    """Return current hormone levels from the EndocrineSystem (for Command Center)."""
    endocrine = _services.get("endocrine")
    if endocrine is None:
        raise HTTPException(status_code=503, detail="Endocrine system not available")
    return endocrine.get_status()


@app.get("/api/pipeline/timings")
async def pipeline_timings(limit: int = 24) -> dict[str, Any]:
    """Return recent pipeline run stage timings (for Command Center ticker)."""
    pipeline = _services.get("pipeline")
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not available")
    timings = pipeline.get_recent_stage_timings(limit)
    return {"timings": timings}


@app.get("/api/terminal/metrics")
async def terminal_metrics() -> dict[str, Any]:
    """Aggregated metrics for Command Center: pipeline, campaigns, stale leads, recent interactions."""
    crm = _svc(SK.CRM)
    pipeline = await crm.get_pipeline_summary()
    campaigns = await crm.list_campaigns(filters={"status": "ACTIVE"})
    stale_leads = await crm.get_stale_leads(days=14)
    interactions = await crm.list_interactions(limit=5)
    recent = [
        {
            "id": str(ix.id),
            "created_at": ix.created_at.isoformat() if ix.created_at else None,
            "channel": ix.channel,
            "direction": ix.direction.value if hasattr(ix.direction, "value") else str(ix.direction),
            "contact_id": str(ix.contact_id) if ix.contact_id else None,
        }
        for ix in interactions
    ]
    return {
        "pipeline": pipeline,
        "active_campaigns": len(campaigns),
        "stale_leads": stale_leads,
        "recent_interactions": recent,
    }


@app.websocket("/api/ws/stream")
async def ws_event_stream(websocket: WebSocket) -> None:
    """Stream DataEventBus events to Command Center clients in real time."""
    await websocket.accept()
    _ws_connections.add(websocket)
    try:
        circulatory = _services.get(SK.CIRCULATORY)
        if circulatory is not None:
            recent = circulatory.recent_events(50)
            for evt in recent:
                try:
                    await websocket.send_json({
                        "ts": evt.get("timestamp", ""),
                        "type": evt.get("event_type", ""),
                        "entity_type": evt.get("entity_type", ""),
                        "entity_id": evt.get("entity_id", ""),
                        "source_store": evt.get("source_store", ""),
                        "payload_keys": evt.get("payload_keys", []),
                    })
                except Exception:
                    break
        while True:
            await websocket.receive_text()
    except Exception:
        logger.debug("WebSocket stream closed", exc_info=True)
    finally:
        _ws_connections.discard(websocket)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = frozenset({".txt", ".pdf", ".docx", ".xlsx", ".csv", ".json", ".md"})


@app.post("/api/ingest")
async def ingest_file(file: UploadFile) -> dict[str, Any]:
    """Upload a document for ingestion through the DigestiveSystem."""
    filename = os.path.basename(file.filename or "upload")
    if ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ext = os.path.splitext(filename)[1].lower()
    if ext and ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content)} bytes). Maximum: {_MAX_UPLOAD_BYTES} bytes",
        )

    digestive = _svc(SK.DIGESTIVE)
    text = content.decode("utf-8", errors="replace")
    result = await digestive.ingest(
        raw_data=text,
        source=filename,
        source_category="document_upload",
    )

    # Persist to data/imports/ so Alexandros's metadata index stays current
    imports_dir = Path("data/imports")
    try:
        await asyncio.to_thread(imports_dir.mkdir, parents=True, exist_ok=True)
        dest = imports_dir / filename
        if dest.exists():
            stem, ext_part = os.path.splitext(filename)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            dest = imports_dir / f"{stem}_{ts}{ext_part}"
        await asyncio.to_thread(dest.write_bytes, content)

        async def _background_index() -> None:
            try:
                from ira.brain.imports_metadata_index import build_index
                await build_index(use_llm=True, force=False)
            except Exception:
                logger.warning("Background build_index failed", exc_info=True)

        asyncio.create_task(_background_index())
    except Exception:
        logger.warning("Failed to save %s to imports or trigger index", filename, exc_info=True)

    return {
        "filename": filename,
        "chunks_created": result.get("chunks_created", 0),
        "entities_found": result.get("entities_found", {}),
    }


class ReingestRequest(BaseModel):
    min_file_size_mb: int = 5
    base_path: str = "data/imports"
    min_chars_per_page: int = 25


_reingest_status: dict[str, Any] = {"running": False, "last_result": None}
_reingest_lock = asyncio.Lock()


@app.post("/api/reingest-scanned")
async def reingest_scanned(req: ReingestRequest | None = None) -> dict[str, Any]:
    """Re-ingest scanned PDFs through Document AI OCR.

    Launches as a background task and returns immediately.
    Poll ``GET /api/reingest-scanned`` for status.
    """
    async with _reingest_lock:
        if _reingest_status["running"]:
            return {"status": "already_running", "message": "Re-ingestion is already in progress."}
        _reingest_status["running"] = True
        _reingest_status["last_result"] = None

    ingestor = _svc("ingestor")
    params = req or ReingestRequest()
    min_bytes = params.min_file_size_mb * 1024 * 1024

    async def _run() -> None:
        try:
            summary = await ingestor.reingest_scanned_pdfs(
                base_path=params.base_path,
                min_file_size=min_bytes,
                min_chars_per_page=params.min_chars_per_page,
            )
            _reingest_status["last_result"] = summary
            logger.info("Scanned PDF re-ingestion complete: %s", summary)
        except Exception:
            logger.exception("Scanned PDF re-ingestion failed")
            _reingest_status["last_result"] = {"error": "Re-ingestion failed — check server logs."}
        finally:
            _reingest_status["running"] = False

    asyncio.create_task(_run())
    return {"status": "started", "message": "Re-ingestion launched in background. Poll GET /api/reingest-scanned for status."}


@app.get("/api/reingest-scanned")
async def reingest_scanned_status() -> dict[str, Any]:
    """Check the status of the scanned PDF re-ingestion."""
    return {
        "running": _reingest_status["running"],
        "last_result": _reingest_status["last_result"],
    }


@app.post("/api/board-meeting")
async def board_meeting(req: BoardMeetingRequest) -> dict[str, Any]:
    """Run a board meeting and return the minutes."""
    bm = _svc("board_meeting")
    minutes = await bm.run_meeting(req.topic, req.participants)
    return {
        "topic": minutes.topic,
        "participants": minutes.participants,
        "contributions": minutes.contributions,
        "synthesis": minutes.synthesis,
        "action_items": minutes.action_items,
    }


@app.get("/api/journal")
async def journal_only(
    since_last: bool = True,
    last_24h: bool = False,
) -> dict[str, Any]:
    """Run journal only (no dream cycle). since_last=true journals from each agent's last entry till now.
    last_24h=true uses last 24 hours instead."""
    dm = _svc(SK.DREAM_MODE)
    result = await dm.run_journal_only(
        since_last_journal=since_last and not last_24h,
        lookback_hours=24.0 if last_24h else 168.0,
    )
    return result


@app.get("/api/dream-report")
async def dream_report(
    journal_last_24h: bool = False,
) -> dict[str, Any]:
    """Trigger a dream cycle and return the report.
    Set journal_last_24h=true to journal agent actions from the last 24 hours."""
    dm = _svc(SK.DREAM_MODE)
    report = await dm.run_dream_cycle(journal_last_24h=journal_last_24h)
    return {
        "cycle_date": str(report.cycle_date),
        "memories_consolidated": report.memories_consolidated,
        "gaps_identified": report.gaps_identified,
        "creative_connections": report.creative_connections,
        "campaign_insights": report.campaign_insights,
        "stage_results": report.stage_results,
    }


@app.get("/api/memory/recall")
async def memory_recall(
    query: str,
    user_id: str = "global",
    limit: int = 5,
) -> dict[str, Any]:
    """Recall long-term memories (Mem0) for a given query and optional user_id (e.g. contact email).
    Use when assembling context for lead email drafts so the draft is data-driven from past interactions."""
    mem = _svc(SK.LONG_TERM_MEMORY)
    if mem is None:
        return {"memories": [], "source": "none"}
    results = await mem.search(query=query, user_id=user_id, limit=limit)
    memories = [
        m.get("memory", m.get("content", ""))
        for m in results
        if m.get("memory") or m.get("content")
    ]
    return {"memories": memories, "source": "mem0"}


class MemoryStoreRequest(BaseModel):
    content: str
    user_id: str = "global"
    metadata: dict[str, Any] | None = None


@app.post("/api/memory/store")
async def memory_store(req: MemoryStoreRequest) -> dict[str, Any]:
    """Store a long-term memory (Mem0). Use for master updates e.g. contact quote summary."""
    mem = _svc(SK.LONG_TERM_MEMORY)
    if mem is None:
        return {"stored": False, "detail": "Mem0 not configured"}
    result = await mem.store(
        content=req.content,
        user_id=req.user_id,
        metadata=req.metadata,
    )
    return {"stored": True, "result": result}


@app.post("/api/email/search")
async def email_search(req: EmailSearchRequest) -> dict[str, Any]:
    """Search Gmail using native query filters (from, subject, date, etc.)."""
    ep = _svc(SK.EMAIL_PROCESSOR)
    try:
        emails = await ep.search_emails(
            from_address=req.from_address,
            to_address=req.to_address,
            subject=req.subject,
            label=req.label,
            query=req.query,
            after=req.after,
            before=req.before,
            max_results=req.max_results,
        )
    except IraError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("Gmail search failed")
        raise HTTPException(
            status_code=503,
            detail=f"Gmail search unavailable: {e}",
        ) from e
    return {
        "count": len(emails),
        "emails": [
            {
                "id": e.id,
                "thread_id": e.thread_id,
                "from": e.from_address,
                "to": e.to_address,
                "subject": e.subject,
                "date": e.received_at.isoformat(),
                "body": e.body[:2000],
            }
            for e in emails
        ],
    }


@app.get("/api/email/thread/{thread_id}/with-attachments")
async def email_thread_with_attachments(
    thread_id: str,
    max_attachment_chars: int = 50000,
    save_to_dir: str | None = None,
    from_email: str | None = None,
) -> dict[str, Any]:
    """Fetch thread and extract text from PDF/DOCX attachments (e.g. CVs).

    If save_to_dir and from_email are set, PDF/DOCX attachments are also written
    to save_to_dir / sanitized(from_email) / filename (resolved relative to cwd).
    """
    ep = _svc(SK.EMAIL_PROCESSOR)
    save_path: Path | None = None
    if save_to_dir and from_email:
        save_path = Path(save_to_dir).resolve()
    try:
        messages = await ep.get_thread_with_attachment_text(
            thread_id,
            max_attachment_chars=max_attachment_chars,
            save_attachments_under=save_path,
            from_address=from_email if save_path else None,
        )
    except IraError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("Gmail thread with attachments failed for %s", thread_id)
        raise HTTPException(
            status_code=503,
            detail=f"Gmail thread unavailable: {e}",
        ) from e
    return {
        "thread_id": thread_id,
        "message_count": len(messages),
        "messages": [
            {
                "id": m["id"],
                "from": m["from_address"],
                "to": m["to_address"],
                "subject": m["subject"],
                "date": m["received_at"],
                "body": m["body"],
                "attachment_texts": m.get("attachment_texts", []),
            }
            for m in messages
        ],
    }


@app.get("/api/email/thread/{thread_id}")
async def email_thread(thread_id: str) -> dict[str, Any]:
    """Fetch a full email thread by its Gmail thread ID."""
    ep = _svc(SK.EMAIL_PROCESSOR)
    try:
        emails = await ep.get_thread(thread_id)
    except IraError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("Gmail get_thread failed for %s", thread_id)
        raise HTTPException(
            status_code=503,
            detail=f"Gmail thread unavailable: {e}",
        ) from e
    return {
        "thread_id": thread_id,
        "message_count": len(emails),
        "messages": [
            {
                "id": e.id,
                "from": e.from_address,
                "to": e.to_address,
                "subject": e.subject,
                "date": e.received_at.isoformat(),
                "body": e.body,
            }
            for e in emails
        ],
    }


@app.post("/api/email/draft")
async def email_draft(req: EmailDraftRequest) -> dict[str, Any]:
    """Generate an email draft via Calliope."""
    pantheon = _svc(SK.PANTHEON)
    calliope = pantheon.get_agent("calliope")
    if calliope is None:
        raise HTTPException(status_code=503, detail="Calliope agent not available")

    body = await calliope.handle(
        req.context,
        {"draft_type": "email", "recipient": req.to, "tone": req.tone},
    )
    return {
        "to": req.to,
        "subject": req.subject,
        "body": body,
    }


@app.post("/api/email/create-draft")
async def email_create_draft(req: EmailSendRequest) -> dict[str, Any]:
    """Create a Gmail draft (no send). User can open Gmail and send from their mailbox.

    Works in any IRA_EMAIL_MODE. Does not require OPERATIONAL.
    """
    ep = _svc(SK.EMAIL_PROCESSOR)
    if ep is None:
        raise HTTPException(status_code=503, detail="Email processor not available")
    try:
        result = await ep.create_draft(
            to=req.to,
            subject=req.subject,
            body=req.body,
            cc=req.cc,
            thread_id=req.thread_id,
        )
        return {
            "created": True,
            "draft_id": result.get("id"),
            "message_id": result.get("message", {}).get("id"),
        }
    except IraError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/email/send")
async def email_send(req: EmailSendRequest) -> dict[str, Any]:
    """Send an email via Gmail. Only call when the user explicitly said 'send'.

    Explicit user send is allowed in any IRA_EMAIL_MODE (script or UI Send).
    Logs the outbound email to CRM interactions so the CRM agent has full context.
    """
    from email.utils import parseaddr

    ep = _svc(SK.EMAIL_PROCESSOR)
    if ep is None:
        raise HTTPException(status_code=503, detail="Email processor not available")
    try:
        result = await ep.send_message(
            to=req.to,
            subject=req.subject,
            body=req.body,
            cc=req.cc,
            thread_id=req.thread_id,
            user_initiated=True,
        )
        # Log outbound email to CRM so CRM agent has full history (what was sent, when)
        crm = _svc(SK.CRM)
        if crm is not None:
            try:
                to_email = (parseaddr(req.to)[1] or req.to).strip().lower()
                if to_email and "@" in to_email:
                    contact = await crm.get_contact_by_email(to_email)
                    if contact is not None:
                        from ira.data.models import Channel, Direction
                        await crm.create_interaction(
                            contact_id=str(contact.id),
                            channel=Channel.EMAIL,
                            direction=Direction.OUTBOUND,
                            subject=req.subject,
                            content=(req.body or "")[:4000],
                        )
                        logger.info("Logged outbound email to CRM for contact %s", to_email)
            except Exception as log_exc:
                logger.warning("Failed to log outbound email to CRM: %s", log_exc)
        result = result or {}
        return {
            "sent": True,
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
            "sent_from": result.get("sent_from"),
        }
    except IraError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Email send failed")
        raise HTTPException(
            status_code=502,
            detail=f"Email send failed: {exc!s}. Check Gmail token has send scopes and GOOGLE_IRA_EMAIL if set.",
        ) from exc


# ── Anu (AI Recruiter Agent) ───────────────────────────────────────────────

@app.get("/api/anu/candidates")
async def anu_list_candidates(
    limit: int = 100,
    offset: int = 0,
    role_applied: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """List applicant datasheets (recruitment database)."""
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    try:
        rows = await store.list_candidates(
            limit=limit, offset=offset, role_applied=role_applied, stage=stage
        )
        total = await store.count()
        return {"total": total, "candidates": rows}
    except Exception as e:
        logger.exception("Anu list candidates failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/anu/candidates/by-email")
async def anu_get_candidate(email: str) -> dict[str, Any]:
    """Get one applicant datasheet by email (for drafting replies via Rushabh's email)."""
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    try:
        c = await store.get_by_email(email)
        if c is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return c
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Anu get candidate failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.patch("/api/anu/candidates/by-email")
async def anu_update_candidate_cv_parsed(
    email: str,
    req: AnuCvParsedUpdateRequest,
) -> dict[str, Any]:
    """Store CV-parsed profile for a candidate (from Anu parse-resume-text)."""
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    try:
        await store.update_cv_parsed(email, req.candidate_profile)
        c = await store.get_by_email(email)
        if c is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return c
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Anu update cv_parsed failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── Recruitment database API (Anu backend) ───────────────────────────────────

@app.post("/api/recruitment/candidates")
async def recruitment_upsert_candidate(req: RecruitmentUpsertRequest) -> dict[str, Any]:
    """Upsert a candidate in the recruitment database (by email)."""
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    try:
        candidate = await store.upsert_candidate(
            req.email,
            name=req.name,
            phone=req.phone,
            role_applied=req.role_applied,
            profile=req.profile,
            cv_parsed=req.cv_parsed,
            score=req.score,
            ctc_current=req.ctc_current,
            source_type=req.source_type,
            source_id=req.source_id,
            notes=req.notes,
        )
        return candidate.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Recruitment upsert candidate failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/recruitment/candidates/by-email/events")
async def recruitment_add_stage_event(
    email: str,
    req: RecruitmentStageEventRequest,
) -> dict[str, Any]:
    """Record a stage event for a candidate (e.g. stage1_sent, stage2_replied, call_invited)."""
    from datetime import datetime
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    event_at = None
    if req.event_at:
        try:
            event_at = datetime.fromisoformat(req.event_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid event_at ISO datetime")
    try:
        event = await store.add_stage_event(
            email, req.stage, event_at=event_at, metadata=req.metadata
        )
        if event is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return event.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Recruitment add stage event failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.patch("/api/recruitment/candidates/by-email")
async def recruitment_update_candidate(
    email: str,
    req: RecruitmentCandidateUpdateRequest,
) -> dict[str, Any]:
    """Update candidate fields (ctc_current, notes, name, phone, role_applied)."""
    from ira.data.recruitment import RecruitmentStore
    store = RecruitmentStore()
    try:
        candidate = await store.upsert_candidate(
            email,
            ctc_current=req.ctc_current,
            notes=req.notes,
            name=req.name,
            phone=req.phone,
            role_applied=req.role_applied,
        )
        return candidate.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Recruitment update candidate failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/draft-recruitment-stage2")
async def anu_draft_recruitment_stage2(
    req: AnuDraftRecruitmentStage2Request,
) -> dict[str, Any]:
    """Draft Stage 2 recruitment email (subject + body) with case study, DICE, and skills questions."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")
    try:
        result = await anu.draft_recruitment_stage2(
            candidate_name=req.candidate_name,
            role=req.role,
            case_study_text=req.case_study_text,
            dice_questions=req.dice_questions,
            skills_questions=req.skills_questions,
            company_intro_short=req.company_intro_short,
            job_description_or_context=req.job_description_or_context,
        )
        return result
    except Exception as e:
        logger.exception("Anu draft-recruitment-stage2 failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/parse-resume")
async def anu_parse_resume(file: UploadFile) -> dict[str, Any]:
    """Parse a PDF resume into structured candidate profile (JSON)."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for resume parsing")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {_MAX_UPLOAD_BYTES} bytes)")

    try:
        profile = await anu.parse_resume_from_pdf_bytes(content)
        return {"candidate_profile": profile.model_dump()}
    except Exception as e:
        logger.exception("Anu parse-resume failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/parse-resume-text")
async def anu_parse_resume_text(req: AnuParseTextRequest) -> dict[str, Any]:
    """Parse plain resume text into structured candidate profile (JSON)."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")
    try:
        profile = await anu.parse_resume_from_text(req.resume_text)
        return {"candidate_profile": profile.model_dump()}
    except Exception as e:
        logger.exception("Anu parse-resume-text failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/score")
async def anu_score(req: AnuScoreRequest) -> dict[str, Any]:
    """Score a candidate (1-5) with optional job description."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")
    try:
        score = await anu.score_candidate(
            req.candidate_profile,
            job_description=req.job_description,
        )
        return {"score": score.model_dump()}
    except Exception as e:
        logger.exception("Anu score failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/chat")
async def anu_chat(req: AnuChatRequest) -> dict[str, Any]:
    """Mentor-style chat: reply given candidate profile and conversation history."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")
    try:
        reply = await anu.mentor_reply(
            req.candidate_profile,
            message=req.message,
            conversation_history=req.conversation_history,
        )
        return {"reply": reply}
    except Exception as e:
        logger.exception("Anu chat failed")
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/anu/export")
async def anu_export(req: AnuExportRequest):
    """Generate profile summary; optionally return as PDF."""
    pantheon = _svc(SK.PANTHEON)
    anu = pantheon.get_agent("anu") if pantheon else None
    if anu is None:
        raise HTTPException(status_code=503, detail="Anu agent not available")

    try:
        summary = await anu.generate_profile_summary(
            req.candidate_profile,
            scoring=req.scoring,
        )
    except Exception as e:
        logger.exception("Anu export summary failed")
        raise HTTPException(status_code=502, detail=str(e)) from e

    if (req.format or "text").lower() == "pdf":
        pdfco = _svc(SK.PDFCO)
        if pdfco is None or not getattr(pdfco, "available", False):
            return {"format": "text", "summary": summary}
        try:
            escaped = (summary or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = f"<html><body><pre style='font-family: sans-serif; white-space: pre-wrap;'>{escaped}</pre></body></html>"
            pdf_bytes = await pdfco.html_to_pdf(html, name="candidate_profile.pdf")
            from fastapi.responses import Response
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=candidate_profile.pdf"},
            )
        except Exception as e:
            logger.warning("PDF export failed, returning text: %s", e)
            return {"format": "text", "summary": summary}

    return {"format": "text", "summary": summary}


@app.post("/api/outbound/campaigns/draft")
async def outbound_campaign_draft(req: OutboundDraftBatchRequest) -> dict[str, Any]:
    """Queue outbound messages for explicit approval before Gmail draft creation."""
    approvals = _svc(SK.OUTBOUND_APPROVALS)
    from ira.systems.outbound_approvals import OutboundMessage

    batch = await approvals.create_batch(
        campaign_name=req.campaign_name,
        created_by=req.created_by,
        messages=[OutboundMessage(**m.model_dump()) for m in req.messages],
    )
    return {
        "status": "pending_approval",
        "batch_id": batch["batch_id"],
        "campaign_name": batch["campaign_name"],
        "message_count": len(batch["messages"]),
    }


@app.post("/api/outbound/campaigns/approve")
async def outbound_campaign_approve(req: OutboundApproveRequest) -> dict[str, Any]:
    """Approve a queued batch and create Gmail drafts (never direct-send)."""
    approvals = _svc(SK.OUTBOUND_APPROVALS)
    email_processor = _svc(SK.EMAIL_PROCESSOR)
    from ira.interfaces.email_processor import GmailDraftSender

    gmail_sender = GmailDraftSender(email_processor=email_processor)
    try:
        batch = await approvals.approve_batch(
            batch_id=req.batch_id,
            approved_by=req.approved_by,
            gmail_draft_sender=gmail_sender,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": batch["status"],
        "batch_id": batch["batch_id"],
        "approved_by": batch["approved_by"],
        "draft_count": len(batch.get("drafts", [])),
    }


# ── Email rescan endpoint ───────────────────────────────────────────────


class EmailRescanRequest(BaseModel):
    after: str = "2023/03/08"
    before: str = "2026/03/08"
    dry_run: bool = False
    resume: bool = False
    throttle: float = 0.1
    skip_crm_populate: bool = False
    user_id: str | None = None


_rescan_status: dict[str, Any] = {"running": False, "last_result": None}
_rescan_lock = asyncio.Lock()


@app.post("/api/email/rescan")
async def email_rescan_stream(req: EmailRescanRequest) -> EventSourceResponse:
    """Deep-scan historical Gmail and stream progress via SSE.

    Runs the full pipeline: paginated Gmail fetch, Delphi classification,
    DigestiveSystem protein extraction, Neo4j entity graph, CRM
    contact/deal creation, then CRM population.
    """
    async with _rescan_lock:
        if _rescan_status["running"]:
            raise HTTPException(status_code=409, detail="A rescan is already in progress")
        _rescan_status["running"] = True

    ep = _svc(SK.EMAIL_PROCESSOR)

    async def _event_generator() -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"event": "started", "data": _json.dumps({
                "after": req.after, "before": req.before,
                "dry_run": req.dry_run, "resume": req.resume,
            })}

            last_reported = {"processed": 0}

            def on_progress(processed: int, total: int, stats: dict) -> None:
                last_reported["processed"] = processed
                last_reported["total"] = total
                last_reported["stats"] = stats

            scan_task = asyncio.create_task(ep.deep_scan(
                after=req.after,
                before=req.before,
                throttle=req.throttle,
                resume=req.resume,
                dry_run=req.dry_run,
                progress_callback=on_progress,
            ))

            while not scan_task.done():
                await asyncio.sleep(2)
                yield {"event": "progress", "data": _json.dumps({
                    "phase": "scan",
                    "processed": last_reported.get("processed", 0),
                    "total_estimate": last_reported.get("total", 0),
                    **last_reported.get("stats", {}),
                })}

            scan_stats = await scan_task

            yield {"event": "scan_complete", "data": _json.dumps(scan_stats)}

            pop_result: dict[str, Any] | None = None
            if not req.skip_crm_populate:
                yield {"event": "progress", "data": _json.dumps({
                    "phase": "crm_populate", "message": "Classifying contacts...",
                })}

                from ira.systems.crm_populator import CRMPopulator

                crm = _svc(SK.CRM)
                pantheon = _svc(SK.PANTHEON)
                delphi = pantheon.get_agent("delphi")

                populator = CRMPopulator(
                    delphi=delphi, crm=crm, dry_run=req.dry_run,
                )
                pop_result = await populator.populate(
                    sources=["gmail", "kb", "neo4j"],
                    after=req.after,
                    before=req.before,
                )

                yield {"event": "crm_complete", "data": _json.dumps(pop_result["stats"])}

            # Phase 3: Generate 4-category intelligence report
            reports: dict[str, str] = {}
            if not req.dry_run:
                pipeline = _services.get("pipeline")
                if pipeline is not None:
                    unanswered = scan_stats.get("unanswered_inbound_threads", 0)
                    proposals = scan_stats.get("proposal_signals", 0)

                    report_queries = [
                        (
                            "customer_journeys",
                            "Search the CRM and knowledge base for all LIVE_CUSTOMER contacts. "
                            "For each customer: company name, contact person, how the relationship "
                            "started, conversation timeline, which machine(s) they bought (model, "
                            "specs), and deal value.",
                        ),
                        (
                            "delivered_machines",
                            "Search for customers with delivered machines or WON deals. For each: "
                            "company, machine model and specs, delivery date, price, and any open "
                            "support issues or complaints from email threads.",
                        ),
                        (
                            "hot_leads",
                            f"We found {proposals} proposal/quote signals. Search for deals at "
                            "PROPOSAL or NEGOTIATION stage and LEAD_WITH_INTERACTIONS contacts. "
                            "For each: company, machine quoted, price, when quote was sent, last "
                            "interaction date and content, days since last contact.",
                        ),
                        (
                            "missed_leads",
                            f"The scan detected {unanswered} unanswered inbound threads. Search "
                            "for LEAD_NO_INTERACTIONS contacts or contacts with only inbound "
                            "interactions. For each: who emailed, what they asked about, when, "
                            "and why this is a lost opportunity.",
                        ),
                    ]

                    for key, rq in report_queries:
                        yield {"event": "progress", "data": _json.dumps({
                            "phase": "report",
                            "report_section": key,
                            "message": f"Generating {key.replace('_', ' ')} report...",
                        })}
                        try:
                            text, _agents = await pipeline.process_request(
                                raw_input=rq,
                                channel="api",
                                sender_id=req.user_id or "rescan-report",
                            )
                            reports[key] = text
                            yield {"event": "report", "data": _json.dumps({
                                "section": key,
                                "report": text,
                            })}
                        except (IraError, Exception):
                            logger.warning("Report section %s failed", key, exc_info=True)

            final = {
                "scan": scan_stats,
                "crm": pop_result["stats"] if pop_result else None,
                "reports": reports or None,
            }
            _rescan_status["last_result"] = final
            yield {"event": "done", "data": _json.dumps(final)}

        except (IraError, Exception) as exc:
            logger.exception("Email rescan failed")
            yield {"event": "error", "data": _json.dumps({"error": str(exc)})}
        finally:
            _rescan_status["running"] = False

    return EventSourceResponse(_event_generator())


@app.get("/api/email/rescan")
async def email_rescan_status() -> dict[str, Any]:
    """Check the status of a running or last completed email rescan."""
    return {
        "running": _rescan_status["running"],
        "last_result": _rescan_status["last_result"],
    }


# ── Vendor / Procurement endpoints ──────────────────────────────────────


@app.get("/api/vendors")
async def list_vendors() -> dict[str, Any]:
    """List all vendors."""
    vdb = _svc(SK.VENDOR_DB)
    vendors = await vdb.list_vendors()
    return {"vendors": [v.to_dict() for v in vendors], "count": len(vendors)}


@app.post("/api/vendors")
async def create_vendor(req: dict[str, Any]) -> dict[str, Any]:
    """Create a new vendor."""
    vdb = _svc(SK.VENDOR_DB)
    vendor = await vdb.create_vendor(**req)
    return vendor.to_dict()


@app.get("/api/vendors/payables")
async def vendor_payables_summary() -> dict[str, Any]:
    """Get payables summary across all vendors."""
    vdb = _svc(SK.VENDOR_DB)
    summary = await vdb.get_payables_summary()
    overdue = await vdb.get_overdue_payables()
    return {"summary": summary, "overdue": overdue}


@app.get("/api/vendors/overdue")
async def overdue_payables() -> dict[str, Any]:
    """Get all overdue vendor payables."""
    vdb = _svc(SK.VENDOR_DB)
    overdue = await vdb.get_overdue_payables()
    return {"overdue": overdue, "count": len(overdue)}


@app.post("/api/vendors/payables")
async def create_payable(req: dict[str, Any]) -> dict[str, Any]:
    """Record a new vendor payable/invoice."""
    vdb = _svc(SK.VENDOR_DB)
    payable = await vdb.create_payable(**req)
    return payable.to_dict()


# ── Corrections endpoints ────────────────────────────────────────────────


@app.get("/api/corrections")
async def list_corrections(
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List recent corrections from the correction store."""
    store = _svc("correction_store")
    db = store._db
    if db is None:
        raise HTTPException(503, "Correction store not initialised")

    where = "WHERE status = ?" if status else ""
    params: tuple = (status,) if status else ()
    cursor = await db.execute(
        f"SELECT id, entity, category, severity, old_value, new_value, source, created_at, status "
        f"FROM corrections {where} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    corrections = [
        {
            "id": r[0], "entity": r[1], "category": r[2], "severity": r[3],
            "old_value": r[4], "new_value": r[5], "source": r[6],
            "created_at": r[7], "status": r[8],
        }
        for r in rows
    ]
    stats = await store.get_stats()
    return {"corrections": corrections, "count": len(corrections), "stats": stats}


# ── Task orchestration endpoints ─────────────────────────────────────────


@app.post("/api/task/stream")
async def task_stream(req: TaskRequest) -> EventSourceResponse:
    """Start a multi-phase task and stream progress via SSE.

    Emits events: ``task_created``, ``clarity_checking``,
    ``clarification_needed``, ``plan_created``, ``phase_started``,
    ``phase_done``, ``report_generating``, ``report_ready``,
    ``task_complete``, and ``task_error``.

    If clarification is needed the stream ends after the
    ``clarification_needed`` event.  Resume via ``/api/task/clarify``.
    """
    orchestrator = _svc("task_orchestrator")

    async def _event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        event_seq = 0

        async def _on_progress(event: dict[str, Any]) -> None:
            await orchestrator.append_task_event(task_id, _normalize_task_event(event))
            await queue.put(event)

        task_id = await orchestrator.create_task(
            goal=req.goal,
            user_id=req.user_id,
            output_format=req.output_format,
        )

        async def _run() -> Any:
            return await orchestrator.run_task(task_id, on_progress=_on_progress)

        task = asyncio.create_task(_run())

        while not task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                payload = _normalize_task_event(event)
                event_seq += 1
                yield {
                    "id": str(event_seq),
                    "event": payload.get("type", "progress"),
                    "data": _json.dumps(payload, default=str),
                }
            except asyncio.TimeoutError:
                continue

        while not queue.empty():
            event = queue.get_nowait()
            payload = _normalize_task_event(event)
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": payload.get("type", "progress"),
                "data": _json.dumps(payload, default=str),
            }

        try:
            result = task.result()
            await orchestrator.append_task_event(
                task_id,
                _normalize_task_event(
                    {
                        "type": "task_result",
                        "task_id": result.task_id,
                        "status": result.status,
                        "summary": result.summary,
                        "file_path": result.file_path,
                        "file_format": result.file_format,
                        "clarification_questions": result.clarification_questions,
                    }
                ),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_result",
                "data": _json.dumps({
                    "task_id": result.task_id,
                    "status": result.status,
                    "summary": result.summary,
                    "file_path": result.file_path,
                    "file_format": result.file_format,
                    "clarification_questions": result.clarification_questions,
                }, default=str),
            }
        except Exception as exc:
            logger.exception("Task stream failed")
            await orchestrator.append_task_event(
                task_id,
                _normalize_task_event({"type": "task_error", "error": str(exc)}),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_error",
                "data": _json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(_event_generator())


@app.post("/api/task/clarify")
async def task_clarify(req: TaskClarificationRequest) -> EventSourceResponse:
    """Resume a task with a clarification answer, streaming progress via SSE.

    Call this after receiving a ``clarification_needed`` event from
    ``/api/task/stream``.  Pass the ``task_id`` and the user's answer.
    """
    orchestrator = _svc("task_orchestrator")

    async def _event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        event_seq = 0

        async def _on_progress(event: dict[str, Any]) -> None:
            await orchestrator.append_task_event(req.task_id, _normalize_task_event(event))
            await queue.put(event)

        async def _run() -> Any:
            return await orchestrator.resume_with_clarification(
                task_id=req.task_id,
                answer=req.answer,
                on_progress=_on_progress,
            )

        task = asyncio.create_task(_run())

        while not task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                payload = _normalize_task_event(event)
                event_seq += 1
                yield {
                    "id": str(event_seq),
                    "event": payload.get("type", "progress"),
                    "data": _json.dumps(payload, default=str),
                }
            except asyncio.TimeoutError:
                continue

        while not queue.empty():
            event = queue.get_nowait()
            payload = _normalize_task_event(event)
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": payload.get("type", "progress"),
                "data": _json.dumps(payload, default=str),
            }

        try:
            result = task.result()
            await orchestrator.append_task_event(
                req.task_id,
                _normalize_task_event(
                    {
                        "type": "task_result",
                        "task_id": result.task_id,
                        "status": result.status,
                        "summary": result.summary,
                        "file_path": result.file_path,
                        "file_format": result.file_format,
                    }
                ),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_result",
                "data": _json.dumps({
                    "task_id": result.task_id,
                    "status": result.status,
                    "summary": result.summary,
                    "file_path": result.file_path,
                    "file_format": result.file_format,
                }, default=str),
            }
        except Exception as exc:
            logger.exception("Task clarify stream failed")
            await orchestrator.append_task_event(
                req.task_id,
                _normalize_task_event({"type": "task_error", "error": str(exc)}),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_error",
                "data": _json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(_event_generator())


@app.get("/api/task/{task_id}")
async def task_status(task_id: str) -> dict[str, Any]:
    """Return current persisted task state."""
    orchestrator = _svc("task_orchestrator")
    state = await orchestrator.get_task_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return state


@app.get("/api/tasks")
async def task_list(limit: int = 20) -> dict[str, Any]:
    """List recent tasks for operator visibility."""
    orchestrator = _svc("task_orchestrator")
    tasks = await orchestrator.list_tasks(limit=limit)
    return {"count": len(tasks), "tasks": tasks}


@app.get("/api/task/{task_id}/events")
async def task_events(task_id: str, limit: int = 200) -> dict[str, Any]:
    """Return recent persisted events for a task."""
    orchestrator = _svc("task_orchestrator")
    state = await orchestrator.get_task_state(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    events = await orchestrator.get_task_events(task_id, limit=limit)
    return {"task_id": task_id, "count": len(events), "events": events}


@app.post("/api/task/abort")
async def task_abort(req: TaskAbortRequest) -> dict[str, Any]:
    """Request cancellation of an in-flight task."""
    orchestrator = _svc("task_orchestrator")
    ok = await orchestrator.abort_task(req.task_id, reason=req.reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Task '{req.task_id}' not found")
    return {"task_id": req.task_id, "status": "aborting", "reason": req.reason}


@app.post("/api/task/retry/stream")
async def task_retry_stream(req: TaskRetryRequest) -> EventSourceResponse:
    """Retry a prior task from a specific phase, streaming progress via SSE."""
    orchestrator = _svc("task_orchestrator")
    state = await orchestrator.get_task_state(req.task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Task '{req.task_id}' not found")

    async def _event_generator() -> AsyncIterator[dict[str, str]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        event_seq = 0

        async def _on_progress(event: dict[str, Any]) -> None:
            await orchestrator.append_task_event(req.task_id, _normalize_task_event(event))
            await queue.put(event)

        async def _run() -> Any:
            return await orchestrator.retry_task(
                task_id=req.task_id,
                from_phase=req.from_phase,
                on_progress=_on_progress,
            )

        task = asyncio.create_task(_run())

        while not task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                payload = _normalize_task_event(event)
                event_seq += 1
                yield {
                    "id": str(event_seq),
                    "event": payload.get("type", "progress"),
                    "data": _json.dumps(payload, default=str),
                }
            except asyncio.TimeoutError:
                continue

        while not queue.empty():
            event = queue.get_nowait()
            payload = _normalize_task_event(event)
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": payload.get("type", "progress"),
                "data": _json.dumps(payload, default=str),
            }

        try:
            result = task.result()
            await orchestrator.append_task_event(
                req.task_id,
                _normalize_task_event(
                    {
                        "type": "task_result",
                        "task_id": result.task_id,
                        "status": result.status,
                        "summary": result.summary,
                        "file_path": result.file_path,
                        "file_format": result.file_format,
                    }
                ),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_result",
                "data": _json.dumps({
                    "task_id": result.task_id,
                    "status": result.status,
                    "summary": result.summary,
                    "file_path": result.file_path,
                    "file_format": result.file_format,
                }, default=str),
            }
        except Exception as exc:
            logger.exception("Task retry stream failed")
            await orchestrator.append_task_event(
                req.task_id,
                _normalize_task_event({"type": "task_error", "error": str(exc)}),
            )
            event_seq += 1
            yield {
                "id": str(event_seq),
                "event": "task_error",
                "data": _json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(_event_generator())
