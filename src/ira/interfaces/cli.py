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


def _build_pantheon() -> Any:
    """Construct a Pantheon with minimal wiring for CLI use."""
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)
    bus = MessageBus()
    return Pantheon(retriever=retriever, bus=bus)


async def _build_pipeline(pantheon: Any) -> Any:
    """Construct a full RequestPipeline for CLI use."""
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.context import UnifiedContextManager
    from ira.data.crm import CRMDatabase
    from ira.memory.conversation import ConversationMemory
    from ira.memory.goal_manager import GoalManager
    from ira.memory.inner_voice import InnerVoice
    from ira.memory.metacognition import Metacognition
    from ira.memory.procedural import ProceduralMemory
    from ira.memory.relationship import RelationshipMemory
    from ira.pipeline import RequestPipeline
    from ira.systems.endocrine import EndocrineSystem
    from ira.systems.sensory import SensorySystem
    from ira.systems.voice import VoiceSystem

    graph = KnowledgeGraph()
    sensory = SensorySystem(knowledge_graph=graph)
    await sensory.create_tables()
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
    voice = VoiceSystem()
    endocrine = EndocrineSystem()
    crm = CRMDatabase()
    await crm.create_tables()
    unified_context = UnifiedContextManager()

    return RequestPipeline(
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
    )


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


def _build_email_processor(pantheon: Any, digestive: Any) -> Any:
    """Construct an EmailProcessor wired to the Pantheon's Delphi agent."""
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.data.crm import CRMDatabase
    from ira.interfaces.email_processor import EmailProcessor
    from ira.systems.sensory import SensorySystem

    graph = KnowledgeGraph()
    sensory = SensorySystem(knowledge_graph=graph)
    crm = CRMDatabase()
    delphi = pantheon.get_agent("delphi")
    return EmailProcessor(
        delphi=delphi,
        digestive=digestive,
        sensory=sensory,
        crm=crm,
    )


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
    """Interactive chat session with Ira."""
    _configure_logging(verbose)

    console.print(
        Panel(
            "[bold]Ira[/bold] — Machinecraft AI Pantheon\n"
            "Type your message and press Enter.  Use [bold]/quit[/bold] to exit.",
            title="Chat Session",
            border_style="blue",
        )
    )

    pantheon = _build_pantheon()

    async def _session() -> None:
        user_id = "cli-user"

        async with pantheon:
            pipeline = await _build_pipeline(pantheon)

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

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold green]Consulting agents..."),
                    console=err_console,
                    transient=True,
                ) as progress:
                    progress.add_task("thinking", total=None)
                    response = await pipeline.process_request(
                        raw_input=text,
                        channel="cli",
                        sender_id=user_id,
                    )

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

    pantheon = _build_pantheon()

    async def _ask() -> None:
        user_id = "cli-user"

        async with pantheon:
            pipeline = await _build_pipeline(pantheon)

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Thinking..."),
                console=err_console,
                transient=True,
            ) as progress:
                progress.add_task("thinking", total=None)
                response = await pipeline.process_request(
                    raw_input=query,
                    channel="cli",
                    sender_id=user_id,
                )

        console.print(Panel(Markdown(response), title="Ira", border_style="green"))

    _run(_ask())


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

    pantheon = _build_pantheon()

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

    pantheon = _build_pantheon()
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


# ── Ingestion ─────────────────────────────────────────────────────────────


@app.command()
def ingest(
    path: Optional[str] = typer.Argument(None, help="Path to ingest. Defaults to data/imports/."),
    force: bool = typer.Option(False, "--force", "-f", help="Re-ingest documents already in the vector store."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run document ingestion on a file or directory.

    Walks all subdirectories under the target path, ingests every supported
    file (PDF, XLSX, DOCX, CSV, TXT), and displays a live progress bar.
    Files that fail to parse are logged and skipped without crashing.
    """
    _configure_logging(verbose)

    target = path or "data/imports"
    target_path = Path(target)

    if not target_path.exists():
        console.print(f"[red]Path not found:[/red] {target_path}")
        raise typer.Exit(1)

    _digestive, ingestor, _qdrant = _build_digestive()

    files = ingestor.discover_files(str(target_path))
    if not files:
        console.print(f"[yellow]No supported files found under {target_path}.[/yellow]")
        raise typer.Exit(0)

    categories = {f["category"] for f in files}
    total_size_mb = sum(f["size"] for f in files) / (1024 * 1024)
    console.print(
        Panel(
            f"[bold]Path:[/bold]        {target_path}\n"
            f"[bold]Files:[/bold]       {len(files)}\n"
            f"[bold]Directories:[/bold] {len(categories)}\n"
            f"[bold]Total size:[/bold]  {total_size_mb:.1f} MB\n"
            f"[bold]Force:[/bold]       {'yes' if force else 'no'}",
            title="Ingestion Plan",
            border_style="blue",
        )
    )

    succeeded: list[dict[str, Any]] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []

    async def _ingest() -> None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=err_console,
        ) as progress:
            task = progress.add_task("Ingesting files", total=len(files))
            for file_info in files:
                file_path = file_info["path"]
                short_name = Path(file_path).name
                progress.update(task, description=f"[bold green]{short_name}")
                try:
                    n = await ingestor.ingest_file(file_info, force=force)
                    if n > 0:
                        succeeded.append({"path": file_path, "chunks": n, "category": file_info["category"]})
                    else:
                        skipped.append(file_path)
                except Exception as exc:
                    logger.exception("Failed to ingest %s", file_path)
                    failed.append({"path": file_path, "error": str(exc)})
                progress.advance(task)

    _run(_ingest())

    summary_table = Table(title="Ingestion Report")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green", justify="right")

    total_chunks = sum(s["chunks"] for s in succeeded)
    summary_table.add_row("Files processed", str(len(succeeded)))
    summary_table.add_row("Files skipped", str(len(skipped)))
    summary_table.add_row("Files failed", str(len(failed)))
    summary_table.add_row("Chunks created", str(total_chunks))

    console.print(summary_table)

    if succeeded:
        cat_counts: dict[str, int] = {}
        for s in succeeded:
            cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + s["chunks"]
        cat_table = Table(title="Chunks by Category")
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Chunks", style="green", justify="right")
        for cat, count in sorted(cat_counts.items()):
            cat_table.add_row(cat, str(count))
        console.print(cat_table)

    if failed:
        err_table = Table(title="Failed Files")
        err_table.add_column("#", style="dim", width=3)
        err_table.add_column("File", style="red")
        err_table.add_column("Error")
        for i, f in enumerate(failed, 1):
            err_table.add_row(str(i), f["path"], f["error"])
        console.print(err_table)

    ingestor.close()


# ── Dream ─────────────────────────────────────────────────────────────────


@app.command()
def dream(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Trigger a dream cycle and print the consolidation report."""
    _configure_logging(verbose)

    async def _dream() -> None:
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.knowledge_graph import KnowledgeGraph
        from ira.brain.qdrant_manager import QdrantManager
        from ira.brain.retriever import UnifiedRetriever
        from ira.memory.conversation import ConversationMemory
        from ira.memory.dream_mode import DreamMode
        from ira.memory.episodic import EpisodicMemory
        from ira.memory.long_term import LongTermMemory

        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        retriever = UnifiedRetriever(qdrant=qdrant, embedding_service=embedding)
        long_term = LongTermMemory()
        episodic = EpisodicMemory()
        conversation = ConversationMemory()

        dream_mode = DreamMode(
            long_term=long_term,
            episodic=episodic,
            conversation=conversation,
            retriever=retriever,
        )

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

    _run(_dream())


# ── Board meeting ─────────────────────────────────────────────────────────


@app.command()
def board(
    topic: str = typer.Argument(..., help="The topic for the board meeting."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run a Pantheon board meeting on the given topic."""
    _configure_logging(verbose)

    pantheon = _build_pantheon()

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

    pantheon = _build_pantheon()

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
            "IRA_EMAIL": "ira@machinecraft.org",
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
            except Exception as exc:
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
    pantheon = _build_pantheon()

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
