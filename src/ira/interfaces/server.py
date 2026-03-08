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

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ira.middleware.auth import require_api_key
from ira.middleware.request_context import RequestContextMiddleware, RequestIdFilter

from ira.config import get_settings
from ira.exceptions import ConfigurationError, IraError
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
    query: str = ""
    after: str = ""
    before: str = ""
    max_results: int = 10


class EmailDraftRequest(BaseModel):
    to: str
    subject: str
    context: str
    tone: str = "professional"


class TaskRequest(BaseModel):
    goal: str
    user_id: str | None = None
    output_format: str = "markdown"


class TaskClarificationRequest(BaseModel):
    task_id: str
    answer: str
    user_id: str | None = None


# ── Service registry ──────────────────────────────────────────────────────
#
# Populated during the lifespan startup phase and cleared on shutdown.
# Endpoints access services through this dict rather than globals.

_services: dict[str, Any] = {}


def _svc(name: str) -> Any:
    """Retrieve a service by name; raise 503 if not yet initialised."""
    svc = _services.get(name)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"Service '{name}' not available")
    return svc


# ── Lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap all Ira subsystems on startup, tear down on shutdown."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.app.log_level, logging.INFO),
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  [%(request_id)s]  %(message)s",
        datefmt="%H:%M:%S",
    )
    for handler in logging.root.handlers:
        handler.addFilter(RequestIdFilter())

    # ── Redis ─────────────────────────────────────────────────────────
    from ira.systems.redis_cache import RedisCache

    redis_cache = RedisCache()
    await redis_cache.connect()
    _services[SK.REDIS] = redis_cache

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
    qdrant = QdrantManager(embedding_service=embedding)
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
    from ira.systems.data_event_bus import EventType

    correction_learner = CorrectionLearner()
    data_event_bus.subscribe(EventType.KNOWLEDGE_CORRECTED, correction_learner.on_knowledge_corrected)

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

    _services["procedural_memory"] = procedural_memory
    _services["learning_hub"] = learning_hub

    # ── Feedback handler ─────────────────────────────────────────────
    from ira.brain.correction_store import CorrectionStore
    from ira.brain.feedback_handler import FeedbackHandler

    correction_store = CorrectionStore()
    await _safe_init("correction_store", correction_store.initialize())

    feedback_handler = FeedbackHandler(
        learning_hub=learning_hub,
        correction_store=correction_store,
        mem0_client=mem0_client,
        procedural_memory=procedural_memory,
        data_event_bus=data_event_bus,
    )
    await feedback_handler.load_scores()

    _services["feedback_handler"] = feedback_handler
    _services["correction_store"] = correction_store

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
    })

    # ── Unified context ───────────────────────────────────────────────
    from ira.context import UnifiedContextManager

    unified_context = UnifiedContextManager()
    _services["unified_context"] = unified_context

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

    gmail_sender = GmailDraftSender(email_processor=email_processor)
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

    # ── Email polling background task ─────────────────────────────────
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

    for svc_name in (
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


# ── App ───────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Ira — Machinecraft AI Pantheon",
    version="3.2.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

_cors_raw = get_settings().app.cors_origins
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else ["*"]

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

    return EventSourceResponse(_event_generator())


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

    _OK_STATUSES = {"healthy", "ok", "connected"}

    def _is_ok(v: Any) -> bool:
        if not isinstance(v, dict):
            return True
        if "status" in v:
            return v["status"] in _OK_STATUSES
        return all(_is_ok(sub) for sub in v.values())

    all_healthy = all(_is_ok(v) for v in checks.values())
    return {"status": "ok" if all_healthy else "degraded", "services": checks}


@app.get("/api/pipeline")
async def pipeline_summary() -> dict[str, Any]:
    """Return the CRM sales pipeline summary."""
    crm = _svc(SK.CRM)
    summary = await crm.get_pipeline_summary()
    return {"pipeline": summary}


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    """List all Pantheon agents."""
    pantheon = _svc(SK.PANTHEON)
    agents = [
        {
            "name": agent.name,
            "role": getattr(agent, "role", ""),
            "description": getattr(agent, "description", ""),
        }
        for agent in pantheon.agents.values()
    ]
    return {"agents": agents, "count": len(agents)}


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


_reingest_status: dict[str, Any] = {"running": False, "last_result": None}


@app.post("/api/reingest-scanned")
async def reingest_scanned(req: ReingestRequest | None = None) -> dict[str, Any]:
    """Re-ingest scanned PDFs through Document AI OCR.

    Launches as a background task and returns immediately.
    Poll ``GET /api/reingest-scanned`` for status.
    """
    if _reingest_status["running"]:
        return {"status": "already_running", "message": "Re-ingestion is already in progress."}

    ingestor = _svc("ingestor")
    params = req or ReingestRequest()
    min_bytes = params.min_file_size_mb * 1024 * 1024

    async def _run() -> None:
        _reingest_status["running"] = True
        _reingest_status["last_result"] = None
        try:
            summary = await ingestor.reingest_scanned_pdfs(
                base_path=params.base_path,
                min_file_size=min_bytes,
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


@app.get("/api/dream-report")
async def dream_report() -> dict[str, Any]:
    """Trigger a dream cycle and return the report."""
    dm = _svc(SK.DREAM_MODE)
    report = await dm.run_dream_cycle()
    return {
        "cycle_date": str(report.cycle_date),
        "memories_consolidated": report.memories_consolidated,
        "gaps_identified": report.gaps_identified,
        "creative_connections": report.creative_connections,
        "campaign_insights": report.campaign_insights,
        "stage_results": report.stage_results,
    }


@app.post("/api/email/search")
async def email_search(req: EmailSearchRequest) -> dict[str, Any]:
    """Search Gmail using native query filters (from, subject, date, etc.)."""
    ep = _svc(SK.EMAIL_PROCESSOR)
    emails = await ep.search_emails(
        from_address=req.from_address,
        to_address=req.to_address,
        subject=req.subject,
        query=req.query,
        after=req.after,
        before=req.before,
        max_results=req.max_results,
    )
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


@app.get("/api/email/thread/{thread_id}")
async def email_thread(thread_id: str) -> dict[str, Any]:
    """Fetch a full email thread by its Gmail thread ID."""
    ep = _svc(SK.EMAIL_PROCESSOR)
    emails = await ep.get_thread(thread_id)
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


@app.post("/api/email/rescan")
async def email_rescan_stream(req: EmailRescanRequest) -> EventSourceResponse:
    """Deep-scan historical Gmail and stream progress via SSE.

    Runs the full pipeline: paginated Gmail fetch, Delphi classification,
    DigestiveSystem protein extraction, Neo4j entity graph, CRM
    contact/deal creation, then CRM population.
    """
    if _rescan_status["running"]:
        raise HTTPException(status_code=409, detail="A rescan is already in progress")

    ep = _svc(SK.EMAIL_PROCESSOR)

    async def _event_generator() -> AsyncIterator[dict[str, Any]]:
        _rescan_status["running"] = True
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

        async def _on_progress(event: dict[str, Any]) -> None:
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
            result = task.result()
            yield {
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
            yield {
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

        async def _on_progress(event: dict[str, Any]) -> None:
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
            result = task.result()
            yield {
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
            yield {
                "event": "task_error",
                "data": _json.dumps({"error": str(exc)}),
            }
