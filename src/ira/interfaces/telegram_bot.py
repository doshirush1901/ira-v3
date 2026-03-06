"""Telegram bot interface for Ira.

Provides conversational access to the Pantheon via Telegram, with:

* General query routing through Athena.
* Inline-keyboard draft approval/rejection flow (Calliope).
* Campaign management commands delegated to Hermes.
* Board meeting invocation via the BoardMeeting system.

Start with::

    python -m ira.interfaces.telegram_bot
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ira.config import get_settings

logger = logging.getLogger(__name__)

# ── Lazy service access ──────────────────────────────────────────────────
#
# Services are injected once via `start_bot()` rather than imported at
# module level, keeping the module importable without a running server.

_pantheon: Any = None
_board_meeting: Any = None
_crm: Any = None
_unified_context: Any = None

# Temporary store for drafts pending approval, keyed by chat_id.
_pending_drafts: dict[int, dict[str, str]] = {}


# ── Helpers ──────────────────────────────────────────────────────────────


def _truncate(text: str, limit: int = 4096) -> str:
    """Telegram messages are capped at 4096 chars."""
    if len(text) <= limit:
        return text
    return text[: limit - 4] + " ..."


def _draft_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve Draft", callback_data="draft_approve"),
                InlineKeyboardButton("Reject", callback_data="draft_reject"),
            ]
        ]
    )


# ── Command handlers ─────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and list available commands."""
    text = (
        "Hello! I'm *Ira*, the Machinecraft AI Pantheon.\n\n"
        "*Commands*\n"
        "/ask <query> — Ask any question\n"
        "/draft <context> — Generate an email draft for approval\n"
        "/campaign start <name> <email> — Start a drip campaign\n"
        "/campaign status <name> — Check campaign status\n"
        "/board <topic> — Run a board meeting\n"
        "/help — Show this message"
    )
    assert update.effective_message is not None
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ── /ask ─────────────────────────────────────────────────────────────────


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route a free-form query through the Pantheon."""
    assert update.effective_message is not None

    if not context.args:
        await update.effective_message.reply_text("Usage: /ask <your question>")
        return

    query = " ".join(context.args)
    user_id = str(update.effective_message.chat_id)
    await update.effective_message.reply_text("Thinking ...")

    try:
        ctx: dict[str, Any] = {"channel": "telegram"}
        if _unified_context is not None:
            ctx["cross_channel_history"] = _unified_context.recent_history(
                user_id, limit=10,
            )

        response = await _pantheon.process(query, ctx)

        if _unified_context is not None:
            _unified_context.record_turn(user_id, "telegram", query, response)

        await update.effective_message.reply_text(_truncate(response))
    except Exception:
        logger.exception("Pantheon query failed")
        await update.effective_message.reply_text(
            "Something went wrong while processing your request."
        )


# ── /draft  (inline keyboard) ───────────────────────────────────────────


async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate an email draft and present Approve / Reject buttons."""
    assert update.effective_message is not None

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /draft <context for the email>"
        )
        return

    draft_context = " ".join(context.args)
    await update.effective_message.reply_text("Drafting ...")

    calliope = _pantheon.get_agent("calliope")
    if calliope is None:
        await update.effective_message.reply_text("Calliope agent is not available.")
        return

    try:
        body = await calliope.handle(
            draft_context,
            {"draft_type": "email", "tone": "professional"},
        )
    except Exception:
        logger.exception("Calliope draft failed")
        await update.effective_message.reply_text("Failed to generate draft.")
        return

    chat_id = update.effective_message.chat_id
    _pending_drafts[chat_id] = {"context": draft_context, "body": body}

    await update.effective_message.reply_text(
        f"*Draft*\n\n{_truncate(body, 3900)}",
        parse_mode="Markdown",
        reply_markup=_draft_keyboard(),
    )


async def on_draft_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Approve / Reject button presses on a draft message."""
    query = update.callback_query
    assert query is not None
    await query.answer()

    chat_id = query.message.chat_id if query.message else None
    draft = _pending_drafts.pop(chat_id, None) if chat_id else None

    if query.data == "draft_approve":
        if draft:
            await query.edit_message_text(
                f"Draft *approved* and queued for sending.\n\n{_truncate(draft['body'], 3800)}",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("Draft approved (no cached copy found).")
    elif query.data == "draft_reject":
        await query.edit_message_text("Draft *rejected*. Use /draft to try again.", parse_mode="Markdown")


# ── /campaign ────────────────────────────────────────────────────────────


async def cmd_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage drip campaigns via Hermes.

    /campaign start <name> <contact_email>
    /campaign status <name>
    """
    assert update.effective_message is not None
    args = context.args or []

    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage:\n"
            "  /campaign start <name> <contact_email>\n"
            "  /campaign status <name>"
        )
        return

    sub = args[0].lower()
    hermes = _pantheon.get_agent("hermes")
    if hermes is None:
        await update.effective_message.reply_text("Hermes agent is not available.")
        return

    if sub == "start":
        if len(args) < 3:
            await update.effective_message.reply_text(
                "Usage: /campaign start <name> <contact_email>"
            )
            return

        campaign_name = args[1]
        contact_email = args[2]

        await update.effective_message.reply_text(
            f"Starting campaign *{campaign_name}* for {contact_email} ...",
            parse_mode="Markdown",
        )

        try:
            contact = await _crm.get_contact_by_email(contact_email)
            if contact is None:
                await update.effective_message.reply_text(
                    f"Contact {contact_email} not found in CRM."
                )
                return

            response = await hermes.handle(
                f"Design a 3-step drip campaign named '{campaign_name}' "
                f"for contact {contact.name} ({contact_email}) "
                f"at company {getattr(contact, 'company_id', 'unknown')}. "
                f"Lead score: {contact.lead_score}.",
                {"campaign_name": campaign_name, "contact_email": contact_email},
            )
            await update.effective_message.reply_text(
                f"*Campaign Plan — {campaign_name}*\n\n{_truncate(response, 3800)}",
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Campaign start failed")
            await update.effective_message.reply_text("Failed to start campaign.")

    elif sub == "status":
        campaign_name = " ".join(args[1:])
        await update.effective_message.reply_text(
            f"Checking status of *{campaign_name}* ...",
            parse_mode="Markdown",
        )

        try:
            campaigns = await _crm.list_campaigns()
            match = next(
                (c for c in campaigns if c.name.lower() == campaign_name.lower()),
                None,
            )

            if match is None:
                await update.effective_message.reply_text(
                    f"No campaign named '{campaign_name}' found."
                )
                return

            steps = await _crm.list_drip_steps(
                filters={"campaign_id": str(match.id)}
            )
            sent = sum(1 for s in steps if s.sent_at)
            replied = sum(1 for s in steps if s.reply_received)
            total = len(steps)

            status_text = (
                f"*{match.name}*\n"
                f"Status: {match.status.value if hasattr(match.status, 'value') else match.status}\n"
                f"Steps: {total} total, {sent} sent, {replied} replied"
            )

            hermes_analysis = await hermes.handle(
                f"Analyse the performance of campaign '{match.name}': "
                f"{total} steps, {sent} sent, {replied} replies. "
                f"Provide a brief assessment and recommendations.",
            )
            status_text += f"\n\n*Analysis*\n{_truncate(hermes_analysis, 3400)}"

            await update.effective_message.reply_text(
                _truncate(status_text), parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Campaign status failed")
            await update.effective_message.reply_text(
                "Failed to retrieve campaign status."
            )
    else:
        await update.effective_message.reply_text(
            f"Unknown sub-command '{sub}'. Use 'start' or 'status'."
        )


# ── /board ───────────────────────────────────────────────────────────────


async def cmd_board(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a board meeting on the given topic and return the minutes."""
    assert update.effective_message is not None

    if not context.args:
        await update.effective_message.reply_text("Usage: /board <topic>")
        return

    topic = " ".join(context.args)
    await update.effective_message.reply_text(
        f"Convening board meeting on: *{_truncate(topic, 200)}* ...",
        parse_mode="Markdown",
    )

    try:
        minutes = await _board_meeting.run_meeting(topic)
    except Exception:
        logger.exception("Board meeting failed")
        await update.effective_message.reply_text(
            "The board meeting encountered an error."
        )
        return

    parts: list[str] = [f"*Board Meeting — {_truncate(topic, 100)}*\n"]

    parts.append("*Participants:* " + ", ".join(minutes.participants))

    for agent, contribution in minutes.contributions.items():
        parts.append(f"\n*{agent}*\n{_truncate(contribution, 600)}")

    parts.append(f"\n*Synthesis*\n{minutes.synthesis}")

    if minutes.action_items:
        items = "\n".join(f"  • {item}" for item in minutes.action_items)
        parts.append(f"\n*Action Items*\n{items}")

    full_text = "\n".join(parts)
    await update.effective_message.reply_text(
        _truncate(full_text), parse_mode="Markdown"
    )


# ── Fallback: plain text → Pantheon ──────────────────────────────────────


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route any non-command text through the Pantheon."""
    assert update.effective_message is not None
    text = update.effective_message.text or ""
    if not text.strip():
        return

    user_id = str(update.effective_message.chat_id)

    try:
        ctx: dict[str, Any] = {"channel": "telegram"}
        if _unified_context is not None:
            ctx["cross_channel_history"] = _unified_context.recent_history(
                user_id, limit=10,
            )

        response = await _pantheon.process(text, ctx)

        if _unified_context is not None:
            _unified_context.record_turn(user_id, "telegram", text, response)

        await update.effective_message.reply_text(_truncate(response))
    except Exception:
        logger.exception("Pantheon message handling failed")
        await update.effective_message.reply_text(
            "Something went wrong while processing your message."
        )


# ── Bot lifecycle ────────────────────────────────────────────────────────


async def start_bot(
    pantheon: Any,
    board_meeting: Any,
    crm: Any,
    unified_context: Any = None,
) -> Application:  # type: ignore[type-arg]
    """Build, configure, and return the Telegram Application.

    The caller is responsible for calling ``app.run_polling()`` or
    integrating with an existing asyncio loop.

    Parameters
    ----------
    pantheon:
        A fully initialised :class:`~ira.pantheon.Pantheon` instance.
    board_meeting:
        A fully initialised :class:`~ira.systems.board_meeting.BoardMeeting`.
    crm:
        A fully initialised :class:`~ira.data.crm.CRMDatabase`.
    unified_context:
        Optional :class:`~ira.context.UnifiedContextManager` for cross-channel state.
    """
    global _pantheon, _board_meeting, _crm, _unified_context  # noqa: PLW0603
    _pantheon = pantheon
    _board_meeting = board_meeting
    _crm = crm
    _unified_context = unified_context

    token = get_settings().telegram.bot_token.get_secret_value()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("campaign", cmd_campaign))
    app.add_handler(CommandHandler("board", cmd_board))
    app.add_handler(
        CallbackQueryHandler(on_draft_callback, pattern=r"^draft_(approve|reject)$")
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    return app


# ── Standalone entry point ───────────────────────────────────────────────


async def _bootstrap_and_run() -> None:
    """Full bootstrap for standalone execution (``python -m ...``)."""
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.data.crm import CRMDatabase
    from ira.message_bus import MessageBus
    from ira.pantheon import Pantheon
    from ira.systems.board_meeting import BoardMeeting

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)

    bus = MessageBus()
    pantheon = Pantheon(retriever=retriever, bus=bus)
    await pantheon.start()

    crm = CRMDatabase()
    await crm.create_tables()

    async def _agent_handler(name: str, topic: str) -> str:
        agent = pantheon.get_agent(name)
        if agent is None:
            return f"(Agent '{name}' not found)"
        return await agent.handle(topic)

    bm = BoardMeeting(agent_handler=_agent_handler)

    from ira.context import UnifiedContextManager

    unified_ctx = UnifiedContextManager()

    app = await start_bot(
        pantheon=pantheon, board_meeting=bm, crm=crm,
        unified_context=unified_ctx,
    )

    logger.info("Telegram bot starting ...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()  # type: ignore[union-attr]

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.updater.stop()  # type: ignore[union-attr]
        await app.stop()
        await app.shutdown()
        await graph.close()
        await pantheon.stop()


def main() -> None:
    asyncio.run(_bootstrap_and_run())


if __name__ == "__main__":
    main()
