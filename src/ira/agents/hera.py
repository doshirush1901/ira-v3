"""Hera — Vendor / Procurement agent.

Manages vendor relationships, component sourcing, lead-time estimation,
and procurement taxonomy for Machinecraft's supply chain.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("hera_system")


class Hera(BaseAgent):
    name = "hera"
    role = "Vendor/Procurement"
    description = "Vendor management, component sourcing, lead-time tracking, and procurement intelligence"

    _TAXONOMY: dict[str, list[str]] = {
        "electrical": ["motors", "drives", "sensors", "wiring"],
        "pneumatic": ["cylinders", "valves", "fittings"],
        "mechanical": ["bearings", "gears", "shafts", "fasteners"],
        "heating": ["heaters", "thermocouples", "controllers"],
    }

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        action = ctx.get("action", "")

        if action == "vendor_status":
            return await self.vendor_status(ctx.get("vendor_name", query))

        if action == "lead_time":
            return await self.component_lead_time(ctx.get("component", query))

        if action == "classify":
            return json.dumps(await self.classify_component(
                ctx.get("component_name", query),
            ))

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nVendor/Procurement Context:\n{kb_context}",
        )

    async def vendor_status(self, vendor_name: str) -> str:
        """Search KB for vendor information and return a status summary."""
        results = await self.search_knowledge(
            f"vendor supplier {vendor_name} status orders delivery", limit=10,
        )
        kb_context = self._format_context(results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Provide a comprehensive status report for vendor: {vendor_name}\n\n"
            f"Knowledge base data:\n{kb_context}",
        )

    async def component_lead_time(self, component: str) -> str:
        """Estimate lead time for a component from KB data."""
        results = await self.search_knowledge(
            f"lead time delivery {component} procurement", limit=8,
        )
        kb_context = self._format_context(results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Estimate the lead time for: {component}\n\n"
            f"Include typical supplier lead times, any known delays, and "
            f"alternative sourcing options if available.\n\n"
            f"Knowledge base data:\n{kb_context}",
        )

    async def classify_component(self, component_name: str) -> dict[str, Any]:
        """Classify a component into the procurement taxonomy."""
        name_lower = component_name.lower()
        for category, subcategories in self._TAXONOMY.items():
            for sub in subcategories:
                if sub in name_lower:
                    return {
                        "component": component_name,
                        "category": category,
                        "subcategory": sub,
                        "confidence": "HIGH",
                    }

        raw = await self.call_llm(
            _SYSTEM_PROMPT,
            f"Classify this component into one of these categories: "
            f"{json.dumps(self._TAXONOMY)}\n\n"
            f"Component: {component_name}\n\n"
            f"Return JSON: {{\"component\": str, \"category\": str, "
            f"\"subcategory\": str, \"confidence\": \"HIGH\"|\"MEDIUM\"|\"LOW\"}}",
            temperature=0.1,
        )

        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse component classification as JSON")

        return {
            "component": component_name,
            "category": "unknown",
            "subcategory": "unknown",
            "confidence": "LOW",
        }
