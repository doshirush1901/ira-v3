"""Quotebuilder -- Quote generation agent.

Produces structured quote documents in markdown format with all
standard sections (header, customer info, machine specs, pricing,
payment terms, delivery, warranty).  Supports single-machine and
multi-machine quotes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.agents.base_agent import BaseAgent
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("quotebuilder_system")
_SEQUENCE_FILE = Path("data/brain/quote_sequence.txt")


def _next_quote_id() -> str:
    _SEQUENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    seq = 1
    if _SEQUENCE_FILE.exists():
        try:
            stored = _SEQUENCE_FILE.read_text(encoding="utf-8").strip()
            stored_date, stored_seq = stored.split(":", 1)
            if stored_date == today:
                seq = int(stored_seq) + 1
        except (ValueError, OSError):
            pass

    _SEQUENCE_FILE.write_text(f"{today}:{seq}", encoding="utf-8")
    return f"MT{today}{seq:02d}"


class Quotebuilder(BaseAgent):
    name = "quotebuilder"
    role = "Quote Builder"
    description = "Structured quote generation for single and multi-machine orders"

    async def build_quote(
        self,
        customer: str,
        machine_model: str,
        context: dict,
    ) -> str:
        quote_id = _next_quote_id()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        kb_results = await self.search_knowledge(machine_model, limit=10)
        kb_context = self._format_context(kb_results)

        customer_results = await self.search_knowledge(customer, limit=5)
        customer_context = self._format_context(customer_results)

        payment_terms = context.get("payment_terms", "")
        delivery_location = context.get("delivery_location", "")
        special_requirements = context.get("special_requirements", "")
        validity_days = context.get("validity_days", 30)

        prompt = (
            f"Generate a structured quote document.\n\n"
            f"QUOTE HEADER:\n"
            f"  Quote ID: {quote_id}\n"
            f"  Date: {today}\n"
            f"  Validity: {validity_days} days\n\n"
            f"CUSTOMER: {customer}\n"
            f"MACHINE MODEL: {machine_model}\n"
        )
        if delivery_location:
            prompt += f"DELIVERY LOCATION: {delivery_location}\n"
        if payment_terms:
            prompt += f"REQUESTED PAYMENT TERMS: {payment_terms}\n"
        if special_requirements:
            prompt += f"SPECIAL REQUIREMENTS: {special_requirements}\n"

        prompt += (
            f"\nMACHINE KNOWLEDGE:\n{kb_context}\n\n"
            f"CUSTOMER KNOWLEDGE:\n{customer_context}\n\n"
            "Include these sections in the quote:\n"
            "1. Quote header (ID, date, validity period)\n"
            "2. Customer information\n"
            "3. Machine specifications\n"
            "4. Pricing breakdown (machine, tooling, accessories, installation)\n"
            "5. Payment terms\n"
            "6. Delivery timeline\n"
            "7. Warranty terms\n"
            "8. Process flow description\n\n"
            "Use markdown formatting. Mark any values you are uncertain about "
            "with [TBD] so they can be reviewed before sending."
        )

        result = await self.call_llm(_SYSTEM_PROMPT, prompt)
        logger.info("Quote %s generated for %s / %s", quote_id, customer, machine_model)
        return result

    async def build_multi_machine_quote(
        self,
        customer: str,
        machines: list[str],
        context: dict,
    ) -> str:
        quote_id = _next_quote_id()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        validity_days = context.get("validity_days", 30)

        all_kb: list[str] = []
        for model in machines:
            results = await self.search_knowledge(model, limit=6)
            if results:
                all_kb.append(f"\n### {model}\n{self._format_context(results)}")

        customer_results = await self.search_knowledge(customer, limit=5)
        customer_context = self._format_context(customer_results)

        delivery_location = context.get("delivery_location", "")
        payment_terms = context.get("payment_terms", "")
        special_requirements = context.get("special_requirements", "")

        machines_list = "\n".join(f"  - {m}" for m in machines)
        prompt = (
            f"Generate a multi-machine structured quote document.\n\n"
            f"QUOTE HEADER:\n"
            f"  Quote ID: {quote_id}\n"
            f"  Date: {today}\n"
            f"  Validity: {validity_days} days\n\n"
            f"CUSTOMER: {customer}\n"
            f"MACHINES ({len(machines)}):\n{machines_list}\n"
        )
        if delivery_location:
            prompt += f"DELIVERY LOCATION: {delivery_location}\n"
        if payment_terms:
            prompt += f"REQUESTED PAYMENT TERMS: {payment_terms}\n"
        if special_requirements:
            prompt += f"SPECIAL REQUIREMENTS: {special_requirements}\n"

        prompt += (
            f"\nMACHINE KNOWLEDGE:{''.join(all_kb)}\n\n"
            f"CUSTOMER KNOWLEDGE:\n{customer_context}\n\n"
            "Include these sections:\n"
            "1. Quote header (ID, date, validity period)\n"
            "2. Customer information\n"
            "3. Machine specifications — one subsection per machine\n"
            "4. Pricing breakdown — itemised per machine plus combined total\n"
            "5. Payment terms\n"
            "6. Delivery timeline for each machine\n"
            "7. Warranty terms\n"
            "8. Process flow description\n\n"
            "Use markdown formatting. Mark uncertain values with [TBD]."
        )

        result = await self.call_llm(_SYSTEM_PROMPT, prompt)
        logger.info(
            "Multi-machine quote %s generated for %s (%d machines)",
            quote_id, customer, len(machines),
        )
        return result

    # ── BaseAgent interface ───────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}

        if ctx.get("task") == "multi_machine_quote":
            return await self.build_multi_machine_quote(
                customer=ctx["customer"],
                machines=ctx["machines"],
                context=ctx,
            )
        if ctx.get("task") == "quote" or ctx.get("customer"):
            return await self.build_quote(
                customer=ctx.get("customer", query),
                machine_model=ctx.get("machine_model", ""),
                context=ctx,
            )

        if ctx.get("task") == "estimate_price":
            return await self.use_skill(
                "calculate_quote",
                machine_model=ctx.get("machine_model", ""),
                configuration=ctx.get("configuration", {}),
            )

        if ctx.get("task") == "proposal":
            return await self.use_skill(
                "draft_proposal",
                customer=ctx.get("customer", ""),
                machine_model=ctx.get("machine_model", ""),
                context=query,
            )

        kb_results = await self.search_knowledge(query, limit=8)
        kb_context = self._format_context(kb_results)

        return await self.call_llm(
            _SYSTEM_PROMPT,
            f"Query: {query}\n\nKnowledge Base:\n{kb_context}",
        )
