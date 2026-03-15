"""Aletheia — Compliance / Provenance agent.

Traces claims in agent responses back to sources (Qdrant, Neo4j, CRM).
Runs in the pipeline between execution and shaping to flag unverifiable
claims before they reach the user.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("aletheia_system")

_CLAIM_PATTERN = re.compile(
    r"(\d[\d,.]+\s*(?:INR|USD|EUR|Rs|lakh|crore|weeks?|days?|months?|kg|tons?|units?|%)|"
    r"\b(?:ready|dispatched|delivered|shipped|completed|scheduled)\s+(?:by|on|for)\s+\S+|"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b)",
    re.IGNORECASE,
)


class Aletheia(BaseAgent):
    name = "aletheia"
    role = "Compliance / Provenance"
    description = "Traces claims to sources and flags unverifiable assertions"
    knowledge_categories = [
        "company_internal",
        "sales_and_crm",
        "project_case_studies",
    ]
    timeout = 45

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="trace_claim",
            description=(
                "Search Qdrant and Neo4j for source evidence matching a specific claim. "
                "Returns source reference or 'unverifiable'."
            ),
            parameters={"claim": "The specific claim to trace (e.g. a number, date, or assertion)"},
            handler=self._tool_trace_claim,
        ))

        self.register_tool(AgentTool(
            name="verify_sources",
            description="Extract key claims from a response and trace each to a source. Returns a provenance report.",
            parameters={"response_text": "The full response text to verify"},
            handler=self._tool_verify_sources,
        ))

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        return await self.run(query, context, system_prompt=_SYSTEM_PROMPT)

    async def check_provenance(self, response_text: str) -> dict[str, Any]:
        """Quick provenance check without the full ReAct loop."""
        claims = _CLAIM_PATTERN.findall(response_text)
        if not claims:
            return {"verdict": "VERIFIED", "claims_checked": 0, "unverifiable": []}

        verified: list[str] = []
        unverifiable: list[str] = []

        for claim in claims[:10]:
            claim_str = claim.strip()
            try:
                results = await self._retriever.search(claim_str, limit=3)
                if results and any(r.get("score", 0) > 0.5 for r in results):
                    verified.append(claim_str)
                else:
                    unverifiable.append(claim_str)
            except Exception:
                unverifiable.append(claim_str)

        total = len(verified) + len(unverifiable)
        if not unverifiable:
            verdict = "VERIFIED"
        elif len(unverifiable) < total / 2:
            verdict = "PARTIAL"
        else:
            verdict = "UNVERIFIED"

        return {
            "verdict": verdict,
            "claims_checked": total,
            "verified": verified,
            "unverifiable": unverifiable,
        }

    async def _tool_trace_claim(self, claim: str) -> str:
        try:
            results = await self._retriever.search(claim, limit=5)
        except Exception as exc:
            return f"Search error: {exc}"

        if not results:
            return f"UNVERIFIABLE: No source found for '{claim}'"

        best = max(results, key=lambda r: r.get("score", 0))
        if best.get("score", 0) < 0.4:
            return f"UNVERIFIABLE: Best match score {best.get('score', 0):.2f} is too low for '{claim}'"

        source = best.get("metadata", {}).get("source", best.get("source_type", "unknown"))
        content_preview = best.get("content", "")[:200]
        return f"VERIFIED: '{claim}' → source: {source} (score: {best.get('score', 0):.2f})\n  Evidence: {content_preview}"

    async def _tool_verify_sources(self, response_text: str) -> str:
        result = await self.check_provenance(response_text)
        lines = [f"Provenance verdict: {result['verdict']} ({result['claims_checked']} claims checked)"]
        if result.get("verified"):
            lines.append(f"Verified: {', '.join(result['verified'][:5])}")
        if result.get("unverifiable"):
            lines.append(f"Unverifiable: {', '.join(result['unverifiable'][:5])}")
        return "\n".join(lines)
