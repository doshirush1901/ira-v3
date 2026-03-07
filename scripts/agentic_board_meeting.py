#!/usr/bin/env python3
"""Post-Upgrade Board Meeting — showcasing the agentic transformation.

Runs a focused board meeting with key agents using their new ReAct loops,
rewrites in Tim Urban style, and sends as a Gmail draft.
"""

import asyncio
import base64
import json
import logging
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agentic_board")

KEY_AGENTS = [
    "prometheus", "plutus", "hephaestus", "atlas", "clio",
]

BOARD_TOPIC = """\
Post-Upgrade Board Meeting — The Pantheon Has Evolved

This is the FIRST board meeting since the agentic transformation. You now
have a ReAct reasoning loop, memory access, and domain-specific tools.

USE YOUR TOOLS to gather real data before responding. Search the knowledge
base, check the CRM, recall memories. Be specific — cite actual numbers,
company names, machine models, and dates.

Cover your domain:
- SALES (Prometheus): Pipeline, deals, stale leads, conversion rates
- FINANCE (Plutus): Pricing, quotes, revenue, margins
- MARKETING (Hermes): Campaigns, leads, market research
- PRODUCTION (Hephaestus): Machine specs, schedules, capacity
- HR (Themis): Team, headcount, org structure
- FORECASTING (Tyche): Revenue projections, pipeline health
- PROCUREMENT (Hera): Vendors, lead times, supply risks
- QUALITY (Asclepius): Punch items, quality trends
- PROJECTS (Atlas): Active projects, milestones, overdue items
- LIBRARY (Alexandros): Archive status, undigested files
- RESEARCH (Clio): Key knowledge base findings
"""

TIM_URBAN_REWRITE_PROMPT = """\
You are Tim Urban, the writer behind Wait But Why. You've just been handed
the minutes of a board meeting at Machinecraft — a company that builds
industrial packaging machines (pouch-fill-seal, automatic, rotary, etc.)
and sells them globally.

IMPORTANT CONTEXT: This is the FIRST board meeting since Machinecraft's AI
system (called "Ira") underwent a massive upgrade. The 24 AI agents that
make up Ira's "Pantheon" were just transformed from simple chatbots into
actual agentic systems with reasoning loops, memory, and tools. Before the
upgrade, they were "prompt in, text out" bots scoring 2.8/10 on average.
Now they can search databases, recall memories, check CRM data, consult
each other, and reason step-by-step before answering.

Your job: rewrite these board meeting minutes into a single, brilliant
Wait-But-Why-style email report for Rushabh Doshi, the founder and CEO.

Rules:
- Tim Urban's signature style: conversational, funny, analogies, metaphors,
  tangents that circle back brilliantly
- Visual hierarchy: headers, bold, occasional ALL CAPS for comedic effect
- Start with a hook about the upgrade — these agents just got superpowers
- Include ALL substantive data — numbers, names, timelines
- Note when agents actually USED their tools vs just talking
- End with "The Verdict: Did the Upgrade Work?" — honest assessment
- Under 3000 words, every word counts
- Format as HTML email (<h2>, <p>, <b>, <br> tags)
- Sign off as "Your AI Board of Directors (now with actual superpowers)"

TOPIC: {topic}

AGENT CONTRIBUTIONS:
{contributions}

ATHENA'S SYNTHESIS:
{synthesis}
"""


async def run_board_meeting():
    """Bootstrap the Pantheon with full services and run the meeting."""
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.pricing_engine import PricingEngine
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.config import get_settings
    from ira.data.crm import CRMDatabase
    from ira.data.quotes import QuoteManager
    from ira.memory.long_term import LongTermMemory
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon
    from ira.skills.handlers import bind_services as bind_skill_services

    settings = get_settings()

    logger.info("Bootstrapping services...")
    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()

    mem0_client = None
    mem0_key = settings.memory.api_key.get_secret_value()
    if mem0_key:
        try:
            from mem0 import MemoryClient
            mem0_client = MemoryClient(api_key=mem0_key)
        except Exception:
            pass

    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph, mem0_client=mem0_client)
    bus = MessageBus()

    crm = CRMDatabase()
    quotes = QuoteManager(session_factory=crm.session_factory)
    pricing_engine = PricingEngine(retriever=retriever, crm=crm)

    pantheon = Pantheon(retriever=retriever, bus=bus)

    shared_services = {
        "crm": crm,
        "quotes": quotes,
        "pricing_engine": pricing_engine,
        "retriever": retriever,
    }
    pantheon.inject_services(shared_services)
    bind_skill_services(shared_services)

    long_term = LongTermMemory()
    pantheon.inject_services({
        "long_term_memory": long_term,
        "pantheon": pantheon,
    })

    # Cap iterations and disable cross-agent delegation to prevent OOM
    for agent in pantheon.agents.values():
        agent.max_iterations = 2
        agent.tools = [t for t in agent.tools if t.name != "ask_agent"]

    logger.info("Starting board meeting with %d key agents (sequential)...", len(KEY_AGENTS))
    async with pantheon:
        # Run agents sequentially to avoid OOM from parallel execution
        from ira.data.models import BoardMeetingMinutes
        contributions: dict[str, str] = {}
        for agent_name in KEY_AGENTS:
            agent = pantheon.get_agent(agent_name)
            if agent is None:
                continue
            logger.info("Agent %s contributing...", agent_name)
            try:
                response = await agent.handle(BOARD_TOPIC)
                contributions[agent_name] = response
            except Exception:
                logger.exception("Agent %s failed", agent_name)
                contributions[agent_name] = f"(Agent {agent_name} encountered an error)"

        synthesis = await pantheon.get_agent("athena").handle(
            BOARD_TOPIC, {"agent_responses": contributions},
        )
        minutes = BoardMeetingMinutes(
            topic=BOARD_TOPIC,
            participants=["athena"] + list(contributions.keys()),
            contributions=contributions,
            synthesis=synthesis,
        )

    logger.info(
        "Board meeting complete. %d agents contributed.",
        len(minutes.contributions),
    )
    return minutes


async def rewrite_tim_urban(minutes):
    """Rewrite the board meeting output in Tim Urban's style.

    Tries OpenAI first, falls back to Anthropic on any failure.
    """
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    openai_key = settings.llm.openai_api_key.get_secret_value()
    anthropic_key = settings.llm.anthropic_api_key.get_secret_value()

    contributions_text = "\n\n".join(
        f"--- {agent.upper()} ---\n{response}"
        for agent, response in minutes.contributions.items()
    )

    prompt = TIM_URBAN_REWRITE_PROMPT.format(
        topic=minutes.topic,
        contributions=contributions_text,
        synthesis=minutes.synthesis,
    )

    system_msg = "You are Tim Urban, writer of Wait But Why."

    if openai_key:
        logger.info("Trying OpenAI for Tim Urban rewrite (%d chars)...", len(prompt))
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4.1",
                        "temperature": 0.7,
                        "max_tokens": 8000,
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                result = resp.json()["choices"][0]["message"]["content"]
                logger.info("Tim Urban rewrite complete via OpenAI (%d chars).", len(result))
                return result
        except Exception:
            logger.warning("OpenAI failed for rewrite — falling back to Anthropic")

    if anthropic_key:
        logger.info("Using Anthropic for Tim Urban rewrite (%d chars)...", len(prompt))
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": settings.llm.anthropic_model,
                    "max_tokens": 8000,
                    "system": system_msg,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            result = resp.json()["content"][0]["text"]
            logger.info("Tim Urban rewrite complete via Anthropic (%d chars).", len(result))
            return result

    raise RuntimeError("No LLM provider available for rewrite")


def send_gmail(html_body: str, subject: str, to: str):
    """Send an email via Gmail API."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from ira.config import get_settings

    settings = get_settings()
    token_path = Path(settings.google.token_path)

    scopes = [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(html_body, "html")
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    result = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )

    logger.info("Email SENT: %s (ID: %s)", to, result.get("id"))
    return result


async def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/board_meetings")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  AGENTIC BOARD MEETING — Post-Upgrade Debut")
    print(f"  {len(KEY_AGENTS)} key agents, ReAct loops, tools")
    print("=" * 60 + "\n")

    minutes = await run_board_meeting()

    print(f"\n{'─' * 60}")
    print(f"  {len(minutes.contributions)} agents contributed")
    print(f"  Participants: {', '.join(minutes.participants)}")
    print(f"{'─' * 60}\n")

    raw_path = output_dir / f"{ts}_agentic_meeting.json"
    raw_path.write_text(json.dumps({
        "topic": minutes.topic,
        "participants": minutes.participants,
        "contributions": minutes.contributions,
        "synthesis": minutes.synthesis,
        "action_items": getattr(minutes, "action_items", []),
    }, indent=2, default=str))
    logger.info("Raw minutes saved: %s", raw_path)

    tim_urban_html = await rewrite_tim_urban(minutes)

    html_path = output_dir / f"{ts}_agentic_report.html"
    html_path.write_text(tim_urban_html)
    logger.info("HTML report saved: %s", html_path)

    subject = "Your AI Board Just Got Superpowers — Here's Their First Meeting"
    send_gmail(
        html_body=tim_urban_html,
        subject=subject,
        to="rushabh@machinecraft.org",
    )

    print(f"\n{'=' * 60}")
    print(f"  DONE!")
    print(f"  Email SENT to rushabh@machinecraft.org")
    print(f"  Subject: {subject}")
    print(f"  Raw minutes: {raw_path}")
    print(f"  HTML report: {html_path}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
