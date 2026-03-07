"""Cadmus -- CMO / Case Study agent.

Searches the knowledge base for relevant case studies, builds new
case studies from project data (with NDA-safe redaction), and drafts
LinkedIn posts grounded in Machinecraft's domain expertise.

Equipped with ReAct tools for case-study search, NDA compliance
checking, LinkedIn drafting, and cross-agent delegation to Atlas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.exceptions import ToolExecutionError
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("cadmus_system")


class Cadmus(BaseAgent):
    name = "cadmus"
    role = "CMO / Case Studies"
    description = "Case study creation, LinkedIn content, and marketing storytelling"
    knowledge_categories = [
        "project_case_studies",
        "presentations",
        "product_catalogues",
    ]

    # ── tool registration ────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="find_case_studies",
            description="Search the knowledge base for existing case studies and project references.",
            parameters={"query": "Search query for case studies"},
            handler=self._tool_find_case_studies,
        ))
        self.register_tool(AgentTool(
            name="build_case_study",
            description="Build a professional case study document for a project.",
            parameters={
                "project": "Project name or description",
                "nda_safe": "Whether to redact NDA-sensitive info ('true'/'false', default 'false')",
            },
            handler=self._tool_build_case_study,
        ))
        self.register_tool(AgentTool(
            name="draft_linkedin_post",
            description="Draft a LinkedIn post about a topic or based on case study text.",
            parameters={"case_study_text": "Topic or case study content to base the post on"},
            handler=self._tool_draft_linkedin_post,
        ))
        self.register_tool(AgentTool(
            name="check_nda_compliance",
            description="Check text for NDA-sensitive information (company names, deal values, confidential details).",
            parameters={"text": "Text to check for NDA compliance"},
            handler=self._tool_check_nda_compliance,
        ))
        self.register_tool(AgentTool(
            name="ask_atlas",
            description="Delegate a question to Atlas, the project manager agent.",
            parameters={"query": "Question for Atlas"},
            handler=self._tool_ask_atlas,
        ))

    # ── tool handlers ────────────────────────────────────────────────────

    async def _tool_find_case_studies(self, query: str) -> str:
        return await self.find_case_studies(query)

    async def _tool_build_case_study(self, project: str, nda_safe: str = "false") -> str:
        ctx = {"nda_safe": nda_safe.lower() in ("true", "1", "yes")}
        return await self.build_case_study(project, ctx)

    async def _tool_draft_linkedin_post(self, case_study_text: str) -> str:
        return await self.draft_linkedin_post(case_study_text)

    async def _tool_check_nda_compliance(self, text: str) -> str:
        prompt = (
            "Analyse the following text for NDA-sensitive information.\n"
            "Identify:\n"
            "1. Specific company names (other than Machinecraft)\n"
            "2. Deal values, contract amounts, or pricing details\n"
            "3. Proprietary technical specifications\n"
            "4. Confidential project timelines or internal processes\n\n"
            "Return a JSON object with keys: 'is_safe' (bool), 'issues' (list of strings), "
            "'redacted_version' (the text with sensitive items replaced by generic descriptors).\n\n"
            f"TEXT:\n{text[:6000]}"
        )
        raw = await self.call_llm(_SYSTEM_PROMPT, prompt, temperature=0.1)
        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                return json.dumps(parsed, default=str)
        except (json.JSONDecodeError, ValueError):
            pass
        return raw

    async def _tool_ask_atlas(self, query: str) -> str:
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent("atlas")
        if agent is None:
            return "Atlas agent not found."
        try:
            return await agent.handle(query)
        except (ToolExecutionError, Exception) as exc:
            logger.warning("Atlas delegation failed: %s", exc)
            return f"Atlas error: {exc}"

    # ── existing methods ─────────────────────────────────────────────────

    async def find_case_studies(self, query: str) -> str:
        results = await self.search_domain_knowledge(query, limit=10)
        if not results:
            return "No case studies found matching that query."

        lines = [f"Found {len(results)} relevant knowledge-base entries:\n"]
        for r in results:
            source = r.get("source", "unknown")
            content = r.get("content", "")[:600]
            lines.append(f"- [{source}] {content}")
        return "\n".join(lines)

    async def build_case_study(self, project_name: str, context: dict) -> str:
        kb_results = await self.search_domain_knowledge(project_name, limit=12)
        kb_context = self._format_context(kb_results)

        nda_safe = context.get("nda_safe", False)
        nda_instruction = (
            "IMPORTANT: This case study must be NDA-safe. Replace the actual "
            "customer name with a generic descriptor (e.g. 'a leading Middle-Eastern "
            "construction firm'). Remove any proprietary pricing, contract values, "
            "or confidential technical details."
            if nda_safe
            else "You may use the full customer and project name."
        )

        prompt = (
            f"Build a professional case study for project: {project_name}\n\n"
            f"{nda_instruction}\n\n"
            "Structure the case study with these sections:\n"
            "1. Challenge — what problem the customer faced\n"
            "2. Solution — what Machinecraft delivered\n"
            "3. Results — measurable outcomes and benefits\n"
            "4. Key machines / technology used\n\n"
            f"Knowledge Base Context:\n{kb_context}"
        )
        return await self.call_llm(_SYSTEM_PROMPT, prompt)

    async def draft_linkedin_post(self, topic: str) -> str:
        kb_results = await self.search_domain_knowledge(topic, limit=8)
        kb_context = self._format_context(kb_results)

        prompt = (
            f"Draft a LinkedIn post about: {topic}\n\n"
            "Guidelines:\n"
            "- Professional but engaging tone suitable for LinkedIn\n"
            "- 150-250 words\n"
            "- Include a hook in the first line\n"
            "- End with a call to action or thought-provoking question\n"
            "- Use line breaks for readability\n"
            "- No hashtag spam — 3-5 relevant hashtags maximum\n\n"
            f"Knowledge Base Context:\n{kb_context}"
        )
        return await self.call_llm(_SYSTEM_PROMPT, prompt, temperature=0.6)

    # ── BaseAgent interface ───────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if ctx.get("task") == "case_study":
            return await self.build_case_study(
                project_name=ctx.get("project_name", query),
                context=ctx,
            )
        if ctx.get("task") == "linkedin":
            return await self.use_skill(
                "generate_social_post",
                topic=ctx.get("topic", query),
                platform="linkedin",
            )
        if ctx.get("task") == "social_post":
            return await self.use_skill(
                "generate_social_post",
                topic=ctx.get("topic", query),
                platform=ctx.get("platform", "linkedin"),
            )

        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)
