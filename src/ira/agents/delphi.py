"""Delphi — Email Classifier agent.

Classifies inbound emails by intent, urgency, and required action,
then routes them to the appropriate agent or workflow.
"""

from __future__ import annotations

import json
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

_SYSTEM_PROMPT = load_prompt("delphi_system")


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
