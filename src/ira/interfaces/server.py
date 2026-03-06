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
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
        raise RuntimeError(f"Service '{name}' not available")
    return svc


# ── Lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap all Ira subsystems on startup, tear down on shutdown."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.app.log_level, logging.INFO),
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── Brain layer ───────────────────────────────────────────────────
    from ira.brain.document_ingestor import DocumentIngestor
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)
    ingestor = DocumentIngestor(qdrant=qdrant)

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

    # ── Pantheon ──────────────────────────────────────────────────────
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon

    bus = MessageBus()
    pantheon = Pantheon(retriever=retriever, bus=bus)
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
    sensory = SensorySystem(knowledge_graph=graph)
    await sensory.create_tables()
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

    long_term = LongTermMemory()
    episodic = EpisodicMemory(long_term=long_term)
    conversation = ConversationMemory()
    musculoskeletal = MusculoskeletalSystem()
    await musculoskeletal.create_tables()

    dream_mode = DreamMode(
        long_term=long_term,
        episodic=episodic,
        conversation=conversation,
        musculoskeletal=musculoskeletal,
        retriever=retriever,
    )

    _services["long_term"] = long_term
    _services["episodic"] = episodic
    _services["conversation"] = conversation
    _services["musculoskeletal"] = musculoskeletal
    _services["dream_mode"] = dream_mode

    # ── Learning hub ──────────────────────────────────────────────────
    from ira.memory.procedural import ProceduralMemory
    from ira.systems.learning_hub import LearningHub

    procedural_memory = ProceduralMemory()
    learning_hub = LearningHub(crm=crm, procedural_memory=procedural_memory)

    _services["procedural_memory"] = procedural_memory
    _services["learning_hub"] = learning_hub

    # ── Unified context ───────────────────────────────────────────────
    from ira.context import UnifiedContextManager

    unified_context = UnifiedContextManager()
    _services["unified_context"] = unified_context

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

    # ── Respiratory system (background tasks) ─────────────────────────
    from ira.systems.respiratory import RespiratorySystem

    respiratory = RespiratorySystem(
        digestive=digestive,
        ingestor=ingestor,
        dream_mode=dream_mode,
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
    await pantheon.stop()
    await sensory.close()
    await musculoskeletal.close()
    await graph.close()

    _services.clear()
    logger.info("All services shut down.")


# ── App ───────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Ira — Machinecraft AI Pantheon",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Route a query through Athena and the Pantheon."""
    pantheon = _svc("pantheon")

    ctx = req.context or {}
    if req.user_id:
        unified_context = _svc("unified_context")
        user_ctx = unified_context.get(req.user_id)
        ctx["cross_channel_history"] = unified_context.recent_history(
            req.user_id, limit=10,
        )
        ctx["last_channel"] = user_ctx.last_channel

    response = await pantheon.process(req.query, ctx)

    if req.user_id:
        unified_context = _svc("unified_context")
        unified_context.record_turn(
            req.user_id, ctx.get("channel", "api"), req.query, response,
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


@app.post("/api/ingest")
async def ingest_file(file: UploadFile) -> dict[str, Any]:
    """Upload a document for ingestion through the DigestiveSystem."""
    digestive = _svc("digestive")
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    result = await digestive.ingest(
        raw_data=text,
        source=file.filename or "upload",
        source_category="document_upload",
    )
    return {
        "filename": file.filename,
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
