"""FastAPI server — main entry point for the Ira application.

Bootstraps every subsystem during startup, exposes REST endpoints for
querying, health, pipeline, ingestion, board meetings, dream reports,
and email drafting, then tears everything down gracefully on shutdown.

Run with::

    uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ira.middleware.auth import require_api_key
from ira.middleware.request_context import RequestContextMiddleware, RequestIdFilter

from ira.config import get_settings

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


class EmailDraftRequest(BaseModel):
    to: str
    subject: str
    context: str
    tone: str = "professional"


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
        except Exception:
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

    _services["crm"] = crm
    _services["quotes"] = quotes

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

    _services["data_event_bus"] = data_event_bus
    _services["circulatory"] = circulatory

    # ── Pricing engine ────────────────────────────────────────────────
    from ira.brain.pricing_engine import PricingEngine

    pricing_engine = PricingEngine(retriever=retriever, crm=crm)

    _services["pricing_engine"] = pricing_engine

    # ── Pantheon ──────────────────────────────────────────────────────
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon

    bus = MessageBus()
    pantheon = Pantheon(retriever=retriever, bus=bus)

    shared_services = {
        "crm": crm,
        "quotes": quotes,
        "pricing_engine": pricing_engine,
        "retriever": retriever,
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
        except Exception:
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

    dream_mode._procedural = procedural_memory

    _services["procedural_memory"] = procedural_memory
    _services["learning_hub"] = learning_hub

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
        "long_term_memory": long_term,
        "episodic_memory": episodic,
        "conversation_memory": conversation,
        "relationship_memory": relationship_memory,
        "goal_manager": goal_manager,
        "emotional_intelligence": emotional_intelligence,
        "procedural_memory": procedural_memory,
        "learning_hub": learning_hub,
        "data_event_bus": data_event_bus,
        "pantheon": pantheon,
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
    )
    _services["pipeline"] = request_pipeline

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
    email_poll_task = asyncio.create_task(email_processor.poll_inbox())
    logger.info(
        "Email polling started (mode=%s)", settings.google.email_mode.value,
    )

    # ── Immune startup validation ─────────────────────────────────────
    try:
        health_report = await immune.run_startup_validation()
        healthy = all(
            v.get("status") == "healthy" for v in health_report.values()
        )
        status = "ALL HEALTHY" if healthy else "DEGRADED"
        logger.info("Startup validation: %s — %s", status, list(health_report))
    except Exception:
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

    if email_poll_task is not None:
        email_poll_task.cancel()
        try:
            await email_poll_task
        except asyncio.CancelledError:
            pass

    await respiratory.stop()
    await data_event_bus.stop()
    await pantheon.stop()
    await sensory.close()
    await musculoskeletal.close()
    await graph.close()

    for svc_name in (
        "conversation", "episodic", "dream_mode", "emotional_intelligence",
        "relationship_memory", "goal_manager", "metacognition", "inner_voice",
        "procedural_memory",
    ):
        svc = _services.get(svc_name)
        if svc is not None and hasattr(svc, "close"):
            try:
                await svc.close()
            except Exception:
                logger.exception("Failed to close %s", svc_name)

    _services.clear()
    logger.info("All services shut down.")


# ── App ───────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Ira — Machinecraft AI Pantheon",
    version="3.0.0",
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
    respiratory = _services.get("respiratory")

    try:
        if respiratory is not None:
            async with respiratory.breath():
                response = await call_next(request)
        else:
            response = await call_next(request)
    except Exception as exc:
        immune = _services.get("immune")
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

    if pipeline is not None:
        response = await pipeline.process_request(
            raw_input=req.query,
            channel=channel,
            sender_id=sender_id,
            metadata=metadata,
        )
    else:
        pantheon = _svc("pantheon")
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

    return QueryResponse(response=response)


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    """Run the immune system health check."""
    immune = _svc("immune")
    try:
        report = await immune.run_startup_validation()
    except Exception as exc:
        report = getattr(exc, "health_report", {"error": str(exc)})
    return {"status": "ok", "services": report}


@app.get("/api/deep-health")
async def deep_health_check() -> dict[str, Any]:
    """Check connectivity to all external services."""
    checks: dict[str, Any] = {}

    immune = _services.get("immune")
    if immune is not None:
        try:
            checks["core"] = await immune.run_startup_validation()
        except Exception as exc:
            checks["core"] = {"status": "error", "detail": str(exc)}

    mem0_key = get_settings().memory.api_key.get_secret_value()
    if mem0_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.mem0.ai/v2/memories/search/",
                    json={"query": "health", "user_id": "health_check"},
                    headers={"Authorization": f"Token {mem0_key}"},
                )
                checks["mem0"] = {"status": "healthy" if resp.status_code < 400 else "degraded"}
        except Exception as exc:
            checks["mem0"] = {"status": "unhealthy", "detail": str(exc)}

    all_healthy = all(
        (v.get("status") in ("healthy", "ok") if isinstance(v, dict) else True)
        for v in checks.values()
    )
    return {"status": "ok" if all_healthy else "degraded", "services": checks}


@app.get("/api/pipeline")
async def pipeline_summary() -> dict[str, Any]:
    """Return the CRM sales pipeline summary."""
    crm = _svc("crm")
    summary = await crm.get_pipeline_summary()
    return {"pipeline": summary}


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    """List all Pantheon agents."""
    pantheon = _svc("pantheon")
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
    import os

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

    digestive = _svc("digestive")
    text = content.decode("utf-8", errors="replace")
    result = await digestive.ingest(
        raw_data=text,
        source=filename,
        source_category="document_upload",
    )
    return {
        "filename": filename,
        "chunks_created": result.get("chunks_created", 0),
        "entities_found": result.get("entities_found", {}),
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
    dm = _svc("dream_mode")
    report = await dm.run_dream_cycle()
    return {
        "cycle_date": str(report.cycle_date),
        "memories_consolidated": report.memories_consolidated,
        "gaps_identified": report.gaps_identified,
        "creative_connections": report.creative_connections,
        "campaign_insights": report.campaign_insights,
    }


@app.post("/api/email/draft")
async def email_draft(req: EmailDraftRequest) -> dict[str, Any]:
    """Generate an email draft via Calliope."""
    pantheon = _svc("pantheon")
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
