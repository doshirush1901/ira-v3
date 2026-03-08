#!/usr/bin/env python3
"""Ask Ira with live streaming progress — Manus-style agent animation.

Usage:
    python scripts/ask_ira.py "What do you know about Machinecraft?"
    python scripts/ask_ira.py  # interactive mode

Connects to the /api/query/stream SSE endpoint and renders a live
Rich display showing which agents are working, their status, and
the final synthesized answer.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from itertools import cycle

import httpx
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

IRA_URL = "http://localhost:8000"
USER_ID = "rushabh_doshi"

console = Console()

AGENT_ICONS: dict[str, str] = {
    "athena": "🦉", "clio": "📚", "prometheus": "🔥", "plutus": "💰",
    "hermes": "📬", "hephaestus": "🔨", "themis": "⚖️", "calliope": "✍️",
    "tyche": "🎲", "delphi": "🔮", "sphinx": "❓", "vera": "✅",
    "sophia": "🪞", "iris": "🌐", "mnemosyne": "🧠", "nemesis": "🎯",
    "arachne": "🕸️", "alexandros": "📜", "hera": "📦", "atlas": "📋",
    "asclepius": "🏥", "chiron": "🏹", "cadmus": "📰", "quotebuilder": "📄",
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class PipelineState:
    """Mutable state shared between the SSE reader and the display refresher."""

    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.phase: str = "Connecting..."
        self.t0: float = time.monotonic()
        self.agent_start_times: dict[str, float] = {}
        self.final_response: str | None = None
        self.final_agents: list[str] | None = None
        self.done: bool = False
        self.error: str | None = None
        self._spinner = cycle(SPINNER_FRAMES)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    @property
    def spinner(self) -> str:
        return next(self._spinner)

    def find_agent(self, name: str) -> dict | None:
        for a in self.agents:
            if a["name"] == name:
                return a
        return None

    def build_display(self) -> Panel:
        sp = self.spinner
        elapsed = self.elapsed
        lines: list[Text] = []

        header = Text()
        if self.done:
            header.append(" ✓ ", style="bold green")
            header.append(f"Completed in {elapsed:.1f}s", style="bold white")
        else:
            header.append(f" {sp} ", style="bold cyan")
            header.append(self.phase, style="bold white")
            header.append(f"  {elapsed:.0f}s", style="dim")
        lines.append(header)
        lines.append(Text(""))

        for agent in self.agents:
            name = agent["name"]
            status = agent["status"]
            role = agent.get("role", "")
            icon = AGENT_ICONS.get(name, "🤖")
            dur = agent.get("duration", "")
            dur_str = f" ({dur})" if dur else ""
            role_str = f" — {role}" if role else ""

            line = Text()
            if status == "working":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold yellow")
                line.append(role_str, style="dim")
                line.append(f"  {sp} thinking...", style="yellow")
            elif status == "done":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold green")
                line.append(role_str, style="dim")
                line.append(f"  ✓{dur_str}", style="green")
            elif status == "synthesizing":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold magenta")
                line.append(f"  {sp} synthesizing...", style="magenta")
            elif status == "routing":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold blue")
                line.append(f"  {sp} routing query...", style="blue")
            elif status == "timeout":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold red")
                line.append(f"  ✗ timed out{dur_str}", style="red")
            elif status == "error":
                line.append(f"  {icon} ", style="bold")
                line.append(name, style="bold red")
                line.append(f"  ✗ error{dur_str}", style="red")
            lines.append(line)

        if not self.agents and not self.done:
            lines.append(Text(f"  {sp} Waiting for pipeline...", style="dim italic"))

        return Panel(
            Group(*lines),
            title="[bold blue]Ira — Agent Pipeline[/bold blue]",
            border_style="green" if self.done else "blue",
            padding=(0, 1),
        )


def parse_sse_lines(buffer: str) -> tuple[list[tuple[str, str]], str]:
    """Parse SSE buffer into events and return remaining buffer.

    SSE uses ``\\r\\n`` line endings and ``\\r\\n\\r\\n`` as event delimiters.
    """
    normalized = buffer.replace("\r\n", "\n").replace("\r", "\n")

    last_complete = normalized.rfind("\n\n")
    if last_complete < 0:
        return [], buffer

    processable = normalized[:last_complete + 2]
    remainder = normalized[last_complete + 2:]

    events: list[tuple[str, str]] = []
    current_event = ""
    current_data = ""

    for line in processable.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            current_data = line[5:].strip()
        elif line.startswith(":"):
            continue
        elif line == "":
            if current_data:
                events.append((current_event or "message", current_data))
            current_event = ""
            current_data = ""

    return events, remainder


async def read_sse(state: PipelineState, query: str) -> None:
    """Read SSE events from Ira and update state."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{IRA_URL}/api/query/stream",
                json={"query": query, "user_id": USER_ID},
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code != 200:
                    state.error = f"HTTP {resp.status_code}"
                    state.done = True
                    return

                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    events, buffer = parse_sse_lines(buffer)

                    for event_type, data_str in events:
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        elapsed = state.elapsed

                        if event_type == "routing":
                            state.phase = "Athena routing query..."
                            if not state.find_agent("athena"):
                                state.agents.append({"name": "athena", "status": "routing", "role": "Orchestrator"})

                        elif event_type == "agent_started":
                            name = data.get("agent", "?")
                            role = data.get("role", "")
                            state.phase = f"{AGENT_ICONS.get(name, '🤖')} {name} is thinking..."
                            state.agent_start_times[name] = elapsed
                            existing = state.find_agent(name)
                            if existing:
                                existing["status"] = "working"
                                if role:
                                    existing["role"] = role
                            else:
                                state.agents.append({"name": name, "status": "working", "role": role})

                        elif event_type == "agent_done":
                            name = data.get("agent", "?")
                            preview = data.get("preview", "")
                            existing = state.find_agent(name)
                            if existing:
                                if "timed out" in preview:
                                    existing["status"] = "timeout"
                                elif preview.startswith("(") and "error" in preview.lower():
                                    existing["status"] = "error"
                                else:
                                    existing["status"] = "done"
                                start = state.agent_start_times.get(name)
                                if start is not None:
                                    existing["duration"] = f"{elapsed - start:.0f}s"

                            done_count = sum(1 for a in state.agents if a["status"] in ("done", "timeout", "error"))
                            state.phase = f"Agents: {done_count}/{len(state.agents)} complete"

                        elif event_type == "synthesizing":
                            state.phase = "Athena synthesizing responses..."
                            existing = state.find_agent("athena")
                            if existing:
                                existing["status"] = "synthesizing"
                            else:
                                state.agents.append({"name": "athena", "status": "synthesizing", "role": "Orchestrator"})

                        elif event_type == "final_answer":
                            state.final_response = data.get("response", "")
                            state.final_agents = data.get("agents_consulted")
                            state.phase = "Complete"

                        elif event_type == "error":
                            state.error = data.get("error", "Unknown error")

    except httpx.ConnectError:
        state.error = "Cannot connect to Ira. Is the server running on localhost:8000?"
    except httpx.ReadTimeout:
        state.error = "Request timed out after 300s."
    finally:
        state.done = True


async def stream_query(query: str) -> None:
    """Send a query to Ira's SSE endpoint and render live progress."""
    state = PipelineState()

    console.print()
    console.print(Panel(f"[bold]{query}[/bold]", title="[bold cyan]You[/bold cyan]", border_style="cyan", padding=(0, 2)))
    console.print()

    state.phase = "Sending query..."
    sse_task = asyncio.create_task(read_sse(state, query))

    with Live(state.build_display(), console=console, refresh_per_second=8, transient=True) as live:
        while not state.done:
            live.update(state.build_display())
            await asyncio.sleep(0.12)
        live.update(state.build_display())

    await sse_task

    if state.agents:
        for a in state.agents:
            if a["status"] == "working":
                a["status"] = "done"
        console.print(state.build_display())
        console.print()

    if state.error:
        console.print(f"[red bold]{state.error}[/red bold]")
    elif state.final_response:
        console.print(
            Panel(
                Markdown(state.final_response),
                title="[bold green]Ira[/bold green]",
                subtitle=f"[dim]agents: {', '.join(state.final_agents or [])} | {state.elapsed:.1f}s[/dim]",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        console.print("[yellow]No response received. The query may have timed out.[/yellow]")

    console.print()


def main() -> None:
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        asyncio.run(stream_query(query))
    else:
        console.print(
            Panel(
                "[bold]Ira[/bold] — Streaming Query Interface\n"
                "Type your question and press Enter. Type [bold]/quit[/bold] to exit.",
                title="[bold blue]Ask Ira[/bold blue]",
                border_style="blue",
            )
        )
        console.print()

        async def _interactive() -> None:
            while True:
                try:
                    query = console.input("[bold cyan]You:[/bold cyan] ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not query or query.lower() in ("/quit", "/exit", "/q"):
                    break
                await stream_query(query)

        asyncio.run(_interactive())

    console.print("[dim]Session ended.[/dim]")


if __name__ == "__main__":
    main()
