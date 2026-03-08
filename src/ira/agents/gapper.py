"""Gapper — The Gap Resolver.

Activated when a draft response contains missing data (prices, specs,
dates, contacts).  Gapper uses every available tool — email search,
document archive, knowledge base, web search, CRM, and inter-agent
delegation — to fill gaps before the response reaches the user.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("gapper_system")

_GAP_INDICATORS = re.compile(
    r"(?:"
    r"\b(?:not specified|not available|unknown|TBD|N/?A|missing|unclear)\b"
    r"|—"
    r"|\((?:in (?:offer|PDF|quote|PO|attached)|details? (?:not|pending))[^)]*\)"
    r"|\?\s*$"
    r")",
    re.IGNORECASE,
)


def detect_gaps(text: str) -> list[str]:
    """Return a list of lines from *text* that contain gap indicators."""
    gaps: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _GAP_INDICATORS.search(stripped):
            gaps.append(stripped)
    return gaps


class Gapper(BaseAgent):
    name = "gapper"
    role = "Gap Resolver"
    description = (
        "Finds and fills missing data in reports and responses. "
        "Uses email search, document archive, knowledge base, web search, "
        "CRM, and inter-agent delegation to resolve every gap."
    )

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="search_archive_for_document",
            description=(
                "Ask Alexandros to search the document archive for a specific "
                "file (PO, quote, order confirmation) and extract its content."
            ),
            parameters={
                "query": "What to search for (e.g. 'Pinnacle PO', 'Naffco quote PDF')",
            },
            handler=self._tool_search_archive,
        ))

        self.register_tool(AgentTool(
            name="ask_specialist",
            description=(
                "Ask a specialist agent a targeted question to fill a gap. "
                "Use 'prometheus' for sales/CRM, 'atlas' for project status, "
                "'plutus' for finance, 'hephaestus' for production, "
                "'alexandros' for document archive, 'iris' for web research."
            ),
            parameters={
                "agent_name": "Agent to ask (prometheus, atlas, plutus, hephaestus, alexandros, iris)",
                "question": "Specific question to fill the gap",
            },
            handler=self._tool_ask_specialist,
        ))

    async def _tool_search_archive(self, query: str) -> str:
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available."
        alexandros = pantheon.get_agent("alexandros")
        if not alexandros:
            return "Alexandros not available."
        try:
            return await alexandros.handle(query, {"action": "ask", "synthesize": True})
        except Exception as exc:
            logger.warning("Gapper archive search failed: %s", exc)
            return f"Archive search error: {exc}"

    async def _tool_ask_specialist(self, agent_name: str, question: str) -> str:
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available."
        agent = pantheon.get_agent(agent_name.lower())
        if not agent:
            return f"Agent '{agent_name}' not found."
        try:
            return await agent.handle(question, {
                "services": {"_delegation_depth": 1},
                "_delegation_depth": 1,
            })
        except Exception as exc:
            logger.warning("Gapper delegation to '%s' failed: %s", agent_name, exc)
            return f"Agent '{agent_name}' error: {exc}"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Resolve gaps in a draft response.

        *query* should be the draft text with gaps.  Gapper will identify
        the gaps and use its tools to fill them.
        """
        ctx = context or {}

        gaps = detect_gaps(query)
        if not gaps:
            return query

        gap_summary = "\n".join(f"- {g}" for g in gaps[:20])
        enriched_query = (
            f"The following draft response has {len(gaps)} gaps that need filling:\n\n"
            f"GAPS FOUND:\n{gap_summary}\n\n"
            f"FULL DRAFT:\n{query[:6000]}\n\n"
            f"For each gap, use your tools to find the missing data. "
            f"Return the COMPLETE response with all gaps filled and sources cited."
        )

        return await self.run(enriched_query, ctx, system_prompt=_SYSTEM_PROMPT)

    async def resolve_gaps(self, draft: str, original_query: str) -> str:
        """Pipeline-callable method: detect gaps and resolve them.

        Returns the original draft unchanged if no gaps are found,
        or an enriched version with gaps filled.
        """
        gaps = detect_gaps(draft)
        if not gaps:
            logger.info("Gapper: no gaps detected, returning draft unchanged")
            return draft

        logger.info("Gapper: detected %d gaps, resolving...", len(gaps))

        gap_summary = "\n".join(f"- {g}" for g in gaps[:15])
        enriched_query = (
            f"Original user query: {original_query}\n\n"
            f"Draft response with {len(gaps)} data gaps:\n\n"
            f"GAPS FOUND:\n{gap_summary}\n\n"
            f"FULL DRAFT:\n{draft[:6000]}\n\n"
            f"Fill every gap using your tools. Return ONLY the missing data "
            f"you found, formatted as a list of corrections with sources."
        )

        try:
            corrections = await self.run(
                enriched_query, system_prompt=_SYSTEM_PROMPT,
            )
            if corrections and len(corrections) > 50:
                return f"{draft}\n\n---\n**Gap Resolution (by Gapper):**\n{corrections}"
            return draft
        except Exception:
            logger.exception("Gapper resolution failed")
            return draft
