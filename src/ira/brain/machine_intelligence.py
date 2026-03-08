"""Machine-domain intelligence for Machinecraft.

Provides spec lookups, machine recommendations, comparisons, and
hard-coded business-rule overrides.  The machine catalog and truth hints
are loaded from ``data/machine_knowledge.json`` so they can be updated
without touching code.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langfuse.decorators import observe

from ira.brain.retriever import UnifiedRetriever
from ira.prompt_loader import load_prompt
from ira.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

_KNOWLEDGE_FILE = Path("data/machine_knowledge.json")

_SPECS_CATEGORY = "machine_manuals_and_specs"

_RECOMMEND_SYSTEM_PROMPT = load_prompt("recommend_machine")

_COMPARE_SYSTEM_PROMPT = load_prompt("compare_machines")


def _load_knowledge(path: Path = _KNOWLEDGE_FILE) -> dict[str, Any]:
    if not path.exists():
        logger.warning("Machine knowledge file not found: %s", path)
        return {"machine_catalog": {}, "truth_hints": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MachineIntelligence:
    """Deep domain knowledge about Machinecraft's machine portfolio."""

    def __init__(
        self,
        retriever: UnifiedRetriever,
        *,
        knowledge_path: Path = _KNOWLEDGE_FILE,
        llm: LLMClient | None = None,
    ) -> None:
        self._retriever = retriever
        self._llm = llm or get_llm_client()

        data = _load_knowledge(knowledge_path)
        self.machine_catalog: dict[str, dict[str, Any]] = data.get("machine_catalog", {})
        self.truth_hints: dict[str, str] = data.get("truth_hints", {})

    # ── spec lookup ──────────────────────────────────────────────────────

    async def get_machine_specs(self, model: str) -> dict[str, Any]:
        """Retrieve detailed specifications for *model*.

        Merges the static catalog entry with live knowledge-base results
        from the machine-manuals category, then overlays any truth hints
        that apply.
        """
        catalog_entry = self.machine_catalog.get(model, {})

        kb_results = await self._retriever.search_by_category(
            query=f"{model} specifications technical details",
            category=_SPECS_CATEGORY,
            limit=5,
        )

        applicable_hints = {
            k: v for k, v in self.truth_hints.items() if model.lower() in k.lower()
        }

        return {
            "model": model,
            "catalog": catalog_entry,
            "knowledge_base": [r["content"] for r in kb_results],
            "truth_hints": applicable_hints,
        }

    # ── recommendation ───────────────────────────────────────────────────

    @observe()
    async def recommend_machine(
        self,
        requirements: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Recommend machines that match *requirements*.

        Expected keys: ``material``, ``thickness``, ``output_rate``,
        ``budget`` — all optional.
        """
        req_text = ", ".join(f"{k}: {v}" for k, v in requirements.items() if v)

        kb_results = await self._retriever.search(
            query=f"machine for {req_text}",
            limit=8,
        )

        context = self._build_context(kb_results)
        user_msg = f"Customer requirements:\n{req_text}\n\n{context}"

        raw = await self._llm_call(_RECOMMEND_SYSTEM_PROMPT, user_msg)

        try:
            recommendations = json.loads(raw)
            if isinstance(recommendations, list):
                return recommendations
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM returned non-JSON recommendation; wrapping as text")

        return [{"model": "unknown", "reason": raw, "caveats": "", "budget_indication": ""}]

    # ── comparison ───────────────────────────────────────────────────────

    @observe()
    async def compare_machines(self, model_a: str, model_b: str) -> str:
        """Return a Markdown comparison table for two machine models."""
        specs_a = await self.get_machine_specs(model_a)
        specs_b = await self.get_machine_specs(model_b)

        context_parts = [
            f"## {model_a}\nCatalog: {json.dumps(specs_a['catalog'])}\n"
            f"Truth hints: {json.dumps(specs_a['truth_hints'])}\n"
            f"KB excerpts:\n" + "\n".join(specs_a["knowledge_base"][:3]),
            f"## {model_b}\nCatalog: {json.dumps(specs_b['catalog'])}\n"
            f"Truth hints: {json.dumps(specs_b['truth_hints'])}\n"
            f"KB excerpts:\n" + "\n".join(specs_b["knowledge_base"][:3]),
        ]

        return await self._llm_call(
            _COMPARE_SYSTEM_PROMPT,
            "\n\n".join(context_parts),
        )

    # ── internals ────────────────────────────────────────────────────────

    def _build_context(self, kb_results: list[dict[str, Any]]) -> str:
        parts = [
            f"MACHINE CATALOG:\n{json.dumps(self.machine_catalog, indent=2)}",
            f"TRUTH HINTS:\n{json.dumps(self.truth_hints, indent=2)}",
            "KNOWLEDGE BASE CONTEXT:",
        ]
        for r in kb_results:
            parts.append(f"- [{r.get('source', '')}] {r.get('content', '')[:500]}")
        return "\n".join(parts)

    async def _llm_call(self, system: str, user: str) -> str:
        return await self._llm.generate_text(
            system, user, temperature=0.2, name="machine_intelligence",
        )
