"""Ira CLI — command-line interface for the Machinecraft AI Pantheon.

Provides interactive chat, single-query mode, email drafting and learning,
document ingestion, dream cycles, board meetings, training cycles, pipeline
views, health checks, and agent introspection.

Usage::

    ira chat
    ira ask "What machines do we sell in MENA?"
    ira email draft --to "client@example.com" --subject "Follow-up" --context "..."
    ira email learn --thread-id "18f3a..."
    ira ingest data/imports/
    ira dream
    ira board "Q3 European expansion strategy"
    ira train
    ira pipeline
    ira health
    ira agents
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from ira.exceptions import ConfigurationError, IraError
from ira.service_keys import ServiceKey as SK
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="ira",
    help="Ira — Machinecraft AI Pantheon CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

email_app = typer.Typer(help="Email drafting and learning commands.")
app.add_typer(email_app, name="email")

system_app = typer.Typer(help="System lifecycle commands (inhale/exhale).")
app.add_typer(system_app, name="system")

logger = logging.getLogger(__name__)


# ── Lazy bootstrap ────────────────────────────────────────────────────────
#
# Heavy imports and service construction happen only when a command actually
# runs, keeping ``ira --help`` instant.


def _run(coro: Any) -> Any:
    """Run an async coroutine from synchronous CLI context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_pantheon() -> tuple[Any, dict[str, Any]]:
    """Construct a Pantheon with full service wiring for CLI use.

    Returns a ``(pantheon, shared_services)`` tuple so that callers can
    forward the shared CRM / quotes / pricing / retriever instances to
    ``_build_pipeline`` instead of creating duplicate connections.
    """
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.pricing_engine import PricingEngine
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.config import get_settings
    from ira.data.crm import CRMDatabase
    from ira.data.quotes import QuoteManager
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon
    from ira.skills.handlers import bind_services as bind_skill_services

    settings = get_settings()

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()

    mem0_client = None
    mem0_key = settings.memory.api_key.get_secret_value()
    if mem0_key:
        try:
            from mem0 import MemoryClient
            mem0_client = MemoryClient(api_key=mem0_key)
        except (ConfigurationError, Exception):
            logger.warning("Mem0 init failed — continuing without conversational memory")

    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph, mem0_client=mem0_client)
    bus = MessageBus()

    crm = CRMDatabase()
    quotes = QuoteManager(session_factory=crm.session_factory)
    pricing_engine = PricingEngine(retriever=retriever, crm=crm)

    from ira.systems.data_event_bus import DataEventBus
    data_event_bus = DataEventBus()
    crm.set_event_bus(data_event_bus)
    graph.set_event_bus(data_event_bus)
    qdrant.set_event_bus(data_event_bus)

    from ira.systems.circulatory import CirculatorySystem
    CirculatorySystem(
        data_event_bus,
        crm=crm, graph=graph, qdrant=qdrant, embedding=embedding,
    )

    pantheon = Pantheon(retriever=retriever, bus=bus)

    shared_services = {
        SK.CRM: crm,
        SK.QUOTES: quotes,
        SK.PRICING_ENGINE: pricing_engine,
        SK.RETRIEVER: retriever,
        SK.DATA_EVENT_BUS: data_event_bus,
        "mem0_client": mem0_client,
    }
    pantheon.inject_services(shared_services)
    bind_skill_services(shared_services)

    return pantheon, shared_services


async def _build_pipeline(
    pantheon: Any,
    shared_services: dict[str, Any],
) -> tuple[Any, Any]:
    """Construct a full RequestPipeline and FeedbackHandler for CLI use.

    *shared_services* is the dict returned by ``_build_pantheon()`` and
    contains at least ``crm`` and ``quotes`` so we reuse the same
    connection pool instead of opening a duplicate.

    Returns ``(pipeline, feedback_handler)``.
    """
    data_event_bus = shared_services.get(SK.DATA_EVENT_BUS)
    if data_event_bus is not None:
        await data_event_bus.start()

    from ira.brain.correction_store import CorrectionStore
    from ira.brain.feedback_handler import FeedbackHandler
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.context import UnifiedContextManager
    from ira.memory.conversation import ConversationMemory
    from ira.memory.emotional_intelligence import EmotionalIntelligence
    from ira.memory.episodic import EpisodicMemory
    from ira.memory.goal_manager import GoalManager
    from ira.memory.inner_voice import InnerVoice
    from ira.memory.long_term import LongTermMemory
    from ira.memory.metacognition import Metacognition
    from ira.memory.procedural import ProceduralMemory
    from ira.memory.relationship import RelationshipMemory
    from ira.pipeline import RequestPipeline
    from ira.systems.endocrine import EndocrineSystem
    from ira.systems.learning_hub import LearningHub
    from ira.systems.sensory import SensorySystem
    from ira.systems.voice import VoiceSystem

    graph = KnowledgeGraph()
    sensory = SensorySystem(knowledge_graph=graph)
    await sensory.create_tables()

    long_term = LongTermMemory()
    episodic = EpisodicMemory(long_term=long_term)
    await episodic.initialize()

    conversation = ConversationMemory()
    await conversation.initialize()
    relationship_memory = RelationshipMemory()
    await relationship_memory.initialize()
    goal_manager = GoalManager()
    await goal_manager.initialize()
    procedural_memory = ProceduralMemory()
    await procedural_memory.initialize()
    metacognition = Metacognition()
    await metacognition.initialize()
    inner_voice = InnerVoice()
    await inner_voice.initialize()

    emotional_intelligence = EmotionalIntelligence()
    await emotional_intelligence.initialize()

    voice = VoiceSystem()
    endocrine = EndocrineSystem()
    crm = shared_services[SK.CRM]
    await crm.create_tables()
    unified_context = UnifiedContextManager()

    learning_hub = LearningHub(crm=crm, procedural_memory=procedural_memory)

    correction_store = CorrectionStore()
    await correction_store.initialize()

    mem0_client = shared_services.get("mem0_client")

    feedback_handler = FeedbackHandler(
        learning_hub=learning_hub,
        correction_store=correction_store,
        mem0_client=mem0_client,
        procedural_memory=procedural_memory,
    )
    await feedback_handler.load_scores()

    sensory.configure_memory(
        emotional_intelligence=emotional_intelligence,
        conversation_memory=conversation,
        relationship_memory=relationship_memory,
    )

    pantheon.inject_services({
        SK.LONG_TERM_MEMORY: long_term,
        SK.EPISODIC_MEMORY: episodic,
        SK.CONVERSATION_MEMORY: conversation,
        SK.RELATIONSHIP_MEMORY: relationship_memory,
        SK.GOAL_MANAGER: goal_manager,
        SK.PROCEDURAL_MEMORY: procedural_memory,
        SK.EMOTIONAL_INTELLIGENCE: emotional_intelligence,
        SK.LEARNING_HUB: learning_hub,
        SK.PANTHEON: pantheon,
        SK.DATA_EVENT_BUS: shared_services.get(SK.DATA_EVENT_BUS),
    })

    nemesis = pantheon.get_agent("nemesis")
    if nemesis is not None and hasattr(nemesis, "configure"):
        nemesis.configure(learning_hub=learning_hub, peer_agents=pantheon.agents)

    redis_cache = None
    try:
        from ira.systems.redis_cache import RedisCache
        redis_cache = RedisCache()
        await redis_cache.connect()
    except (ConfigurationError, Exception):
        logger.info("Redis not available for CLI — pipeline state will be in-memory only")

    logger.info("CLI pipeline ready with feedback handler")

    pipeline = RequestPipeline(
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
        unified_context=unified_context,
        redis_cache=redis_cache,
    )

    return pipeline, feedback_handler


def _build_digestive() -> tuple[Any, Any, Any]:
    """Return (digestive_system, document_ingestor, qdrant_manager)."""
    from ira.brain.document_ingestor import DocumentIngestor
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.systems.digestive import DigestiveSystem

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)
    digestive = DigestiveSystem(
        ingestor=ingestor,
        knowledge_graph=graph,
        embedding_service=embedding,
        qdrant=qdrant,
    )
    return digestive, ingestor, qdrant


def _build_email_processor(
    pantheon: Any,
    digestive: Any,
    shared_services: dict[str, Any] | None = None,
) -> Any:
    """Construct an EmailProcessor wired to the Pantheon's Delphi agent.

    Reuses the CRM instance from *shared_services* when available to
    avoid opening a duplicate database connection pool.
    """
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.interfaces.email_processor import EmailProcessor
    from ira.systems.sensory import SensorySystem

    graph = KnowledgeGraph()
    sensory = SensorySystem(knowledge_graph=graph)

    if shared_services and SK.CRM in shared_services:
        crm = shared_services[SK.CRM]
    else:
        from ira.data.crm import CRMDatabase
        crm = CRMDatabase()

    delphi = pantheon.get_agent("delphi")
    return EmailProcessor(
        delphi=delphi,
        digestive=digestive,
        sensory=sensory,
        crm=crm,
    )


# Project Shakti Graduation Thresholds
_GRAD_MIN_INTERACTIONS = 1000
_GRAD_MIN_AVG_SCORE = 4.5
_GRAD_MIN_PROCEDURES = 10

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _update_env_file(updates: dict[str, str]) -> None:
    """Insert or replace key=value pairs in the project ``.env`` file."""
    env_path = _PROJECT_ROOT / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*", re.MULTILINE)
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


# ── Commands ──────────────────────────────────────────────────────────────


@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Interactive chat session with Ira (feedback-aware)."""
    _configure_logging(verbose)

    console.print(
        Panel(
            "[bold]Ira[/bold] — Machinecraft AI Pantheon\n"
            "Type your message and press Enter.  Use [bold]/quit[/bold] to exit.\n"
            "[dim]Feedback is detected automatically — just correct Ira naturally.[/dim]",
            title="Chat Session",
            border_style="blue",
        )
    )

    pantheon, shared_services = _build_pantheon()

    async def _session() -> None:
        user_id = "cli-user"

        async with pantheon:
            pipeline, feedback_handler = await _build_pipeline(pantheon, shared_services)

            last_exchange: dict[str, Any] | None = None

            while True:
                try:
                    user_input = console.input("[bold cyan]You:[/bold cyan] ")
                except (EOFError, KeyboardInterrupt):
                    break

                text = user_input.strip()
                if not text:
                    continue
                if text.lower() in ("/quit", "/exit", "/q"):
                    break

                if last_exchange is not None:
                    try:
                        fb_result = await feedback_handler.detect_feedback(
                            text,
                            last_exchange["query"],
                            last_exchange["response"],
                        )

                        if fb_result["polarity"] in ("positive", "negative"):
                            await feedback_handler.process_feedback(
                                text,
                                last_exchange["query"],
                                last_exchange["response"],
                                last_exchange["agents_used"],
                                user_id=user_id,
                            )

                            if fb_result["polarity"] == "negative":
                                console.print(
                                    "[dim yellow]  ↳ Correction noted and queued for learning.[/dim yellow]"
                                )
                            elif fb_result["polarity"] == "positive":
                                console.print(
                                    "[dim green]  ↳ Positive feedback recorded.[/dim green]"
                                )
                    except (IraError, Exception):
                        logger.debug("Feedback detection failed", exc_info=True)

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold green]Consulting agents..."),
                    console=err_console,
                    transient=True,
                ) as progress:
                    progress.add_task("thinking", total=None)
                    response, agents_used = await pipeline.process_request(
                        raw_input=text,
                        channel="cli",
                        sender_id=user_id,
                    )

                last_exchange = {
                    "query": text,
                    "response": response,
                    "agents_used": agents_used,
                }

                console.print()
                console.print(Panel(Markdown(response), title="Ira", border_style="green"))
                console.print()

    _run(_session())
    console.print("\n[dim]Session ended.[/dim]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="The question to ask Ira."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Ask Ira a single question and print the response."""
    _configure_logging(verbose)

    pantheon, shared_services = _build_pantheon()

    async def _ask() -> None:
        user_id = "cli-user"

        async with pantheon:
            pipeline, _feedback = await _build_pipeline(pantheon, shared_services)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Thinking..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("thinking", total=None)
                response, _agents = await pipeline.process_request(
                    raw_input=query,
                    channel="cli",
                    sender_id=user_id,
                )

        console.print(Panel(Markdown(response), title="Ira", border_style="green"))

    _run(_ask())


@app.command()
def feedback(
    correction: str = typer.Argument(..., help="The correction or feedback to record."),
    entity: str = typer.Option("", "--entity", "-e", help="Entity being corrected (e.g. company name, price)."),
    category: str = typer.Option("GENERAL", "--category", "-c", help="PRICING, SPECS, CUSTOMER, COMPETITOR, GENERAL."),
    severity: str = typer.Option("HIGH", "--severity", "-s", help="CRITICAL, HIGH, MEDIUM, LOW."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Record an explicit correction for Ira to learn from.

    Use this when you notice Ira got something wrong outside of a chat
    session, or want to proactively teach it a fact.

    Examples::

        ira feedback "Acme Corp is a customer, not a competitor"
        ira feedback "The MC-500 weighs 2400kg" --entity "MC-500" --category SPECS
        ira feedback "Al Rajhi quoted at USD 185k" --entity "Al Rajhi" --category PRICING
    """
    _configure_logging(verbose)

    async def _feedback() -> None:
        from ira.brain.correction_store import (
            CorrectionCategory,
            CorrectionSeverity,
            CorrectionStore,
        )
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.qdrant_manager import QdrantManager
        from ira.brain.sleep_trainer import SleepTrainer

        try:
            cat = CorrectionCategory(category.upper())
        except ValueError:
            console.print(f"[red]Invalid category: {category}[/red]")
            console.print(f"Valid: {', '.join(c.value for c in CorrectionCategory)}")
            raise typer.Exit(1)

        try:
            sev = CorrectionSeverity(severity.upper())
        except ValueError:
            console.print(f"[red]Invalid severity: {severity}[/red]")
            console.print(f"Valid: {', '.join(s.value for s in CorrectionSeverity)}")
            raise typer.Exit(1)

        store = CorrectionStore()
        await store.initialize()

        correction_entity = entity or correction[:100]
        cid = await store.add_correction(
            entity=correction_entity,
            new_value=correction,
            category=cat,
            severity=sev,
            source="cli-feedback",
        )

        console.print(
            f"[green]Correction #{cid} recorded:[/green] {correction_entity}"
        )

        if sev in (CorrectionSeverity.HIGH, CorrectionSeverity.CRITICAL):
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold magenta]Running micro-learning cycle..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("learning", total=None)

                embedding = EmbeddingService()
                qdrant = QdrantManager(embedding_service=embedding)
                trainer = SleepTrainer(
                    correction_store=store,
                    qdrant_manager=qdrant,
                    embedding_service=embedding,
                )
                stats = await trainer.run_training()

            phases = stats.get("phases", {})
            phase_summary = []
            for name, info in phases.items():
                status = info.get("status", "?")
                style = "green" if status == "ok" else "yellow" if status == "skipped" else "red"
                phase_summary.append(f"[{style}]{name}: {status}[/{style}]")

            console.print(
                Panel(
                    f"[bold]Corrections processed:[/bold] {stats.get('corrections_count', 0)}\n"
                    + "\n".join(phase_summary),
                    title="Micro-Learning Complete",
                    border_style="magenta",
                )
            )
        else:
            console.print(
                "[dim]Correction stored. It will be processed in the next dream cycle "
                "or run [bold]ira dream[/bold] to process now.[/dim]"
            )

        await store.close()

    _run(_feedback())


@app.command(name="learn-from-cursor")
def learn_from_cursor(
    query: str = typer.Option(..., "--query", help="The original query sent to Ira."),
    response: str = typer.Option(..., "--response", help="Ira's response."),
    correction: str = typer.Option("", "--correction", help="The correct answer."),
    feedback: str = typer.Option("", "--feedback", help="Your feedback on the response."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Teach Ira from a correction made in Cursor chat.

    Feeds the correction through the FeedbackHandler pipeline: stores
    the correction, updates procedural memory, and triggers a
    micro-learning cycle for high-severity corrections.
    """
    _configure_logging(verbose)

    if not correction and not feedback:
        console.print("[red]Provide at least --correction or --feedback.[/red]")
        raise typer.Exit(1)

    async def _learn() -> None:
        from ira.interfaces.cursor_feedback import process_cursor_feedback

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold magenta]Learning from correction..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("learning", total=None)
            result = await process_cursor_feedback(
                query=query,
                response=response,
                correction=correction,
                feedback=feedback,
            )

        polarity = result.get("polarity", "unknown")
        console.print(
            Panel(
                f"[bold]Polarity:[/bold] {polarity}\n"
                f"[bold]Query:[/bold] {query[:100]}...\n"
                f"[bold]Correction:[/bold] {(correction or feedback)[:200]}",
                title="Correction Recorded",
                border_style="magenta",
            )
        )

    _run(_learn())


@app.command()
def server(
    mode: str = typer.Option("training", help="Server mode: training or operational."),
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8000, help="Bind port."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Start the FastAPI server with background services (stub)."""
    _configure_logging(verbose)
    console.print(
        Panel(
            f"[bold]Mode:[/bold] {mode}\n"
            f"[bold]Bind:[/bold] {host}:{port}\n\n"
            "[dim]FastAPI server implementation is a Phase 6 deliverable.[/dim]",
            title="Ira Server",
            border_style="yellow",
        )
    )
    console.print("[yellow]Server not yet implemented — use individual CLI commands for now.[/yellow]")


@app.command()
def mcp(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Start the MCP (Model Context Protocol) server.

    Exposes Ira's tools to Claude, Cursor, and any MCP-compatible client.
    Configure in .cursor/mcp.json to use Ira as a Cursor tool.
    """
    _configure_logging(verbose)
    console.print(
        Panel(
            "[bold]Starting Ira MCP Server[/bold]\n\n"
            "Tools exposed: query_ira, search_knowledge, search_crm,\n"
            "get_pipeline_summary, draft_email, ingest_document,\n"
            "get_agent_list, ask_agent",
            title="Ira MCP",
            border_style="cyan",
        )
    )
    from ira.interfaces.mcp_server import main as mcp_main
    mcp_main()


# ── Email sub-commands ────────────────────────────────────────────────────


@email_app.command("draft")
def email_draft(
    to: str = typer.Option(..., "--to", help="Recipient email address."),
    subject: str = typer.Option(..., "--subject", help="Email subject line."),
    context: str = typer.Option(..., "--context", help="Instructions for the draft."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Generate an email draft via Calliope that Rushabh can copy-paste into Gmail."""
    _configure_logging(verbose)

    pantheon, _shared = _build_pantheon()

    async def _draft() -> None:
        async with pantheon:
            calliope = pantheon.get_agent("calliope")
            if calliope is None:
                console.print("[red]Calliope agent not found.[/red]")
                raise typer.Exit(1)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Calliope is drafting..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("drafting", total=None)
                body = await calliope.handle(
                    context,
                    {"draft_type": "email", "recipient": to, "tone": "professional"},
                )

        console.print()
        console.print(Panel(
            f"[bold]To:[/bold]      {to}\n"
            f"[bold]Subject:[/bold] {subject}\n"
            f"{'─' * 50}\n\n"
            f"{body}",
            title="Email Draft",
            border_style="cyan",
        ))

    _run(_draft())


@email_app.command("learn")
def email_learn(
    thread_id: str = typer.Option(..., "--thread-id", help="Gmail thread ID to learn from."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Fetch a Gmail thread, digest it, and update CRM + memory systems."""
    _configure_logging(verbose)

    pantheon, _shared = _build_pantheon()
    digestive, _ingestor, _qdrant = _build_digestive()
    email_proc = _build_email_processor(pantheon, digestive)

    async def _learn() -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Fetching thread..."),
            console=err_console,
            transient=True,
        ) as progress:
            task = progress.add_task("fetch", total=None)
            emails = await email_proc.get_thread(thread_id)
            progress.update(task, description=f"[bold green]Processing {len(emails)} emails...")

        if not emails:
            console.print("[yellow]No messages found in thread.[/yellow]")
            raise typer.Exit(0)

        table = Table(title=f"Thread: {emails[0].subject} ({len(emails)} messages)")
        table.add_column("#", style="dim", width=3)
        table.add_column("From", style="cyan")
        table.add_column("Date", style="green")
        table.add_column("Snippet", max_width=60)

        for i, email in enumerate(emails, 1):
            snippet = email.body[:80].replace("\n", " ") + ("..." if len(email.body) > 80 else "")
            table.add_row(
                str(i),
                email.from_address,
                email.received_at.strftime("%Y-%m-%d %H:%M"),
                snippet,
            )

        console.print(table)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Digesting through analysis pipeline..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("digest", total=None)
            for email in emails:
                await digestive.ingest_email(email)

        console.print(f"\n[green]Learned from {len(emails)} emails in thread {thread_id}.[/green]")

    _run(_learn())


@email_app.command("sync")
def email_sync(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Fetch and process new emails from Gmail (one-time sync).

    Runs a single poll cycle — fetches new emails, classifies them via
    Delphi, digests through the DigestiveSystem, and updates the CRM.
    Exits when done (does not loop).
    """
    _configure_logging(verbose)

    pantheon, shared = _build_pantheon()
    digestive, _ingestor, _qdrant = _build_digestive()
    email_proc = _build_email_processor(pantheon, digestive, shared)

    async def _sync() -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Syncing inbox..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("sync", total=None)
            results = await email_proc.run_single_poll_cycle()

        console.print(
            f"[green]Email sync complete — {len(results)} emails processed.[/green]"
        )

    _run(_sync())


_MC_SALES_QUERY = (
    "{from:machinecraft.org OR from:machinecraft.in "
    "OR to:machinecraft.org OR to:machinecraft.in "
    "OR subject:machinecraft OR subject:thermoform OR subject:vacuum form "
    "OR subject:PF1 OR subject:PF2 OR subject:ATF "
    "OR subject:quote OR subject:proposal OR subject:pricing "
    "OR subject:order OR subject:delivery OR subject:inquiry}"
)


@email_app.command("rescan")
def email_rescan(
    after: str = typer.Option("2023/03/08", "--after", help="Start date YYYY/MM/DD (inclusive)."),
    before: str = typer.Option("2026/03/08", "--before", help="End date YYYY/MM/DD (exclusive)."),
    query: str = typer.Option(
        _MC_SALES_QUERY, "--query", "-q",
        help="Gmail search query to narrow the scan. Default: Machinecraft machine sales only.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify but don't write to CRM/Qdrant."),
    resume: bool = typer.Option(False, "--resume", help="Resume from last checkpoint."),
    throttle: float = typer.Option(0.1, "--throttle", help="Seconds between message fetches."),
    skip_crm: bool = typer.Option(False, "--skip-crm-populate", help="Skip the CRM population phase."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Deep-scan historical Gmail and build Machinecraft sales intelligence.

    By default, scans ONLY emails related to Machinecraft machine sales:
    emails sent/received by machinecraft.org, or containing machine model
    names (PF1, PF2, ATF), or sales keywords (quote, proposal, pricing,
    order, delivery, inquiry).

    Use --query "" to scan all emails (much slower).

    Phase 1: Deep email scan (fetch, classify, digest, CRM interactions)
    Phase 2: CRM population (classify contacts, insert eligible ones)
    Phase 3: Sales intelligence report (4 categories)

    Examples::

        ira email rescan --after 2025/01/01 --before 2026/03/09
        ira email rescan --query "" --after 2024/01/01   # scan everything
        ira email rescan --resume
    """
    _configure_logging(verbose)

    pantheon, shared = _build_pantheon()
    digestive, _ingestor, _qdrant = _build_digestive()
    email_proc = _build_email_processor(pantheon, digestive, shared)

    async def _rescan() -> None:
        crm = shared[SK.CRM]
        await crm.create_tables()

        query_label = query[:80] + "..." if len(query) > 80 else query
        console.print(Panel(
            f"[bold]Date range:[/bold]  {after} → {before}\n"
            f"[bold]Query:[/bold]       {query_label or '[dim]all emails[/dim]'}\n"
            f"[bold]Mode:[/bold]        {'[yellow]DRY RUN[/yellow]' if dry_run else '[green]LIVE[/green]'}\n"
            f"[bold]Resume:[/bold]      {'yes' if resume else 'no'}\n"
            f"[bold]Throttle:[/bold]    {throttle}s between messages\n"
            f"[bold]CRM populate:[/bold] {'skip' if skip_crm else 'yes'}",
            title="Deep Mailbox Rescan — Machinecraft Sales",
            border_style="blue",
        ))

        # Get Artemis for batch triage
        artemis = pantheon.get_agent("artemis") if hasattr(pantheon, "get_agent") else None
        if artemis:
            console.print("[dim]  Artemis (Lead Hunter) will batch-triage emails before deep processing.[/dim]")
        else:
            console.print("[yellow]  Artemis not available — processing all emails (slower).[/yellow]")

        # Phase 1: Deep email scan
        console.print("\n[bold cyan]Phase 1:[/bold cyan] Scanning and digesting emails...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=err_console,
        ) as progress:
            task = progress.add_task(
                "[bold green]Scanning mailbox...", total=None,
            )

            def on_progress(processed: int, total: int, stats: dict) -> None:
                if progress.tasks[task].total is None and total > 0:
                    progress.update(task, total=total)
                triaged = stats.get("triaged_business_high", 0) + stats.get("triaged_noise", 0)
                deep = stats.get("processed", 0)
                label = (
                    f"[bold green]triage:{triaged} "
                    f"biz:{stats.get('triaged_business_high', 0)} "
                    f"| deep:{deep} "
                    f"in:{stats.get('inbound_emails', 0)} "
                    f"out:{stats.get('outbound_emails', 0)} "
                    f"| contacts:{stats.get('contacts_found', 0)} "
                    f"deals:{stats.get('deals_created', 0)} "
                    f"err:{stats.get('errors', 0)}"
                )
                progress.update(task, completed=triaged + deep, description=label)

            scan_stats = await email_proc.deep_scan(
                after=after,
                before=before,
                throttle=throttle,
                resume=resume,
                dry_run=dry_run,
                progress_callback=on_progress,
                artemis=artemis,
                gmail_query=query,
            )

        scan_table = Table(title="Phase 1: Email Scan Results")
        scan_table.add_column("Metric", style="cyan")
        scan_table.add_column("Count", justify="right", style="green")

        scan_table.add_row("Messages listed", str(scan_stats.get("total_listed", 0)))
        triaged_biz = scan_stats.get("triaged_business_high", 0)
        triaged_noise = scan_stats.get("triaged_noise", 0)
        if triaged_biz or triaged_noise:
            scan_table.add_row("[bold]Artemis triage[/bold]", "")
            scan_table.add_row("  ↳ Business (deep-processed)", str(triaged_biz))
            scan_table.add_row("  ↳ Noise (skipped)", str(triaged_noise))
        scan_table.add_row("Fetched (full body)", str(scan_stats.get("fetched", 0)))
        scan_table.add_row("Deep-processed", str(scan_stats.get("processed", 0)))
        scan_table.add_row("  ↳ Inbound", str(scan_stats.get("inbound_emails", 0)))
        scan_table.add_row("  ↳ Outbound", str(scan_stats.get("outbound_emails", 0)))
        scan_table.add_row("  ↳ Proposal signals", str(scan_stats.get("proposal_signals", 0)))
        scan_table.add_row("Skipped (duplicate)", str(scan_stats.get("skipped_duplicate", 0)))
        scan_table.add_row("Skipped (non-business)", str(scan_stats.get("skipped_non_business", 0)))
        scan_table.add_row("Contacts found", str(scan_stats.get("contacts_found", 0)))
        scan_table.add_row("Deals created", str(scan_stats.get("deals_created", 0)))
        scan_table.add_row("[yellow]Unanswered inbound threads[/yellow]",
                           str(scan_stats.get("unanswered_inbound_threads", 0)))
        scan_table.add_row("Errors", str(scan_stats.get("errors", 0)))
        console.print(scan_table)

        # Phase 2: CRM population
        pop_stats: dict[str, Any] = {}
        if not skip_crm:
            console.print("\n[bold cyan]Phase 2:[/bold cyan] Classifying and populating CRM contacts...")

            from ira.brain.embeddings import EmbeddingService
            from ira.brain.knowledge_graph import KnowledgeGraph
            from ira.brain.qdrant_manager import QdrantManager
            from ira.brain.retriever import UnifiedRetriever
            from ira.message_bus import MessageBus
            from ira.systems.crm_populator import CRMPopulator

            embedding = EmbeddingService()
            qdrant_mgr = QdrantManager(embedding_service=embedding)
            graph = KnowledgeGraph()
            retriever = UnifiedRetriever(qdrant=qdrant_mgr, graph=graph)
            bus = MessageBus()

            from ira.agents.delphi import Delphi
            delphi = Delphi(retriever=retriever, bus=bus)

            populator = CRMPopulator(delphi=delphi, crm=crm, dry_run=dry_run)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Classifying contacts..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("populate", total=None)
                pop_result = await populator.populate(
                    sources=["gmail", "kb", "neo4j"],
                    after=after,
                    before=before,
                )

            pop_stats = pop_result["stats"]
            pop_table = Table(title="Phase 2: CRM Population Results")
            pop_table.add_column("Metric", style="cyan")
            pop_table.add_column("Count", justify="right", style="green")

            pop_table.add_row("Total extracted", str(pop_stats["total_extracted"]))
            pop_table.add_row("Classified", str(pop_stats["classified"]))
            pop_table.add_row("Inserted into CRM", str(pop_stats["inserted"]))
            pop_table.add_row("Skipped (duplicate)", str(pop_stats["skipped_duplicate"]))
            pop_table.add_row("Skipped (rejected)", str(pop_stats["skipped_rejected"]))
            pop_table.add_row("Errors", str(pop_stats["errors"]))
            console.print(pop_table)

        # Phase 3: Sales intelligence report (4 categories)
        if not dry_run:
            console.print("\n[bold cyan]Phase 3:[/bold cyan] Generating sales intelligence report...")

            unanswered = scan_stats.get("unanswered_inbound_threads", 0)
            proposals = scan_stats.get("proposal_signals", 0)

            report_queries = [
                (
                    "Customer Journey Map",
                    "Search the CRM and knowledge base for all LIVE_CUSTOMER contacts. "
                    "For each customer, report: (1) company name and contact person, "
                    "(2) how the relationship started — first email interaction and what "
                    "it was about, (3) the conversation timeline — key milestones from "
                    "first contact to purchase, (4) which Machinecraft machine(s) they "
                    "bought (model, specs), (5) deal value and currency. "
                    "Present as a structured list per customer.",
                ),
                (
                    "Delivered Machines & Open Issues",
                    "Search the CRM and knowledge base for customers whose machines have "
                    "been delivered or are marked as WON deals. For each, report: "
                    "(1) company name, (2) machine model and technical specs, "
                    "(3) delivery date or expected delivery, (4) price/deal value, "
                    "(5) any open support issues, complaints, or pending punch list items "
                    "from email threads. Flag any customer with unresolved issues.",
                ),
                (
                    "Hot Sales Leads (Quotes Sent)",
                    f"We found {proposals} emails with proposal/quote signals during the scan. "
                    "Search the CRM for all deals at PROPOSAL or NEGOTIATION stage, and "
                    "all contacts classified as LEAD_WITH_INTERACTIONS. For each, report: "
                    "(1) company and contact person, (2) which machine model was quoted, "
                    "(3) price/value from the quote, (4) when the quote/proposal was sent, "
                    "(5) the last interaction date and what it was about, "
                    "(6) days since last contact. Sort by most recent interaction first. "
                    "These are our hottest re-engagement opportunities.",
                ),
                (
                    "Missed Leads (Unanswered Inbound)",
                    f"The mailbox scan detected {unanswered} inbound email threads that "
                    "never received an outbound reply from Machinecraft. Search the CRM "
                    "for contacts classified as LEAD_NO_INTERACTIONS or any contacts with "
                    "only inbound interactions and no outbound. For each, report: "
                    "(1) who emailed us and from which company, (2) what they asked about "
                    "(machine model, inquiry type), (3) when they emailed, "
                    "(4) why this might be a lost opportunity. "
                    "These are leads we dropped — prioritise any that mentioned specific "
                    "machines or pricing.",
                ),
            ]

            async with pantheon:
                pipeline, _fb = await _build_pipeline(pantheon, shared)

                for title, rq in report_queries:
                    console.print(f"\n  [dim]Generating: {title}...[/dim]")

                    with Progress(
                        SpinnerColumn(),
                        TextColumn(f"[bold green]Consulting agents for {title}..."),
                        console=err_console,
                        transient=True,
                    ) as progress:
                        progress.add_task("report", total=None)
                        response, agents_used = await pipeline.process_request(
                            raw_input=rq,
                            channel="cli",
                            sender_id="rescan-report",
                        )

                    console.print(Panel(
                        Markdown(response),
                        title=f"{title} (agents: {', '.join(agents_used)})",
                        border_style="green",
                    ))

        # Final summary
        console.print(Panel(
            f"[bold]Emails scanned:[/bold]       {scan_stats.get('processed', 0)}\n"
            f"[bold]Inbound / Outbound:[/bold]   "
            f"{scan_stats.get('inbound_emails', 0)} / {scan_stats.get('outbound_emails', 0)}\n"
            f"[bold]Proposal signals:[/bold]     {scan_stats.get('proposal_signals', 0)}\n"
            f"[bold]Contacts found:[/bold]       {scan_stats.get('contacts_found', 0)}\n"
            f"[bold]Deals created:[/bold]        {scan_stats.get('deals_created', 0)}\n"
            f"[bold]Unanswered threads:[/bold]   {scan_stats.get('unanswered_inbound_threads', 0)}\n"
            + (
                f"[bold]CRM contacts added:[/bold]   {pop_stats.get('inserted', 0)}\n"
                if not skip_crm else ""
            )
            + "\n[dim]All email protein is now searchable in Qdrant.\n"
            "Entity relationships are in Neo4j.\n"
            "Ask Ira about customers, leads, or proposals to query the enriched data.[/dim]",
            title="Deep Rescan Complete",
            border_style="green",
        ))

    _run(_rescan())


@email_app.command("drip")
def email_drip(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run a single cycle of the Autonomous Drip Engine.

    Evaluates active campaigns, sends pending drip steps (as Gmail
    drafts for human review), and checks for replies.
    """
    _configure_logging(verbose)

    pantheon, shared = _build_pantheon()
    digestive, _ingestor, _qdrant = _build_digestive()
    email_proc = _build_email_processor(pantheon, digestive, shared)

    async def _drip() -> None:
        from ira.interfaces.email_processor import GmailDraftSender
        from ira.systems.drip_engine import AutonomousDripEngine

        crm = shared[SK.CRM]
        await crm.create_tables()
        quotes = shared.get(SK.QUOTES)

        gmail_sender = GmailDraftSender(email_processor=email_proc)
        drip = AutonomousDripEngine(
            crm=crm,
            quotes=quotes,
            gmail=gmail_sender,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Running drip cycle..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("drip", total=None)
            result = await drip.run_cycle()

        eval_stats = result.get("evaluation", {})
        sent = result.get("sent", {})
        replies = result.get("replies", {})
        console.print(
            Panel(
                f"[bold]Campaigns evaluated:[/bold] {eval_stats.get('campaigns', 0)}\n"
                f"[bold]Steps sent:[/bold] {sent.get('sent', 0)}\n"
                f"[bold]Replies checked:[/bold] {replies.get('checked', 0)}",
                title="Drip Cycle Complete",
                border_style="cyan",
            )
        )

    _run(_drip())


# ── System sub-commands ──────────────────────────────────────────────────


@system_app.command("inhale")
def system_inhale(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run a morning inhale cycle: fetch emails and ingest new documents."""
    _configure_logging(verbose)

    pantheon, shared = _build_pantheon()
    digestive, _ingestor, _qdrant = _build_digestive()
    email_proc = _build_email_processor(pantheon, digestive, shared)

    from ira.systems.respiratory import RespiratorySystem

    respiratory = RespiratorySystem(
        email_processor=email_proc,
    )

    async def _inhale() -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]Inhaling..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("inhale", total=None)
            await respiratory.run_inhale_cycle()

        console.print("[green]Inhale cycle complete.[/green]")

    _run(_inhale())


@system_app.command("exhale")
def system_exhale(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run an evening exhale cycle: dream consolidation and reporting."""
    _configure_logging(verbose)

    pantheon, shared = _build_pantheon()

    async def _exhale() -> None:
        from ira.memory.dream_mode import build_dream_mode

        dream_mode = await build_dream_mode()
        try:
            respiratory = RespiratorySystem(dream_mode=dream_mode)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold magenta]Exhaling..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("exhale", total=None)
                await respiratory.run_exhale_cycle()

            console.print("[green]Exhale cycle complete.[/green]")
        finally:
            await dream_mode.close()

    from ira.systems.respiratory import RespiratorySystem
    _run(_exhale())


# ── Metadata Index ────────────────────────────────────────────────────────


@app.command(name="index-imports")
def index_imports(
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM summaries (fast local-only extraction)."),
    force: bool = typer.Option(False, "--force", "-f", help="Force rebuild all entries."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Build or update the LLM metadata index for data/imports/.

    Scans every file in the imports directory and generates structured
    metadata (summary, doc_type, machines, entities, keywords) using
    GPT-4.1-mini.  The index powers Alexandros's hybrid search.
    """
    _configure_logging(verbose)

    async def _index() -> None:
        from ira.brain.imports_metadata_index import build_index, get_index_stats

        def progress(done: int, total: int, name: str) -> None:
            console.print(f"  [{done}/{total}] {name}")

        console.print(Panel(
            f"[bold]LLM summaries:[/bold] {'disabled' if no_llm else 'enabled'}\n"
            f"[bold]Force rebuild:[/bold] {'yes' if force else 'no'}",
            title="Metadata Index Build",
            border_style="blue",
        ))

        stats = await build_index(
            use_llm=not no_llm,
            force=force,
            progress_callback=progress,
        )

        summary_table = Table(title="Index Build Report")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green", justify="right")
        summary_table.add_row("Total files scanned", str(stats["total"]))
        summary_table.add_row("Newly indexed", str(stats["new"]))
        summary_table.add_row("Skipped (unchanged)", str(stats["skipped"]))
        summary_table.add_row("Errors", str(stats["errors"]))
        console.print(summary_table)

        idx_stats = await get_index_stats()
        if idx_stats.get("indexed", 0) > 0:
            console.print(f"\n[green]Index now contains {idx_stats['indexed']} files "
                          f"({idx_stats.get('unique_machines', 0)} unique machines).[/green]")

    _run(_index())


# ── Ingestion ─────────────────────────────────────────────────────────────


@app.command()
def ingest(
    force: bool = typer.Option(False, "--force", "-f", help="Re-ingest all files regardless of log state."),
    batch_size: int = typer.Option(712, "--batch", "-n", help="Max files to process (default: all)."),
    concurrency: int = typer.Option(3, "--workers", "-w", help="Parallel workers (default: 3)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run Alexandros-gated intelligent document ingestion.

    Alexandros scans the metadata index against the ingestion log to find
    files that are new, changed, or were ingested by an older pipeline.
    Files are processed in parallel through the DigestiveSystem:

      STOMACH   — LLM classifies text as protein / carbs / waste
      DUODENUM  — LLM summarises protein into searchable statements
      INTESTINE — chunk, embed (Voyage-3), upsert to Qdrant Cloud
      LIVER     — entities (companies, people, machines) to Neo4j

    Use ``--force`` to re-ingest everything.
    Use ``--workers N`` to control parallelism (default: 3).
    """
    _configure_logging(verbose)

    from ira.brain.ingestion_gatekeeper import scan_for_undigested, run_ingestion_cycle

    queue = _run(scan_for_undigested(force=force))

    if not queue:
        console.print("[green]All files are up-to-date. Nothing to ingest.[/green]")
        raise typer.Exit(0)

    by_reason: dict[str, int] = {}
    for f in queue:
        by_reason[f["reason"]] = by_reason.get(f["reason"], 0) + 1

    reason_lines = ", ".join(f"{r}: {c}" for r, c in sorted(by_reason.items()))
    batch = queue[:batch_size]

    # Estimate: 45s per file sequential, divide by concurrency
    est_per_file_s = 45
    est_total_s = (len(batch) * est_per_file_s) / max(concurrency, 1)
    est_min = est_total_s / 60
    est_label = f"~{est_min:.0f} min" if est_min < 60 else f"~{est_min/60:.1f} hr"

    console.print(
        Panel(
            f"[bold]Total needing ingestion:[/bold] {len(queue)}\n"
            f"[bold]This batch:[/bold]             {len(batch)}\n"
            f"[bold]Parallel workers:[/bold]        {concurrency}\n"
            f"[bold]Reasons:[/bold]                {reason_lines}\n"
            f"[bold]Est. time:[/bold]              {est_label}\n"
            f"[bold]Force:[/bold]                  {'yes' if force else 'no'}",
            title="Alexandros Ingestion Scan",
            border_style="blue",
        )
    )

    async def _ingest() -> dict[str, Any]:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=err_console,
        ) as progress:
            task = progress.add_task("Ingesting", total=len(batch))

            def on_progress(done: int, total: int, filename: str, result: Any) -> None:
                chunks = result.get("chunks_created", 0) if isinstance(result, dict) else 0
                label = f"[bold green]{filename}" + (f" [dim]({chunks} chunks)[/dim]" if chunks else "")
                progress.update(task, completed=done, description=label)

            return await run_ingestion_cycle(
                force=force,
                batch_size=batch_size,
                concurrency=concurrency,
                progress_callback=on_progress,
            )

    result = _run(_ingest())

    summary_table = Table(title="Alexandros Ingestion Report")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green", justify="right")

    summary_table.add_row("Files processed", str(result.get("files_processed", 0)))
    summary_table.add_row("Files skipped", str(result.get("files_skipped", 0)))
    summary_table.add_row("Files failed", str(result.get("files_failed", 0)))
    summary_table.add_row("Files remaining", str(result.get("files_remaining", 0)))
    summary_table.add_row("Chunks created", str(result.get("total_chunks", 0)))
    summary_table.add_row("Pipeline", result.get("pipeline", "?"))

    console.print(summary_table)

    entities = result.get("total_entities", {})
    if any(entities.values()):
        ent_table = Table(title="Entities Extracted (Neo4j)")
        ent_table.add_column("Type", style="cyan")
        ent_table.add_column("Count", style="green", justify="right")
        for etype, count in sorted(entities.items()):
            ent_table.add_row(etype, str(count))
        console.print(ent_table)

    errors = result.get("errors", [])
    if errors:
        err_table = Table(title="Failed Files")
        err_table.add_column("#", style="dim", width=3)
        err_table.add_column("Error", style="red")
        for i, e in enumerate(errors, 1):
            err_table.add_row(str(i), e)
        console.print(err_table)

    remaining = result.get("files_remaining", 0)
    if remaining > 0:
        console.print(
            f"\n[yellow]{remaining} files still pending. "
            f"Run [bold]ira ingest[/bold] again or wait for the next sleep cycle.[/yellow]"
        )


# ── Dream ─────────────────────────────────────────────────────────────────


@app.command()
def dream(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Trigger a dream cycle and print the consolidation report."""
    _configure_logging(verbose)

    async def _dream() -> None:
        from ira.memory.dream_mode import build_dream_mode

        dream_mode = await build_dream_mode()
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold magenta]Dreaming..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("dream", total=None)
                report = await dream_mode.run_dream_cycle()

            console.print(Panel(
                f"[bold]Date:[/bold]                  {report.cycle_date}\n"
                f"[bold]Memories consolidated:[/bold] {report.memories_consolidated}",
                title="Dream Report",
                border_style="magenta",
            ))

            if report.stage_results:
                stage_table = Table(title="Stage Results")
                stage_table.add_column("Stage", style="dim")
                stage_table.add_column("Status")
                for stage_name, status in report.stage_results.items():
                    style = "green" if status == "ok" else ("red" if status == "error" else "yellow")
                    stage_table.add_row(stage_name, f"[{style}]{status}[/{style}]")
                console.print(stage_table)

            if report.gaps_identified:
                gap_table = Table(title="Knowledge Gaps Identified")
                gap_table.add_column("#", style="dim", width=3)
                gap_table.add_column("Gap", style="yellow")
                for i, gap in enumerate(report.gaps_identified, 1):
                    gap_table.add_row(str(i), gap)
                console.print(gap_table)

            if report.creative_connections:
                conn_table = Table(title="Creative Connections")
                conn_table.add_column("#", style="dim", width=3)
                conn_table.add_column("Insight", style="cyan")
                for i, conn in enumerate(report.creative_connections, 1):
                    conn_table.add_row(str(i), conn)
                console.print(conn_table)

            if report.campaign_insights:
                camp_table = Table(title="Campaign Insights")
                camp_table.add_column("#", style="dim", width=3)
                camp_table.add_column("Insight", style="green")
                for i, insight in enumerate(report.campaign_insights, 1):
                    camp_table.add_row(str(i), insight)
                console.print(camp_table)
        finally:
            await dream_mode.close()

    _run(_dream())


# ── Board meeting ─────────────────────────────────────────────────────────


@app.command()
def board(
    topic: str = typer.Argument(..., help="The topic for the board meeting."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run a Pantheon board meeting on the given topic."""
    _configure_logging(verbose)

    pantheon, _shared = _build_pantheon()

    async def _board() -> None:
        async with pantheon:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Board meeting in session..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("meeting", total=None)
                minutes = await pantheon.board_meeting(topic)

        console.print(Panel(
            f"[bold]Topic:[/bold] {minutes.topic}",
            title="Board Meeting Minutes",
            border_style="blue",
        ))

        contrib_table = Table(title="Agent Contributions")
        contrib_table.add_column("Agent", style="cyan", width=15)
        contrib_table.add_column("Contribution")
        for agent_name, contribution in minutes.contributions.items():
            contrib_table.add_row(agent_name, contribution[:200] + ("..." if len(contribution) > 200 else ""))
        console.print(contrib_table)

        console.print(Panel(Markdown(minutes.synthesis), title="Synthesis", border_style="green"))

        if minutes.action_items:
            action_table = Table(title="Action Items")
            action_table.add_column("#", style="dim", width=3)
            action_table.add_column("Item", style="yellow")
            for i, item in enumerate(minutes.action_items, 1):
                action_table.add_row(str(i), item)
            console.print(action_table)

    _run(_board())


# ── Training ──────────────────────────────────────────────────────────────


@app.command()
def train(
    scenarios: int = typer.Option(3, "--scenarios", "-n", help="Number of training scenarios to run."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run a Nemesis training cycle to stress-test agents and log results."""
    _configure_logging(verbose)

    pantheon, _shared = _build_pantheon()

    async def _train() -> None:
        from ira.data.crm import CRMDatabase
        from ira.memory.procedural import ProceduralMemory
        from ira.systems.learning_hub import LearningHub

        crm = CRMDatabase()
        await crm.create_tables()

        procedural = ProceduralMemory()
        await procedural.initialize()

        learning_hub = LearningHub(crm=crm, procedural_memory=procedural)

        async with pantheon:
            nemesis = pantheon.get_agent("nemesis")
            if nemesis is None:
                console.print("[red]Nemesis agent not found.[/red]")
                raise typer.Exit(1)

            nemesis.configure(
                learning_hub=learning_hub,
                peer_agents=pantheon.agents,
            )

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold red]Nemesis is training the Pantheon..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("training", total=None)
                report = await nemesis.handle(
                    "Run training cycle",
                    {"num_scenarios": scenarios},
                )

        console.print(Panel(
            Markdown(report),
            title="Nemesis Training Report",
            border_style="red",
        ))

        await procedural.close()

    _run(_train())


# ── Graduation ────────────────────────────────────────────────────────────


@app.command()
def graduate(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Self-assess readiness and promote Ira to OPERATIONAL email mode."""
    _configure_logging(verbose)

    async def _graduate() -> None:
        from ira.data.crm import CRMDatabase
        from ira.memory.procedural import ProceduralMemory
        from ira.systems.learning_hub import LearningHub

        crm = CRMDatabase()
        await crm.create_tables()

        procedural = ProceduralMemory()
        await procedural.initialize()

        learning_hub = LearningHub(crm=crm, procedural_memory=procedural)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Running self-assessment..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("assess", total=None)
            total_interactions = await crm.count_interactions()
            avg_score = learning_hub.get_average_score()
            num_procedures = await procedural.count_procedures()

        await procedural.close()

        table = Table(title="Graduation Self-Assessment")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right", style="green")
        table.add_column("Threshold", justify="right", style="yellow")
        table.add_column("Status", width=8)

        def _status(ok: bool) -> str:
            return "[green]PASS[/green]" if ok else "[red]FAIL[/red]"

        pass_interactions = total_interactions > _GRAD_MIN_INTERACTIONS
        pass_score = avg_score is not None and avg_score > _GRAD_MIN_AVG_SCORE
        pass_procedures = num_procedures >= _GRAD_MIN_PROCEDURES

        table.add_row(
            "Total interactions",
            str(total_interactions),
            f"> {_GRAD_MIN_INTERACTIONS}",
            _status(pass_interactions),
        )
        table.add_row(
            "Avg feedback score",
            f"{avg_score:.2f}" if avg_score is not None else "N/A",
            f"> {_GRAD_MIN_AVG_SCORE}",
            _status(pass_score),
        )
        table.add_row(
            "Procedures learned",
            str(num_procedures),
            f">= {_GRAD_MIN_PROCEDURES}",
            _status(pass_procedures),
        )
        console.print(table)

        if not (pass_interactions and pass_score and pass_procedures):
            console.print(Panel(
                "[red bold]Graduation blocked.[/red bold]\n\n"
                "The thresholds above must all pass before Ira can move to "
                "OPERATIONAL mode. Continue training and accumulating feedback.",
                title="Assessment Failed",
                border_style="red",
            ))
            raise typer.Exit(1)

        _update_env_file({
            "IRA_EMAIL_MODE": "OPERATIONAL",
            "IRA_EMAIL": "${GOOGLE_IRA_EMAIL}",
        })

        console.print(Panel(
            "[green bold]Graduation successful. Restarting in OPERATIONAL mode.[/green bold]",
            title="Assessment Passed",
            border_style="green",
        ))

        scripts_dir = _PROJECT_ROOT / "scripts"
        subprocess.run([str(scripts_dir / "stop.sh")], check=False)
        subprocess.run([str(scripts_dir / "start.sh")], check=False)

    _run(_graduate())


# ── CRM Population ────────────────────────────────────────────────────────


@app.command("populate-crm")
def populate_crm(
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify contacts but don't insert into CRM."),
    source: str = typer.Option("all", "--source", "-s", help="Data source: all, gmail, kb, neo4j."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Classify contacts and populate the CRM with eligible entries.

    Extracts contacts from Gmail inbox, the Qdrant knowledge base, and
    Neo4j.  Delphi classifies each contact (with Clio-style KB cross-
    referencing for evidence), and only live customers, past customers,
    and sales leads are inserted.
    """
    _configure_logging(verbose)

    async def _populate() -> None:
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.knowledge_graph import KnowledgeGraph
        from ira.brain.qdrant_manager import QdrantManager
        from ira.brain.retriever import UnifiedRetriever
        from ira.data.crm import CRMDatabase
        from ira.message_bus import MessageBus
        from ira.systems.crm_populator import CRMPopulator

        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        graph = KnowledgeGraph()
        retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)
        bus = MessageBus()

        from ira.agents.delphi import Delphi
        delphi = Delphi(retriever=retriever, bus=bus)

        crm = CRMDatabase()
        await crm.create_tables()

        sources = None if source == "all" else [source]

        populator = CRMPopulator(delphi=delphi, crm=crm, dry_run=dry_run)

        mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
        console.print(Panel(
            f"Mode: {mode_label}\nSources: {source}\n\n"
            "Delphi will classify each contact (with KB evidence) as:\n"
            "  [green]LIVE_CUSTOMER[/green] | [green]PAST_CUSTOMER[/green] | "
            "[green]LEAD_WITH_INTERACTIONS[/green] | [green]LEAD_NO_INTERACTIONS[/green]\n"
            "  [red]VENDOR[/red] | [red]PARTNER[/red] | [red]OWN_COMPANY[/red] | [red]OTHER[/red] → rejected",
            title="CRM Population Pipeline",
            border_style="cyan",
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Extracting, cross-referencing, and classifying contacts..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("populate", total=None)
            result = await populator.populate(sources)

        stats = result["stats"]
        table = Table(title="Population Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")

        table.add_row("Total extracted", str(stats["total_extracted"]))
        table.add_row("Classified", str(stats["classified"]))
        table.add_row("Inserted into CRM", str(stats["inserted"]))
        table.add_row("Skipped (duplicate)", str(stats["skipped_duplicate"]))
        table.add_row("Skipped (rejected)", str(stats["skipped_rejected"]))
        table.add_row("Skipped (no email)", str(stats["skipped_no_email"]))
        table.add_row("Errors", str(stats["errors"]))

        console.print(table)

        classifications = result.get("classifications", [])
        if classifications:
            console.print(f"\n[dim]Classification details ({len(classifications)} contacts):[/dim]")
            ct_table = Table(show_header=True)
            ct_table.add_column("Email", style="cyan", width=30)
            ct_table.add_column("Company", width=20)
            ct_table.add_column("Type", width=24)
            ct_table.add_column("Conf", width=6)
            ct_table.add_column("Reasoning", width=50)

            for c in classifications:
                ct = c.get("contact_type", "?")
                style = "green" if ct in ("LIVE_CUSTOMER", "PAST_CUSTOMER", "LEAD_WITH_INTERACTIONS", "LEAD_NO_INTERACTIONS") else "red"
                ct_table.add_row(
                    c.get("email", "?")[:30],
                    (c.get("company") or "")[:20],
                    f"[{style}]{ct}[/{style}]",
                    c.get("confidence", "?"),
                    (c.get("reasoning") or "")[:50],
                )

            console.print(ct_table)

    _run(_populate())


crm_app = typer.Typer(help="CRM viewer — list, search, inspect, and manage contacts.")
app.add_typer(crm_app, name="crm")


async def _resolve_company(crm: Any, company_id: str | None) -> str:
    """Resolve a company_id to a name, with caching across a single command."""
    if not company_id:
        return ""
    if not hasattr(_resolve_company, "_cache"):
        _resolve_company._cache = {}
    if company_id in _resolve_company._cache:
        return _resolve_company._cache[company_id]
    comp = await crm.get_company(company_id)
    name = comp.name if comp else ""
    _resolve_company._cache[company_id] = name
    return name


def _type_style(ct: str) -> str:
    if ct in ("LIVE_CUSTOMER",):
        return "green bold"
    if ct in ("PAST_CUSTOMER",):
        return "yellow"
    if "LEAD" in ct:
        return "cyan"
    return "dim"


@crm_app.command("list")
def crm_list(
    contact_type: str = typer.Option("", "--type", "-t", help="Filter: LIVE_CUSTOMER, PAST_CUSTOMER, LEAD_WITH_INTERACTIONS, LEAD_NO_INTERACTIONS"),
    company: str = typer.Option("", "--company", "-c", help="Filter by company name (partial match)."),
    source: str = typer.Option("", "--source", help="Filter by source (e.g. gmail, kb:)."),
    sort: str = typer.Option("type", "--sort", "-s", help="Sort by: name, email, type, score, company."),
) -> None:
    """List all CRM contacts with filters and sorting."""

    async def _list() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        _resolve_company._cache = {}

        filters = {}
        if contact_type:
            filters["contact_type"] = contact_type

        contacts = await crm.list_contacts(filters or None)

        if not contacts:
            console.print("[yellow]No contacts found.[/yellow]")
            return

        rows = []
        for c in contacts:
            comp_name = await _resolve_company(crm, str(c.company_id) if c.company_id else None)
            ct = c.contact_type.value if c.contact_type else "UNCLASSIFIED"

            if company and company.lower() not in comp_name.lower():
                continue
            if source and source.lower() not in (c.source or "").lower():
                continue

            rows.append({
                "name": c.name or "",
                "email": c.email or "",
                "company": comp_name,
                "type": ct,
                "score": c.lead_score or 0,
                "source": c.source or "",
            })

        sort_key = sort.lower()
        if sort_key in ("name", "email", "company", "type", "source"):
            rows.sort(key=lambda r: r[sort_key].lower())
        elif sort_key == "score":
            rows.sort(key=lambda r: r["score"], reverse=True)

        by_type: dict[str, list] = {}
        for r in rows:
            by_type.setdefault(r["type"], []).append(r)

        type_order = ["LIVE_CUSTOMER", "PAST_CUSTOMER", "LEAD_WITH_INTERACTIONS", "LEAD_NO_INTERACTIONS", "UNCLASSIFIED"]
        for ct_name in type_order:
            group = by_type.get(ct_name, [])
            if not group:
                continue

            style = _type_style(ct_name)
            console.print(f"\n[{style}]{ct_name}[/{style}] ({len(group)})")

            table = Table(show_header=True, padding=(0, 1))
            table.add_column("#", style="dim", width=3)
            table.add_column("Name", width=22)
            table.add_column("Email", style="cyan", width=32)
            table.add_column("Company", width=22)
            table.add_column("Score", justify="right", width=5)
            table.add_column("Source", style="dim", width=14)

            for i, r in enumerate(group, 1):
                table.add_row(
                    str(i),
                    r["name"][:22],
                    r["email"][:32],
                    r["company"][:22],
                    f"{r['score']:.0f}",
                    r["source"][:14],
                )

            console.print(table)

        console.print(f"\n[bold]Showing {len(rows)} contacts[/bold]")

    _run(_list())


@crm_app.command("search")
def crm_search(
    query: str = typer.Argument(..., help="Search by name, email, or company."),
) -> None:
    """Search contacts by name, email, or company name."""

    async def _search() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        _resolve_company._cache = {}

        results = await crm.search_contacts(query)

        if not results:
            console.print(f"[yellow]No contacts matching '{query}'.[/yellow]")
            return

        table = Table(title=f"Search: '{query}' ({len(results)} results)", show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", width=24)
        table.add_column("Email", style="cyan", width=34)
        table.add_column("Type", width=22)
        table.add_column("Score", justify="right", width=5)

        for i, r in enumerate(results, 1):
            ct = r.get("contact_type", "?")
            style = _type_style(ct)
            table.add_row(
                str(i),
                (r.get("name") or "")[:24],
                (r.get("email") or "")[:34],
                f"[{style}]{ct}[/{style}]",
                f"{r.get('lead_score', 0):.0f}",
            )

        console.print(table)

    _run(_search())


@crm_app.command("show")
def crm_show(
    email: str = typer.Argument(..., help="Email address of the contact to inspect."),
) -> None:
    """Show full detail for a single contact: info, company, deals, interactions."""

    async def _show() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()

        contact = await crm.get_contact_by_email(email)
        if not contact:
            console.print(f"[red]Contact not found: {email}[/red]")
            raise typer.Exit(1)

        ct = contact.contact_type.value if contact.contact_type else "UNCLASSIFIED"
        style = _type_style(ct)

        console.print(Panel(
            f"[bold]{contact.name}[/bold]\n"
            f"Email: [cyan]{contact.email}[/cyan]\n"
            f"Type: [{style}]{ct}[/{style}]\n"
            f"Score: {contact.lead_score:.0f}\n"
            f"Role: {contact.role or '—'}\n"
            f"Source: {contact.source or '—'}\n"
            f"Created: {contact.created_at.strftime('%Y-%m-%d') if contact.created_at else '—'}",
            title="Contact",
            border_style="cyan",
        ))

        if contact.company_id:
            comp = await crm.get_company(str(contact.company_id))
            if comp:
                console.print(Panel(
                    f"[bold]{comp.name}[/bold]\n"
                    f"Region: {comp.region or '—'}\n"
                    f"Industry: {comp.industry or '—'}\n"
                    f"Website: {comp.website or '—'}",
                    title="Company",
                    border_style="blue",
                ))

        deals = await crm.get_deals_for_contact(str(contact.id))
        if deals:
            deal_table = Table(title=f"Deals ({len(deals)})", show_header=True)
            deal_table.add_column("Title", width=30)
            deal_table.add_column("Stage", width=14)
            deal_table.add_column("Value", justify="right", width=12)
            deal_table.add_column("Machine", width=16)

            for d in deals:
                deal_table.add_row(
                    (d.get("title") or "")[:30],
                    d.get("stage", "?"),
                    f"{d.get('currency', 'USD')} {d.get('value', 0):,.0f}",
                    (d.get("machine_model") or "—")[:16],
                )
            console.print(deal_table)
        else:
            console.print("[dim]No deals.[/dim]")

        interactions = await crm.get_interactions_for_contact(str(contact.id))
        if interactions:
            int_table = Table(title=f"Interactions ({len(interactions)})", show_header=True)
            int_table.add_column("Date", width=12)
            int_table.add_column("Channel", width=10)
            int_table.add_column("Dir", width=4)
            int_table.add_column("Subject", width=45)

            for ix in interactions[:15]:
                date_str = ix.get("created_at", "")
                if date_str and len(date_str) > 10:
                    date_str = date_str[:10]
                int_table.add_row(
                    date_str,
                    (ix.get("channel") or "")[:10],
                    (ix.get("direction") or "")[:4],
                    (ix.get("subject") or "")[:45],
                )
            console.print(int_table)
            if len(interactions) > 15:
                console.print(f"[dim]... and {len(interactions) - 15} more interactions[/dim]")
        else:
            console.print("[dim]No interactions.[/dim]")

    _run(_show())


@crm_app.command("stats")
def crm_stats() -> None:
    """Dashboard overview: contact counts, top companies, stale leads, pipeline."""

    async def _stats() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        _resolve_company._cache = {}

        contacts = await crm.list_contacts()
        companies = await crm.list_companies()

        by_type: dict[str, int] = {}
        by_company: dict[str, int] = {}
        for c in contacts:
            ct = c.contact_type.value if c.contact_type else "UNCLASSIFIED"
            by_type[ct] = by_type.get(ct, 0) + 1
            comp_name = await _resolve_company(crm, str(c.company_id) if c.company_id else None)
            if comp_name:
                by_company[comp_name] = by_company.get(comp_name, 0) + 1

        console.print(Panel(
            f"[bold]Contacts:[/bold] {len(contacts)}  |  "
            f"[bold]Companies:[/bold] {len(companies)}",
            title="CRM Overview",
            border_style="cyan",
        ))

        type_table = Table(title="Contacts by Type", show_header=True)
        type_table.add_column("Type", width=28)
        type_table.add_column("Count", justify="right", width=6)
        type_table.add_column("", width=40)

        max_count = max(by_type.values()) if by_type else 1
        type_order = ["LIVE_CUSTOMER", "PAST_CUSTOMER", "LEAD_WITH_INTERACTIONS", "LEAD_NO_INTERACTIONS", "UNCLASSIFIED"]
        for ct_name in type_order:
            count = by_type.get(ct_name, 0)
            if count == 0:
                continue
            bar_len = int((count / max_count) * 35)
            style = _type_style(ct_name)
            bar = f"[{style}]{'█' * bar_len}[/{style}]"
            type_table.add_row(f"[{style}]{ct_name}[/{style}]", str(count), bar)

        console.print(type_table)

        top_companies = sorted(by_company.items(), key=lambda x: -x[1])[:10]
        if top_companies:
            comp_table = Table(title="Top 10 Companies (by contact count)", show_header=True)
            comp_table.add_column("#", style="dim", width=3)
            comp_table.add_column("Company", width=28)
            comp_table.add_column("Contacts", justify="right", width=8)

            for i, (name, count) in enumerate(top_companies, 1):
                comp_table.add_row(str(i), name[:28], str(count))
            console.print(comp_table)

        stale = await crm.get_stale_leads(days=14)
        if stale:
            console.print(f"\n[yellow bold]Stale leads (>14 days, no interaction): {len(stale)}[/yellow bold]")
            stale_table = Table(show_header=True)
            stale_table.add_column("Name", width=24)
            stale_table.add_column("Email", style="cyan", width=32)
            for s in stale[:10]:
                stale_table.add_row(
                    (s.get("name") or "")[:24],
                    (s.get("email") or "")[:32],
                )
            console.print(stale_table)
            if len(stale) > 10:
                console.print(f"[dim]... and {len(stale) - 10} more[/dim]")

        pipeline = await crm.get_pipeline_summary()
        if pipeline.get("total_count", 0) > 0:
            console.print(f"\n[bold]Pipeline:[/bold] {pipeline['total_count']} deals | ${pipeline['total_value']:,.0f} total value")
            stages = pipeline.get("stages", {})
            if stages:
                pipe_table = Table(title="Deal Pipeline", show_header=True)
                pipe_table.add_column("Stage", width=16)
                pipe_table.add_column("Count", justify="right", width=6)
                pipe_table.add_column("Value", justify="right", width=14)
                for stage, data in stages.items():
                    if isinstance(data, dict):
                        pipe_table.add_row(stage, str(data.get("count", 0)), f"${data.get('total_value', 0):,.0f}")
                console.print(pipe_table)

    _run(_stats())


@crm_app.command("audit")
def crm_audit() -> None:
    """Audit CRM data quality: missing values, stale stages, zero-value deals."""

    async def _audit() -> None:
        from datetime import timedelta

        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()

        deals = await crm.list_deals()
        issues: list[str] = []
        zero_value = []
        missing_model = []
        stale_proposal = []
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(days=90)

        for d in deals:
            dd = d.to_dict() if hasattr(d, "to_dict") else d
            val = dd.get("value", 0)
            if val == 0 or val is None:
                zero_value.append(dd)
            if not dd.get("machine_model"):
                missing_model.append(dd)
            stage = dd.get("stage", "")
            updated = dd.get("updated_at")
            if stage == "PROPOSAL" and updated:
                updated_dt = datetime.fromisoformat(updated) if isinstance(updated, str) else updated
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                if updated_dt < stale_threshold:
                    stale_proposal.append(dd)

        console.print(Panel(
            f"[bold]Total deals:[/bold] {len(deals)}",
            title="CRM Data Quality Audit",
            border_style="yellow",
        ))

        if zero_value:
            table = Table(title=f"Deals with value=0 ({len(zero_value)})", show_header=True)
            table.add_column("Title", width=30)
            table.add_column("Stage", width=14)
            table.add_column("Contact ID", width=20)
            for dd in zero_value[:20]:
                table.add_row(
                    (dd.get("title") or "")[:30],
                    dd.get("stage", "?"),
                    (dd.get("contact_id") or "")[:20],
                )
            console.print(table)
            issues.append(f"{len(zero_value)} deals have value=0")

        if missing_model:
            console.print(f"\n[yellow]{len(missing_model)} deals missing machine_model[/yellow]")
            issues.append(f"{len(missing_model)} deals missing machine_model")

        if stale_proposal:
            table = Table(title=f"Stale PROPOSAL deals (>90 days, {len(stale_proposal)})", show_header=True)
            table.add_column("Title", width=30)
            table.add_column("Value", justify="right", width=12)
            table.add_column("Last Updated", width=20)
            for dd in stale_proposal[:20]:
                table.add_row(
                    (dd.get("title") or "")[:30],
                    f"{dd.get('value', 0):,.2f}",
                    (dd.get("updated_at") or "")[:20],
                )
            console.print(table)
            issues.append(f"{len(stale_proposal)} PROPOSAL deals stale >90 days")

        if not issues:
            console.print("[green bold]No data quality issues found.[/green bold]")
        else:
            console.print(f"\n[yellow bold]Issues found: {len(issues)}[/yellow bold]")
            for issue in issues:
                console.print(f"  - {issue}")

    _run(_audit())


@crm_app.command("companies")
def crm_companies() -> None:
    """List all companies with contact counts."""

    async def _companies() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()

        companies = await crm.list_companies()
        contacts = await crm.list_contacts()

        company_contacts: dict[str, list] = {}
        for c in contacts:
            cid = str(c.company_id) if c.company_id else ""
            company_contacts.setdefault(cid, []).append(c)

        rows = []
        for comp in companies:
            cid = str(comp.id)
            contact_list = company_contacts.get(cid, [])
            types = set()
            for c in contact_list:
                if c.contact_type:
                    types.add(c.contact_type.value)
            rows.append((comp.name, comp.region or "", len(contact_list), ", ".join(sorted(types))))

        rows.sort(key=lambda r: -r[2])

        table = Table(title=f"Companies ({len(rows)})", show_header=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Company", width=28)
        table.add_column("Region", width=14)
        table.add_column("Contacts", justify="right", width=8)
        table.add_column("Types", width=30)

        for i, (name, region, count, types) in enumerate(rows, 1):
            table.add_row(str(i), name[:28], region[:14], str(count), types[:30])

        console.print(table)

    _run(_companies())


@crm_app.command("override")
def crm_override(
    email: str = typer.Argument(..., help="Email address of the contact to reclassify."),
    new_type: str = typer.Argument(..., help="New type: LIVE_CUSTOMER, PAST_CUSTOMER, LEAD_WITH_INTERACTIONS, LEAD_NO_INTERACTIONS."),
) -> None:
    """Reclassify a contact's type."""

    async def _override() -> None:
        from ira.data.crm import CRMDatabase
        from ira.data.models import ContactType

        crm = CRMDatabase()
        await crm.create_tables()

        try:
            ct = ContactType(new_type)
        except ValueError:
            console.print(f"[red]Invalid type: {new_type}[/red]")
            console.print(f"Valid: {', '.join(t.value for t in ContactType)}")
            raise typer.Exit(1)

        contact = await crm.get_contact_by_email(email)
        if not contact:
            console.print(f"[red]Contact not found: {email}[/red]")
            raise typer.Exit(1)

        old = contact.contact_type.value if contact.contact_type else "UNCLASSIFIED"
        await crm.update_contact(str(contact.id), contact_type=ct)
        console.print(f"[green]{contact.name} ({email}): {old} -> {new_type}[/green]")

    _run(_override())


@crm_app.command("export")
def crm_export(
    contact_type: str = typer.Option("", "--type", "-t", help="Filter by contact type."),
    output: str = typer.Option("crm_export.csv", "--output", "-o", help="Output CSV file path."),
) -> None:
    """Export contacts to CSV."""

    async def _export() -> None:
        import csv as csv_mod
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        _resolve_company._cache = {}

        filters = {}
        if contact_type:
            filters["contact_type"] = contact_type

        contacts = await crm.list_contacts(filters or None)

        if not contacts:
            console.print("[yellow]No contacts to export.[/yellow]")
            return

        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv_mod.writer(f)
            writer.writerow(["Name", "Email", "Company", "Type", "Score", "Role", "Source", "Created"])

            for c in contacts:
                comp_name = await _resolve_company(crm, str(c.company_id) if c.company_id else None)
                ct = c.contact_type.value if c.contact_type else ""
                created = c.created_at.strftime("%Y-%m-%d") if c.created_at else ""
                writer.writerow([
                    c.name or "",
                    c.email or "",
                    comp_name,
                    ct,
                    f"{c.lead_score:.0f}",
                    c.role or "",
                    c.source or "",
                    created,
                ])

        console.print(f"[green]Exported {len(contacts)} contacts to {output}[/green]")

    _run(_export())


@crm_app.command("enrich")
def crm_enrich(
    contact_type: str = typer.Option("", "--type", "-t", help="Only enrich contacts of this type."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without writing."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Enrich CRM contacts with KB data: regions, machines, deals, scores.

    Searches the knowledge base for each contact's company to find
    machine orders, delivery dates, pricing, and regional data, then
    updates the CRM with deals, lead scores, and company details.
    """
    _configure_logging(verbose)

    async def _enrich() -> None:
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.qdrant_manager import QdrantManager
        from ira.data.crm import CRMDatabase
        from ira.systems.crm_enricher import CRMEnricher

        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        crm = CRMDatabase()
        await crm.create_tables()

        enricher = CRMEnricher(crm=crm, qdrant=qdrant, dry_run=dry_run)

        mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
        ct_label = contact_type or "all"
        console.print(Panel(
            f"Mode: {mode_label}\nType filter: {ct_label}\n\n"
            "Enrichment passes:\n"
            "  1. Company region & industry (from KB)\n"
            "  2. Contact roles (from KB)\n"
            "  3. Deals with machine models (from order books)\n"
            "  4. Deal values (from quotes/POs)\n"
            "  5. Lead scores & warmth levels",
            title="CRM Enrichment Pipeline",
            border_style="cyan",
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Enriching CRM contacts from knowledge base..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("enrich", total=None)
            result = await enricher.enrich_all(
                contact_type_filter=contact_type or None,
            )

        stats = result["stats"]
        table = Table(title="Enrichment Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")

        table.add_row("Contacts processed", str(stats["contacts_processed"]))
        table.add_row("Companies enriched", str(stats["companies_enriched"]))
        table.add_row("Roles found", str(stats["roles_found"]))
        table.add_row("Deals created", str(stats["deals_created"]))
        table.add_row("Deals with value", str(stats["deals_valued"]))
        table.add_row("Scores set", str(stats["scores_set"]))
        table.add_row("Errors", str(stats["errors"]))

        console.print(table)

    _run(_enrich())


# ── Pipeline ──────────────────────────────────────────────────────────────


@app.command()
def pipeline(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Print the current sales pipeline summary."""
    _configure_logging(verbose)

    async def _pipeline() -> None:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        summary = await crm.get_pipeline_summary()

        if not summary:
            console.print("[yellow]No pipeline data available.[/yellow]")
            return

        table = Table(title="Sales Pipeline Summary")
        table.add_column("Stage", style="cyan")
        table.add_column("Count", justify="right", style="green")
        table.add_column("Value", justify="right", style="yellow")

        stages = summary.get("stages", {})
        if isinstance(stages, dict):
            for stage, data in stages.items():
                if isinstance(data, dict):
                    table.add_row(
                        stage,
                        str(data.get("count", 0)),
                        f"${data.get('total_value', 0):,.0f}",
                    )
                else:
                    table.add_row(stage, str(data), "—")

        console.print(table)

        total_count = summary.get("total_count", 0)
        total_value = summary.get("total_value", 0)
        console.print(f"\n[bold]Total deals:[/bold] {total_count}  |  [bold]Total value:[/bold] ${total_value:,.0f}")

    _run(_pipeline())


# ── Health ────────────────────────────────────────────────────────────────


@app.command()
def health(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run the immune system health check on all services."""
    _configure_logging(verbose)

    async def _health() -> None:
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.knowledge_graph import KnowledgeGraph
        from ira.brain.qdrant_manager import QdrantManager
        from ira.systems.immune import ImmuneSystem

        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        graph = KnowledgeGraph()
        immune = ImmuneSystem(qdrant=qdrant, knowledge_graph=graph, embedding_service=embedding)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Running health checks..."),
            console=err_console,
            transient=True,
        ) as progress:
            progress.add_task("health", total=None)
            try:
                report = await immune.run_startup_validation()
            except (IraError, Exception) as exc:
                report = getattr(exc, "health_report", {})

        table = Table(title="System Health")
        table.add_column("Service", style="cyan", width=15)
        table.add_column("Status", width=10)
        table.add_column("Details")

        for service, info in report.items():
            status = info.get("status", "unknown")
            style = "green" if status == "healthy" else "red" if status == "unhealthy" else "yellow"
            details = info.get("error", info.get("latency_ms", ""))
            table.add_row(service, f"[{style}]{status}[/{style}]", str(details))

        console.print(table)

    _run(_health())


# ── Agents ────────────────────────────────────────────────────────────────


@app.command("agents")
def list_agents() -> None:
    """List all Pantheon agents with their roles."""
    pantheon, _shared = _build_pantheon()

    table = Table(title="Pantheon Agents")
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="cyan", width=14)
    table.add_column("Role", style="green", width=22)
    table.add_column("Description")

    for i, (name, agent) in enumerate(sorted(pantheon.agents.items()), 1):
        table.add_row(
            str(i),
            name,
            getattr(agent, "role", "—"),
            getattr(agent, "description", "—"),
        )

    console.print(table)
    console.print(f"\n[dim]{len(pantheon.agents)} agents registered.[/dim]")


# ── Audit commands ────────────────────────────────────────────────────────

audit_app = typer.Typer(help="Audit and evaluation commands.")
app.add_typer(audit_app, name="audit")


@audit_app.command("knowledge")
def audit_knowledge(
    limit: int = typer.Option(20, help="Max unresolved gaps to show"),
) -> None:
    """Audit knowledge gaps — show unresolved gaps and eval dataset scores."""

    async def _run() -> None:
        from ira.memory.metacognition import Metacognition

        console.print(Panel("[bold]Ira Knowledge Audit[/bold]", style="blue"))

        # 1. Unresolved gaps
        console.print("\n[bold cyan]Unresolved Knowledge Gaps[/bold cyan]\n")
        try:
            meta = Metacognition()
            await meta.initialize()
            gaps = await meta.get_unresolved_gaps(limit=limit)
            await meta.close()

            if not gaps:
                console.print("[green]No unresolved gaps found.[/green]")
            else:
                gap_table = Table(title=f"{len(gaps)} Unresolved Gaps")
                gap_table.add_column("#", style="dim", width=4)
                gap_table.add_column("Query", width=50)
                gap_table.add_column("State", width=12)
                gap_table.add_column("Date", width=20)
                for i, g in enumerate(gaps, 1):
                    gap_table.add_row(
                        str(g["id"]),
                        g["query"][:50],
                        g["state"],
                        g["created_at"][:19],
                    )
                console.print(gap_table)
        except (IraError, Exception) as exc:
            console.print(f"[red]Could not read gaps: {exc}[/red]")

        # 2. Eval dataset summary
        console.print("\n[bold cyan]Eval Dataset Summary[/bold cyan]\n")
        try:
            import json as _json
            eval_path = Path(__file__).resolve().parents[3] / "tests" / "eval_dataset.json"
            if eval_path.exists():
                data = _json.loads(eval_path.read_text())
                questions = data.get("questions", [])
                categories: dict[str, int] = {}
                for q in questions:
                    cat = q.get("category", "uncategorized")
                    categories[cat] = categories.get(cat, 0) + 1

                eval_table = Table(title=f"{len(questions)} Eval Questions")
                eval_table.add_column("Category", style="cyan")
                eval_table.add_column("Count", style="green", justify="right")
                for cat, count in sorted(categories.items()):
                    eval_table.add_row(cat, str(count))
                console.print(eval_table)
                console.print(
                    f"\n[dim]Run 'poetry run pytest tests/test_eval.py -v' "
                    f"for full RAGAS scores.[/dim]"
                )
            else:
                console.print("[yellow]tests/eval_dataset.json not found.[/yellow]")
        except (IraError, Exception) as exc:
            console.print(f"[red]Could not read eval dataset: {exc}[/red]")

    asyncio.run(_run())
