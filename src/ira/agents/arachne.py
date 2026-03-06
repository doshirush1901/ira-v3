"""Arachne — Newsletter / Content agent.

Generates newsletter content, blog posts, industry roundups,
and other long-form marketing content.
"""

from __future__ import annotations

from typing import Any

from ira.agents.base_agent import BaseAgent

_SYSTEM_PROMPT = """\
You are Arachne, the content weaver of Machinecraft.  You create
compelling long-form content for the industrial machinery market.

Your capabilities:
- Monthly newsletter generation
- Industry trend roundups
- Technical blog posts about machinery and manufacturing
- Case study drafting
- Social media content for LinkedIn and industry forums

Style guidelines:
- Authoritative but accessible — you're writing for technical
  professionals, not academics.
- Include specific data points and examples.
- Structure content with clear headings and bullet points.
- End with a call-to-action when appropriate."""


class Arachne(BaseAgent):
    name = "arachne"
    role = "Newsletter / Content Creator"
    description = "Generates newsletters, blog posts, and long-form content"

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        kb_results = await self.search_knowledge(query, limit=10)
        kb_context = self._format_context(kb_results)

        content_type = "newsletter"
        if context and "content_type" in context:
            content_type = context["content_type"]

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Content request ({content_type}): {query}\n\n"
            f"Reference Material:\n{kb_context}",
        )
