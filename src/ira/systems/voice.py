"""Voice system — response shaping by channel, recipient, and behavioral state.

The last step in Ira's response pipeline.  After an agent generates a raw
response, the VoiceSystem shapes it for the target channel and recipient —
adjusting formatting, tone, length, and style.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ira.config import get_settings
from ira.data.models import Contact, WarmthLevel
from ira.exceptions import LLMError
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


# ── channel profiles ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelProfile:
    max_length: int
    format_style: str
    tone_default: str
    supports_markdown: bool
    supports_html: bool


CHANNEL_PROFILES: dict[str, ChannelProfile] = {
    "TELEGRAM": ChannelProfile(
        max_length=2000,
        format_style="concise_markdown",
        tone_default="direct",
        supports_markdown=True,
        supports_html=False,
    ),
    "EMAIL": ChannelProfile(
        max_length=10000,
        format_style="formal_prose",
        tone_default="professional",
        supports_markdown=False,
        supports_html=True,
    ),
    "CLI": ChannelProfile(
        max_length=50000,
        format_style="technical",
        tone_default="informative",
        supports_markdown=True,
        supports_html=False,
    ),
    "API": ChannelProfile(
        max_length=100000,
        format_style="raw",
        tone_default="neutral",
        supports_markdown=False,
        supports_html=False,
    ),
}

_DEFAULT_PROFILE = ChannelProfile(
    max_length=50000,
    format_style="technical",
    tone_default="informative",
    supports_markdown=True,
    supports_html=False,
)

WARMTH_TONE: dict[str, str] = {
    "STRANGER": "formal and professional",
    "ACQUAINTANCE": "polite and slightly warm",
    "FAMILIAR": "friendly, use their first name",
    "WARM": "casual and personable, add brief personal touches",
    "TRUSTED": "direct and informal, light humor is welcome",
}

_CHANNEL_INSTRUCTIONS: dict[str, str] = {
    "TELEGRAM": "Use Markdown bold/italic for emphasis. Be concise. No greeting/closing unless the tone calls for it.",
    "EMAIL": "Include a greeting line and a professional closing. Use paragraphs. Be thorough.",
    "CLI": "Use code blocks for data. Use bullet points for lists. Be detailed and technical.",
}

_SHAPING_SYSTEM_PROMPT = load_prompt("voice_shaping")

_SHORT_RESPONSE_THRESHOLD = 200


class VoiceSystem:
    """Shapes Ira's responses based on channel, recipient, and behavioral modifiers."""

    def __init__(self) -> None:
        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

    async def shape_response(
        self,
        raw_response: str,
        channel: str,
        recipient: Contact | None = None,
        behavioral_modifiers: dict[str, str] | None = None,
    ) -> str:
        """Shape a raw agent response for the target channel and recipient."""
        modifiers = behavioral_modifiers or {}
        profile = CHANNEL_PROFILES.get(channel, _DEFAULT_PROFILE)

        # Short-circuit: API returns raw
        if channel == "API":
            return raw_response

        # Short-circuit: very short responses don't need reshaping
        if len(raw_response) <= _SHORT_RESPONSE_THRESHOLD and channel in ("TELEGRAM", "CLI"):
            return self._enforce_length(raw_response, profile.max_length)

        # Resolve tone
        tone = profile.tone_default
        if recipient is not None:
            warmth = _infer_warmth(recipient)
            tone = WARMTH_TONE.get(warmth, tone)

        # Behavioral modifiers
        addendum = modifiers.get("prompt_addendum", "")
        verbosity = modifiers.get("verbosity", "normal")
        max_length = profile.max_length
        if verbosity == "concise":
            max_length = min(max_length, max_length // 2)
        elif verbosity == "detailed":
            max_length = int(max_length * 1.2)

        channel_instructions = _CHANNEL_INSTRUCTIONS.get(channel, "Format appropriately.")

        # LLM reshaping
        shaped = await self._llm_reshape(
            raw_response, channel, profile.format_style, tone,
            max_length, addendum, channel_instructions,
        )

        return self._enforce_length(shaped, profile.max_length)

    async def _llm_reshape(
        self,
        text: str,
        channel: str,
        format_style: str,
        tone: str,
        max_length: int,
        behavioral_addendum: str,
        channel_specific_instructions: str,
    ) -> str:
        if not self._openai_key:
            return text

        system_prompt = _SHAPING_SYSTEM_PROMPT.format(
            channel=channel,
            format_style=format_style,
            tone=tone,
            max_length=max_length,
            behavioral_addendum=behavioral_addendum or "None",
            channel_specific_instructions=channel_specific_instructions,
        )

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (LLMError, Exception):
            logger.exception("Voice LLM reshaping failed — returning raw response")
            return text

    @staticmethod
    def _enforce_length(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text

        # Truncate at the last sentence boundary before the limit
        truncated = text[:max_length]
        last_period = truncated.rfind(". ")
        if last_period > max_length // 2:
            return truncated[: last_period + 1] + "..."
        return truncated[: max_length - 3] + "..."

    # ── style detection ───────────────────────────────────────────────────

    def detect_preferred_style(
        self,
        contact: Contact,
        interactions: list[dict[str, Any]] | None = None,
    ) -> dict[str, str | int]:
        """Analyze past interactions to determine a contact's preferred style."""
        interactions = interactions or []

        if not interactions:
            tech_industries = {"technology", "software", "engineering", "it", "tech"}
            industry = (contact.industry or "").lower()
            technical = "technical" if industry in tech_industries else "moderate"
            return {
                "formality": "formal",
                "detail_level": "normal",
                "technical_level": technical,
                "preferred_channel": "EMAIL",
                "avg_response_length": 0,
            }

        # Analyze outbound (Ira's responses)
        outbound = [i for i in interactions if i.get("direction") == "OUTBOUND"]
        inbound = [i for i in interactions if i.get("direction") == "INBOUND"]

        # Detail level from average outbound length
        avg_len = 0
        if outbound:
            lengths = [len(i.get("content", "")) for i in outbound]
            avg_len = sum(lengths) // len(lengths)

        if avg_len > 1000:
            detail_level = "detailed"
        elif avg_len < 300:
            detail_level = "brief"
        else:
            detail_level = "normal"

        # Technical level from code blocks / technical terms
        all_outbound_text = " ".join(i.get("content", "") for i in outbound)
        has_code = "```" in all_outbound_text or "def " in all_outbound_text
        technical_level = "technical" if has_code else "moderate"

        # Formality from inbound greeting style
        formality = "formal"
        for msg in inbound:
            content = msg.get("content", "").strip().lower()
            if content.startswith(("hi ", "hey ", "hello ", "yo ")):
                formality = "casual"
                break
            if content.startswith(("dear ", "respected ")):
                formality = "formal"
                break

        # Preferred channel
        channel_counts: dict[str, int] = {}
        for i in interactions:
            ch = i.get("channel", "EMAIL")
            channel_counts[ch] = channel_counts.get(ch, 0) + 1
        preferred_channel = max(channel_counts, key=channel_counts.get) if channel_counts else "EMAIL"  # type: ignore[arg-type]

        return {
            "formality": formality,
            "detail_level": detail_level,
            "technical_level": technical_level,
            "preferred_channel": preferred_channel,
            "avg_response_length": avg_len,
        }

    # ── formatting helpers ────────────────────────────────────────────────

    @staticmethod
    def format_for_email(
        text: str,
        recipient_name: str,
        subject: str = "",
        warmth: str = "STRANGER",
    ) -> str:
        """Wrap text in email formatting with greeting and closing."""
        if warmth in ("WARM", "TRUSTED"):
            first_name = recipient_name.split()[0] if recipient_name else "there"
            greeting = f"Hi {first_name},"
        elif warmth in ("FAMILIAR",):
            first_name = recipient_name.split()[0] if recipient_name else "there"
            greeting = f"Hello {first_name},"
        else:
            greeting = f"Dear {recipient_name},"

        return f"{greeting}\n\n{text}\n\nBest regards,\nIra\nMachinecraft AI Assistant"

    @staticmethod
    def format_for_telegram(text: str) -> str:
        """Ensure Markdown is valid for Telegram's MarkdownV2 parser."""
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Escape special chars that Telegram MarkdownV2 requires
        special = r"_[]()~`>#+-=|{}.!"
        for ch in special:
            text = text.replace(ch, f"\\{ch}")
        return text


def _infer_warmth(contact: Contact) -> str:
    """Best-effort warmth inference from a Contact object."""
    # Contact doesn't carry warmth directly; default to STRANGER.
    # When RelationshipMemory is wired in, the perception dict will
    # carry the real warmth level and callers should pass it explicitly.
    return WarmthLevel.STRANGER.value
