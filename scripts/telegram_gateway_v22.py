#!/usr/bin/env python3
"""
Telegram Gateway v22 — Connects Telegram to the full Pantheon pipeline.

Calls process_with_tools() directly with _progress_callback so all 14 agents
are visible in real-time ("Clio — Searching knowledge base", etc.).

Usage:
    python scripts/telegram_gateway_v22.py
"""
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("ira.telegram_v22")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("RUSHABH_TELEGRAM_ID", "") or os.environ.get("EXPECTED_CHAT_ID", "")

_MAX_HISTORY_CHARS = 8000
_TELEGRAM_MAX_LEN = 4096
_HISTORY_FILE = PROJECT_ROOT / "data" / "telegram_history.json"


def _load_histories() -> Dict[str, str]:
    try:
        if _HISTORY_FILE.exists():
            import json
            return json.loads(_HISTORY_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_histories(histories: Dict[str, str]):
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json
        _HISTORY_FILE.write_text(json.dumps(histories, ensure_ascii=False))
    except Exception:
        pass


_conversation_histories: Dict[str, str] = _load_histories()

AGENT_ICONS = {
    "Clio": "\U0001F4DA", "Iris": "\U0001F310", "Calliope": "\u270D\uFE0F",
    "Vera": "\u2705", "Sophia": "\U0001FA9E", "Mnemosyne": "\U0001F5C4\uFE0F",
    "Hermes": "\U0001F4E7", "Plutus": "\U0001F4B0", "Hephaestus": "\U0001F528",
    "Prometheus": "\U0001F52D", "Sphinx": "\u2753", "Nemesis": "\u2696\uFE0F",
    "Quotebuilder": "\U0001F4C4", "Delphi": "\U0001F52E", "Athena": "\U0001F9E0",
}


def _is_admin(chat_id: str) -> bool:
    return bool(ADMIN_CHAT_ID) and str(chat_id) == str(ADMIN_CHAT_ID)


async def _update_status(status_msg, text: str):
    """Edit the 'Thinking...' message, swallowing Telegram API errors."""
    try:
        await status_msg.edit_text(text)
    except Exception:
        pass


def _get_last_ira_response(history: str) -> str:
    """Extract Ira's most recent response from the conversation history."""
    parts = history.rsplit("Ira: ", 1)
    if len(parts) < 2:
        return ""
    last = parts[1]
    cut = last.find("\nUser: ")
    return last[:cut].strip() if cut != -1 else last.strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route incoming text through the full v22 Pantheon pipeline."""
    if not update.message or not update.message.text:
        return

    chat_id = str(update.effective_chat.id)
    message = update.message.text.strip()
    if not message:
        return

    user_id = f"telegram:{chat_id}"
    status_msg = await update.message.reply_text("Thinking...")

    history = _conversation_histories.get(chat_id, "")

    # --- Feedback detection: check if this message is a correction/praise ---
    previous_response = _get_last_ira_response(history)
    feedback_response = None
    try:
        from openclaw.agents.ira.src.brain.feedback_handler import (
            detect_feedback, handle_negative_feedback, handle_positive_feedback,
        )
        fb_type, fb_conf = detect_feedback(message, previous_response)
        if fb_type == "negative" and fb_conf >= 0.5:
            logger.info("Feedback detected: NEGATIVE (%.2f) — routing to Nemesis", fb_conf)
            feedback_response = handle_negative_feedback(
                user_message=message,
                previous_response=previous_response,
                generation_path="telegram_v22",
                chat_id=chat_id,
            )
        elif fb_type == "positive" and fb_conf >= 0.5:
            logger.info("Feedback detected: POSITIVE (%.2f)", fb_conf)
            handle_positive_feedback(
                user_message=message,
                previous_response=previous_response,
                generation_path="telegram_v22",
                chat_id=chat_id,
            )
    except Exception as e:
        logger.warning("Feedback detection error (non-fatal): %s", e)

    # Track (agent, activity) steps so we show "who is working on what" (Manus-style)
    _progress_steps: List[tuple] = []
    _ticker_running = True
    _t0 = time.time()

    def _build_status_text() -> str:
        elapsed = int(time.time() - _t0)
        header = f"Thinking… ({elapsed}s"
        if _progress_steps:
            header += f", {len(_progress_steps)} steps"
        header += ")"
        if not _progress_steps:
            return header
        icon_lines = []
        for a, act in _progress_steps[-8:]:
            icon = AGENT_ICONS.get(a, "\u25B8")
            icon_lines.append(f"{icon} {a} — {act}")
        return header + "\n" + "\n".join(icon_lines)

    async def _ticker_loop():
        """Update the status message every 3s with elapsed time so the user knows it's alive."""
        while _ticker_running:
            await asyncio.sleep(3)
            if not _ticker_running:
                break
            try:
                await _update_status(status_msg, _build_status_text())
            except Exception:
                pass

    ticker_task = asyncio.get_running_loop().create_task(_ticker_loop())

    def progress_callback(event):
        """Sync callback invoked by tool_orchestrator._emit_progress."""
        if isinstance(event, dict):
            agent = event.get("agent", "")
            activity = event.get("activity", "")
            if not agent and not activity:
                return
            step = (agent, activity or "Working…")
            if step in _progress_steps:
                return
            _progress_steps.append(step)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_update_status(status_msg, _build_status_text()))
            except RuntimeError:
                pass
        elif isinstance(event, str):
            pass

    ctx = {
        "channel": "telegram",
        "user_id": user_id,
        "is_internal": _is_admin(chat_id),
        "conversation_history": history,
        "mem0_context": "",
        "identity": None,
        "personality_context": "",
        "_progress_callback": progress_callback,
    }

    try:
        from openclaw.agents.ira.src.core.tool_orchestrator import process_with_tools

        response = await process_with_tools(
            message=message,
            channel="telegram",
            user_id=user_id,
            context=ctx,
        )
        elapsed = time.time() - _t0
        logger.info("Response in %.1fs for chat=%s (%d chars)", elapsed, chat_id, len(response or ""))
    except Exception as e:
        logger.error("Pipeline error: %s", e, exc_info=True)
        response = f"I encountered an error processing your message. Please try again.\n\nDebug: {str(e)[:200]}"
    finally:
        _ticker_running = False
        ticker_task.cancel()

    # Update conversation history (sliding window) and persist to disk
    history += f"\nUser: {message}\nIra: {response}"
    if len(history) > _MAX_HISTORY_CHARS:
        history = history[-_MAX_HISTORY_CHARS:]
    _conversation_histories[chat_id] = history
    _save_histories(_conversation_histories)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if not response:
        response = "I wasn't able to generate a response. Please try again."

    for chunk in _split_into_bubbles(response):
        await _send_formatted(update.message, chunk)
        await asyncio.sleep(0.3)


async def _send_formatted(message, text: str):
    """Send with Markdown formatting, falling back to plain text if Telegram rejects it."""
    clean = _sanitize_markdown(text)
    try:
        await message.reply_text(clean, parse_mode="Markdown")
    except Exception:
        try:
            await message.reply_text(text)
        except Exception:
            await message.reply_text(text[:_TELEGRAM_MAX_LEN])


def _sanitize_markdown(text: str) -> str:
    """Clean up GPT-4o markdown so Telegram's strict parser accepts it.

    Telegram Markdown v1 rules:
      *bold*  _italic_  `code`  [link](url)
    Common GPT outputs that break it:
      **bold** (double star)  — convert to *bold*
      __italic__ (double underscore) — convert to _italic_
      Unmatched * or _ — escape them
    """
    # Convert **bold** to *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Convert __italic__ to _italic_
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    # Remove ### / ## / # markdown headers (Telegram doesn't support them)
    text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)
    # Escape stray underscores inside words (e.g. variable_name) that would break italic
    text = re.sub(r"(?<=\w)_(?=\w)", r"\_", text)
    return text


def _split_into_bubbles(text: str, hard_limit: int = _TELEGRAM_MAX_LEN) -> List[str]:
    """Split response into short chat-style message bubbles.

    Each double-newline-separated paragraph becomes its own bubble.
    If a single paragraph exceeds the Telegram limit, it gets sub-split
    at single newlines, then at sentences.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    bubbles: List[str] = []
    for para in paragraphs:
        if len(para) <= hard_limit:
            bubbles.append(para)
        else:
            # Sub-split oversized paragraphs at single newlines
            sub = para.split("\n")
            current = ""
            for line in sub:
                candidate = f"{current}\n{line}".strip() if current else line
                if len(candidate) <= hard_limit:
                    current = candidate
                else:
                    if current:
                        bubbles.append(current)
                    current = line[:hard_limit]
            if current:
                bubbles.append(current)

    return bubbles


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ira v22 — Pantheon Pipeline\n\n"
        "Send any message to talk to Ira.\n\n"
        "Commands:\n"
        "  /help — This message\n"
        "  /start — This message\n"
        "  /clear — Reset conversation history\n"
        "  /correct <text> — Correct Ira's last response\n"
        "  /fix <text> — Same as /correct\n"
        "  /arachne_approve <id> — Approve content for distribution\n"
        "  /arachne_skip <id> — Skip/cancel scheduled content\n"
        "  /preview_outreach — Preview next drip batch (admin)\n"
        "  /send_outreach — Send the outreach batch (admin)\n"
    )


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    _conversation_histories.pop(chat_id, None)
    await update.message.reply_text("Conversation history cleared.")


async def handle_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /correct or /fix — explicit correction of Ira's last response."""
    chat_id = str(update.effective_chat.id)
    correction_text = " ".join(context.args) if context.args else ""
    if not correction_text:
        await update.message.reply_text("Usage: /correct <what was wrong and what's correct>")
        return

    history = _conversation_histories.get(chat_id, "")
    previous_response = _get_last_ira_response(history)

    try:
        from openclaw.agents.ira.src.brain.feedback_handler import handle_negative_feedback

        result = handle_negative_feedback(
            user_message=correction_text,
            previous_response=previous_response,
            generation_path="telegram_v22_command",
            chat_id=chat_id,
        )
        await update.message.reply_text(f"Got it \u2014 correction logged.\n\n{result}")
    except Exception as e:
        logger.warning("handle_correct error: %s", e)
        await update.message.reply_text(f"Correction noted, but had trouble processing: {e}")


async def handle_arachne_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /arachne_approve <item_id> — approve content for distribution."""
    chat_id = str(update.effective_chat.id)
    if ADMIN_CHAT_ID and chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Only the admin can approve content.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /arachne_approve <item_id>")
        return
    item_id = args[0]
    try:
        from openclaw.agents.ira.src.agents.arachne import handle_approval
        result = await handle_approval(item_id, action="approve")
        await update.message.reply_text(result)
    except Exception as e:
        logger.warning("arachne_approve failed: %s", e)
        await update.message.reply_text(f"Error: {e}")


async def handle_arachne_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /arachne_skip <item_id> — skip/cancel content."""
    chat_id = str(update.effective_chat.id)
    if ADMIN_CHAT_ID and chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("Only the admin can skip content.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /arachne_skip <item_id>")
        return
    item_id = args[0]
    try:
        from openclaw.agents.ira.src.agents.arachne import handle_approval
        result = await handle_approval(item_id, action="skip")
        await update.message.reply_text(result)
    except Exception as e:
        logger.warning("arachne_skip failed: %s", e)
        await update.message.reply_text(f"Error: {e}")


async def handle_preview_outreach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /preview_outreach — show next batch of drip drafts (no send). T1.6."""
    if not _is_admin(str(update.effective_chat.id)):
        await update.message.reply_text("Admin only.")
        return
    await update.message.reply_text("Checking outreach batch...")
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "openclaw" / "agents" / "ira"))
        from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
        emails = await get_hermes().preview_batch()
    except Exception as e:
        logger.warning("preview_outreach failed: %s", e)
        await update.message.reply_text(f"Error: {e}")
        return
    if not emails:
        await update.message.reply_text("No leads ready for outreach (timezone or daily limit). Try crm_drip_candidates in chat.")
        return
    lines = ["\u270d PREVIEW OUTREACH (drafts only):\n"]
    for i, e in enumerate(emails[:5], 1):
        lines.append(f"{i}. {e.get('company', '?')} ({e.get('country', '?')})")
        lines.append(f"   To: {e.get('to_email', '?')}")
        lines.append(f"   Subject: {e.get('subject', '')[:55]}")
        lines.append("")
    lines.append("Use /send_outreach to send this batch (admin only).")
    text = "\n".join(lines)
    if len(text) > _TELEGRAM_MAX_LEN:
        text = text[:_TELEGRAM_MAX_LEN - 50] + "\n... (truncated)"
    await update.message.reply_text(text)


async def handle_send_outreach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /send_outreach — run Hermes batch and send emails. T1.6."""
    if not _is_admin(str(update.effective_chat.id)):
        await update.message.reply_text("Admin only.")
        return
    await update.message.reply_text("Running outreach batch (sending)...")
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "openclaw" / "agents" / "ira"))
        from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
        result = await get_hermes().run_outreach_batch(dry_run=False)
    except Exception as e:
        logger.warning("send_outreach failed: %s", e)
        await update.message.reply_text(f"Error: {e}")
        return
    status = result.get("status", "?")
    sent = result.get("sent", 0)
    batch_size = result.get("batch_size", 0)
    failed = result.get("failed", 0)
    msg = f"\u2705 Outreach batch complete. Sent: {sent}/{batch_size}. Failed: {failed}. Status: {status}."
    await update.message.reply_text(msg)


def main():
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    print()
    print("  Ira v22 Telegram Gateway")
    print(f"  Admin chat: {ADMIN_CHAT_ID or 'not set'}")
    print("  Starting...\n")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("start", handle_help))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("correct", handle_correct))
    app.add_handler(CommandHandler("fix", handle_correct))
    app.add_handler(CommandHandler("arachne_approve", handle_arachne_approve))
    app.add_handler(CommandHandler("arachne_skip", handle_arachne_skip))
    app.add_handler(CommandHandler("preview_outreach", handle_preview_outreach))
    app.add_handler(CommandHandler("send_outreach", handle_send_outreach))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("  Polling for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
