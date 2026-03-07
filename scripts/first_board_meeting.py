#!/usr/bin/env python3
"""First Pantheon Board Meeting — full business picture.

Runs a board meeting across all agents, rewrites the synthesis in
Tim Urban's Wait But Why style, and creates a Gmail draft to
rushabh@machinecraft.org.
"""

import asyncio
import base64
import json
import logging
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("board_meeting")


BOARD_TOPIC = """\
Complete Business Picture Review — First Pantheon Board Meeting

Every agent must contribute their domain expertise based on ALL available
data in the imports archive. Cover:

1. SALES & PIPELINE: Current deals, stages, conversion rates, stale leads,
   recent wins/losses, pipeline value
2. ORDER BOOK: Active machine orders, delivery timelines, production status
3. FINANCE: Revenue, outstanding receivables, payables, cash flow from
   Tally data, quote-to-order conversion
4. VENDOR & PROCUREMENT: Vendor outstandings, inventory levels, lead times,
   supply chain risks
5. PRODUCTION: Current manufacturing status, capacity utilisation, quality
   punch items
6. HR: Team status, headcount, any open positions
7. MARKETING: Lead generation, campaign performance, market research insights
8. FORECASTING: Revenue forecast, pipeline projections, win probability

Be specific. Cite actual numbers, company names, machine models, and dates
wherever the data supports it. No vague generalities.
"""

TIM_URBAN_REWRITE_PROMPT = """\
You are Tim Urban, the writer behind Wait But Why. You've just been handed
the minutes of a board meeting at Machinecraft — a company that builds
industrial packaging machines (pouch-fill-seal, automatic, rotary, etc.)
and sells them globally.

Your job: rewrite these board meeting minutes into a single, brilliant
Wait-But-Why-style email report. The recipient is Rushabh Doshi, the
founder and CEO.

Rules:
- Use Tim Urban's signature style: conversational, funny, uses analogies
  and metaphors, occasionally goes on tangents that circle back brilliantly
- Use his visual hierarchy: headers, bold for emphasis, occasional
  ALL CAPS for comedic effect
- Start with a hook that makes Rushabh want to read the whole thing
- Include ALL the substantive data — numbers, names, timelines — don't
  lose any facts in the style translation
- Organise into clear sections but make transitions entertaining
- End with a "So What Does This All Mean?" synthesis section
- Keep it under 3000 words but make every word count
- Format as HTML email (use <h2>, <p>, <b>, <br> tags) so it renders
  nicely in Gmail
- Sign off as "Your AI Board of Directors (who never need coffee breaks)"

Here are the raw board meeting minutes:

TOPIC: {topic}

AGENT CONTRIBUTIONS:
{contributions}

ATHENA'S SYNTHESIS:
{synthesis}
"""


async def run_board_meeting():
    """Bootstrap the Pantheon and run the board meeting."""
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

    logger.info("Starting board meeting with ALL agents...")
    async with pantheon:
        minutes = await pantheon.board_meeting(BOARD_TOPIC)

    logger.info(
        "Board meeting complete. %d agents contributed.",
        len(minutes.contributions),
    )
    return minutes


async def rewrite_tim_urban(minutes):
    """Rewrite the board meeting output in Tim Urban's style via GPT-4.1."""
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    api_key = settings.llm.openai_api_key.get_secret_value()

    contributions_text = "\n\n".join(
        f"--- {agent.upper()} ({agent}) ---\n{response}"
        for agent, response in minutes.contributions.items()
    )

    prompt = TIM_URBAN_REWRITE_PROMPT.format(
        topic=minutes.topic,
        contributions=contributions_text,
        synthesis=minutes.synthesis,
    )

    logger.info("Sending to GPT-4.1 for Tim Urban rewrite...")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "model": "gpt-4.1",
                "temperature": 0.7,
                "max_tokens": 8000,
                "messages": [
                    {"role": "system", "content": "You are Tim Urban, writer of Wait But Why."},
                    {"role": "user", "content": prompt},
                ],
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]

    logger.info("Tim Urban rewrite complete (%d chars).", len(result))
    return result


async def create_gmail_draft(html_body: str, subject: str, to: str):
    """Create a Gmail draft using the project's OAuth credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from ira.config import get_settings

    settings = get_settings()
    token_path = Path(settings.google.token_path)
    creds_path = Path(settings.google.credentials_path)

    scopes = [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(html_body, "html")
    msg["to"] = to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )

    logger.info("Gmail draft created: %s", draft.get("id"))
    return draft


async def save_raw_minutes(minutes, tim_urban_html: str):
    """Save raw data for reference."""
    output_dir = Path("data/board_meetings")
    output_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    raw_path = output_dir / f"{ts}_raw_minutes.json"
    raw_path.write_text(json.dumps({
        "topic": minutes.topic,
        "participants": minutes.participants,
        "contributions": minutes.contributions,
        "synthesis": minutes.synthesis,
        "action_items": minutes.action_items,
    }, indent=2, default=str))

    html_path = output_dir / f"{ts}_tim_urban_report.html"
    html_path.write_text(tim_urban_html)

    logger.info("Saved raw minutes to %s", raw_path)
    logger.info("Saved Tim Urban report to %s", html_path)
    return raw_path, html_path


async def main():
    print("\n" + "=" * 60)
    print("  FIRST PANTHEON BOARD MEETING")
    print("  Complete Business Picture Review")
    print("=" * 60 + "\n")

    # 1. Run the board meeting
    minutes = await run_board_meeting()

    print(f"\n{'─' * 60}")
    print(f"  {len(minutes.contributions)} agents contributed")
    print(f"  Participants: {', '.join(minutes.participants)}")
    print(f"{'─' * 60}\n")

    # 2. Rewrite in Tim Urban style
    tim_urban_html = await rewrite_tim_urban(minutes)

    # 3. Save raw data
    raw_path, html_path = await save_raw_minutes(minutes, tim_urban_html)

    # 4. Create Gmail draft
    subject = "Your AI Board of Directors Just Had Their First Meeting"
    draft = await create_gmail_draft(
        html_body=tim_urban_html,
        subject=subject,
        to="rushabh@machinecraft.org",
    )

    print(f"\n{'=' * 60}")
    print(f"  DONE!")
    print(f"  Gmail draft created: {draft.get('id')}")
    print(f"  Raw minutes: {raw_path}")
    print(f"  HTML report: {html_path}")
    print(f"  Check your Gmail drafts folder!")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    asyncio.run(main())
