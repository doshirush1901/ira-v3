"""Delphi — Email Classifier agent.

Classifies inbound emails by intent, urgency, and required action,
then routes them to the appropriate agent or workflow.
"""

from __future__ import annotations

import json
from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Delphi, the email classification specialist at Machinecraft.
You triage every inbound email.

For each email, determine:
1. intent: QUOTE_REQUEST, SUPPORT, GENERAL_INQUIRY, PARTNERSHIP,
   COMPLAINT, FOLLOW_UP, SPAM, INTERNAL
2. urgency: HIGH, MEDIUM, LOW
3. suggested_agent: which Pantheon agent should handle this
4. summary: one-line summary of the email

Return ONLY valid JSON:
{"intent": "", "urgency": "", "suggested_agent": "", "summary": ""}"""


class Delphi(BaseAgent):
    name = "delphi"
    role = "Email Classifier"
    description = "Classifies inbound emails by intent and urgency"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        raw = await self.call_llm(_SYSTEM_PROMPT, f"Email content:\n{query}")

        try:
            self._parse_json_response(raw)
        except (json.JSONDecodeError, ValueError):
            pass

        return raw
