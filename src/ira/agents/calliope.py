"""Calliope — Writer agent.

Drafts and polishes all external communication: emails, reports,
proposals, and presentations.  Uses skills for polishing, translation,
and proposal generation.  Equipped with ReAct tools for proposal
drafting, text polishing, translation, and research delegation.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import ToolExecutionError
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("calliope_system")


class Calliope(BaseAgent):
    name = "calliope"
    role = "Chief Writer"
    description = "Drafts emails, reports, proposals, and all external communication"
    knowledge_categories = [
        "quotes_and_proposals",
        "project_case_studies",
        "presentations",
        "webcall transcripts",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="draft_proposal",
            description="Draft a business proposal for a customer.",
            parameters={
                "customer": "Customer name or company",
                "machine_model": "Machine model (optional)",
                "context": "Additional context or requirements (optional)",
            },
            handler=self._tool_draft_proposal,
        ))
        self.register_tool(AgentTool(
            name="polish_text",
            description="Polish and improve a piece of text.",
            parameters={
                "text": "The text to polish",
                "tone": "Desired tone (default: professional)",
            },
            handler=self._tool_polish_text,
        ))
        self.register_tool(AgentTool(
            name="translate_text",
            description="Translate text to a target language.",
            parameters={
                "text": "The text to translate",
                "target_language": "Target language (e.g. German, Hindi, Dutch)",
            },
            handler=self._tool_translate_text,
        ))
        self.register_tool(AgentTool(
            name="ask_clio",
            description="Delegate a research question to Clio, the research director.",
            parameters={"query": "Research question for Clio"},
            handler=self._tool_ask_clio,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_draft_proposal(
        self, customer: str, machine_model: str = "", context: str = "",
    ) -> str:
        return await self.use_skill(
            "draft_proposal",
            customer=customer,
            machine_model=machine_model,
            context=context,
        )

    async def _tool_polish_text(
        self, text: str, tone: str = "professional",
    ) -> str:
        return await self.use_skill("polish_text", text=text, tone=tone)

    async def _tool_translate_text(self, text: str, target_language: str) -> str:
        return await self.use_skill(
            "translate_text", text=text, language=target_language,
        )

    async def _tool_ask_clio(self, query: str) -> str:
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("clio")
        if agent is None:
            return "Clio agent not found."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            logger.warning("Clio delegation failed: %s", exc)
            return f"Clio error: {exc}"

    # ── handle ───────────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", ctx.get("draft_type", ""))

        if task == "proposal":
            return await self.use_skill(
                "draft_proposal",
                customer=ctx.get("recipient", ctx.get("customer", "")),
                machine_model=ctx.get("machine_model", ""),
                context=query,
            )

        if task == "polish":
            return await self.use_skill(
                "polish_text",
                text=query,
                tone=ctx.get("tone", "professional"),
            )

        if task == "translate":
            return await self.use_skill(
                "translate_text",
                text=query,
                language=ctx.get("language", ctx.get("target_language", "")),
            )

        if task == "meeting_notes":
            return await self.use_skill(
                "generate_meeting_notes",
                transcript=query,
                attendees=ctx.get("attendees", []),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)
