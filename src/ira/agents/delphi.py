"""Delphi — Classification specialist and shadow simulation agent.

Classifies inbound emails by intent, urgency, and required action,
classifies contacts by their relationship to Machinecraft, and runs
shadow simulations to score Ira's responses against Rushabh's style.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_EMAIL_SYSTEM_PROMPT = load_prompt("delphi_system")
_CONTACT_SYSTEM_PROMPT = load_prompt("delphi_classify_contact")

_VALID_CRM_TYPES = frozenset({
    "LIVE_CUSTOMER", "PAST_CUSTOMER",
    "LEAD_WITH_INTERACTIONS", "LEAD_NO_INTERACTIONS",
})


class Delphi(BaseAgent):
    name = "delphi"
    role = "Classification Specialist"
    description = "Classifies emails by intent and contacts by relationship type"

    _SHADOW_DIMENSIONS: list[str] = [
        "technical_accuracy",
        "warmth",
        "urgency_handling",
        "price_sensitivity",
        "cultural_awareness",
        "follow_up_timing",
        "objection_handling",
        "closing_technique",
    ]

    # ── tool registration ─────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="classify_email",
            description="Classify an email's intent, urgency, suggested agent, and summary.",
            parameters={"email_content": "The raw email text to classify"},
            handler=self._tool_classify_email,
        ))
        self.register_tool(AgentTool(
            name="classify_contact",
            description="Classify a contact for CRM eligibility (customer, lead, etc.).",
            parameters={
                "email": "Contact email address",
                "context": "Optional additional context about the contact",
            },
            handler=self._tool_classify_contact,
        ))
        self.register_tool(AgentTool(
            name="run_shadow_sim",
            description="Score Ira's response against Rushabh's style on 8 dimensions.",
            parameters={
                "query": "The original query",
                "ira_response": "Ira's generated response",
                "contact_context": "Optional JSON context about the contact",
            },
            handler=self._tool_run_shadow_sim,
        ))
        self.register_tool(AgentTool(
            name="build_interaction_map",
            description="Build a communication pattern map for a contact from KB history.",
            parameters={"contact_email": "The contact's email address"},
            handler=self._tool_build_interaction_map,
        ))
        self.register_tool(AgentTool(
            name="clone_voice",
            description="Generate a response in Rushabh's communication style.",
            parameters={
                "query": "The query to respond to as Rushabh",
                "context": "Optional JSON context (contact_email, etc.)",
            },
            handler=self._tool_clone_voice,
        ))

    # ── tool handlers ─────────────────────────────────────────────────────

    async def _tool_classify_email(self, email_content: str) -> str:
        raw = await self.call_llm(
            _EMAIL_SYSTEM_PROMPT,
            f"Email content:\n{email_content}",
        )
        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                return json.dumps(parsed, default=str)
        except (json.JSONDecodeError, ValueError):
            pass
        return json.dumps({
            "intent": "unknown",
            "urgency": "medium",
            "suggested_agent": "athena",
            "summary": raw[:500],
        })

    async def _tool_classify_contact(self, email: str, context: str = "") -> str:
        ctx: dict[str, Any] = {"contact_data": {"email": email}}
        if context:
            try:
                ctx.update(json.loads(context))
            except (json.JSONDecodeError, ValueError):
                ctx["extra_context"] = context
        return await self._classify_contact(email, ctx)

    async def _tool_run_shadow_sim(self, query: str, ira_response: str, contact_context: str = "") -> str:
        ctx: dict[str, Any] = {}
        if contact_context:
            try:
                ctx = json.loads(contact_context)
            except (json.JSONDecodeError, ValueError):
                ctx = {"raw_context": contact_context}
        result = await self.run_shadow_simulation(query, ira_response, ctx)
        return json.dumps(result, default=str)

    async def _tool_build_interaction_map(self, contact_email: str) -> str:
        result = await self.build_interaction_map(contact_email)
        return json.dumps(result, default=str)

    async def _tool_clone_voice(self, query: str, context: str = "") -> str:
        ctx: dict[str, Any] = {}
        if context:
            try:
                ctx = json.loads(context)
            except (json.JSONDecodeError, ValueError):
                ctx = {"raw_context": context}
        return await self.rushabh_voice(query, ctx)

    # ── main handler ──────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if ctx.get("task") == "classify_contact":
            return await self._classify_contact(query, ctx)

        if action == "shadow":
            return json.dumps(await self.run_shadow_simulation(
                query,
                ctx.get("ira_response", ""),
                ctx,
            ))

        if action == "interaction_map":
            return json.dumps(await self.build_interaction_map(
                ctx.get("contact_email", query),
            ))

        if action == "rushabh_voice":
            return await self.rushabh_voice(query, ctx)

        return await self.run(query, context, system_prompt=_EMAIL_SYSTEM_PROMPT)

    # ── existing methods ──────────────────────────────────────────────────

    async def build_interaction_map(self, contact_email: str) -> dict[str, Any]:
        """Search KB for all interactions with a contact and build a communication pattern map."""
        results = await self.search_knowledge(
            f"interactions communications emails {contact_email}", limit=15,
        )

        if not results:
            return {
                "contact": contact_email,
                "interaction_count": 0,
                "patterns": {},
                "note": "No interaction history found in knowledge base",
            }

        context_block = self._format_context(results)

        raw = await self.call_llm(
            _EMAIL_SYSTEM_PROMPT,
            f"Analyze all interactions with {contact_email} and return a JSON map with:\n"
            f"- interaction_count: total interactions found\n"
            f"- first_contact: approximate date\n"
            f"- last_contact: approximate date\n"
            f"- dominant_topics: list of recurring subjects\n"
            f"- communication_style: how this person communicates\n"
            f"- responsiveness: fast/medium/slow\n"
            f"- sentiment_trend: improving/stable/declining\n\n"
            f"Interaction data:\n{context_block}",
            temperature=0.2,
        )

        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                parsed["contact"] = contact_email
                return parsed
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse interaction map as JSON")

        return {
            "contact": contact_email,
            "raw_analysis": raw,
        }

    async def run_shadow_simulation(
        self,
        query: str,
        ira_response: str,
        contact_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Score Ira's response on 8 dimensions vs how Rushabh would respond."""
        dimensions_list = ", ".join(self._SHADOW_DIMENSIONS)

        raw = await self.call_llm(
            _EMAIL_SYSTEM_PROMPT,
            f"You are scoring an AI assistant's response against how Rushabh (the CEO) "
            f"would personally respond.\n\n"
            f"Original query: {query}\n\n"
            f"Ira's response:\n{ira_response}\n\n"
            f"Contact context:\n{json.dumps(contact_context, default=str)}\n\n"
            f"Score each dimension 0.0-1.0 and provide suggestions.\n"
            f"Dimensions: {dimensions_list}\n\n"
            f"Return JSON: {{\"dimensions\": {{dim: score}}, \"overall\": float, "
            f"\"suggestions\": [str]}}",
            temperature=0.2,
        )

        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse shadow simulation as JSON")

        return {
            "dimensions": {d: 0.5 for d in self._SHADOW_DIMENSIONS},
            "overall": 0.5,
            "suggestions": ["Shadow simulation returned non-structured output", raw[:500]],
        }

    async def rushabh_voice(self, query: str, context: dict[str, Any]) -> str:
        """Generate a response in Rushabh's communication style using learned patterns."""
        contact_email = context.get("contact_email", "")
        interaction_data: dict[str, Any] = {}
        if contact_email:
            interaction_data = await self.build_interaction_map(contact_email)

        style_results = await self.search_knowledge(
            "Rushabh communication style tone emails", limit=5,
        )
        style_context = self._format_context(style_results)

        return await self.call_llm(
            _EMAIL_SYSTEM_PROMPT,
            f"Generate a response exactly as Rushabh (CEO of Machinecraft) would write it. "
            f"Match his tone, sentence structure, level of detail, and personality.\n\n"
            f"Query to respond to: {query}\n\n"
            f"Rushabh's style signals:\n{style_context}\n\n"
            f"Interaction history with contact:\n{json.dumps(interaction_data, default=str)}\n\n"
            f"Additional context:\n{json.dumps(context, default=str)}\n\n"
            f"Write ONLY the response as Rushabh would send it — no meta-commentary.",
            temperature=0.4,
        )

    async def _classify_contact(self, query: str, ctx: dict[str, Any]) -> str:
        """Classify a contact for CRM inclusion."""
        contact_data = ctx.get("contact_data", {})
        email = contact_data.get("email", "")
        name = contact_data.get("name", "")
        company = contact_data.get("company", "")

        if email and email.endswith(("@machinecraft.org", "@machinecraft.in")):
            return json.dumps({
                "contact_type": "OWN_COMPANY",
                "confidence": "HIGH",
                "reasoning": "Machinecraft internal email domain",
            })

        kb_context = ""
        search_queries = [q for q in [name, company, email] if q]
        if search_queries:
            search_term = " ".join(search_queries)
            try:
                results = await self.search_knowledge(search_term, limit=8)
                if results:
                    kb_context = "\n".join(
                        f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}"
                        for r in results
                    )
            except Exception:
                logger.debug("KB search failed during contact classification")

        email_history = ctx.get("email_history", "")
        order_history = ctx.get("order_history", "")

        payload = json.dumps({
            "contact": contact_data,
            "knowledge_base_matches": kb_context or "(none)",
            "email_history_summary": email_history or "(none)",
            "order_history": order_history or "(none)",
        }, default=str, indent=2)

        raw = await self.call_llm(
            _CONTACT_SYSTEM_PROMPT,
            payload,
            temperature=0.1,
        )

        try:
            result = self._parse_json_response(raw)
            if isinstance(result, dict):
                return json.dumps(result)
        except (json.JSONDecodeError, ValueError):
            pass

        return raw

    @staticmethod
    def is_crm_eligible(classification: dict[str, Any]) -> bool:
        """Return True if the classification result should enter the CRM."""
        return classification.get("contact_type", "") in _VALID_CRM_TYPES
