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

import httpx

from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_KNOWLEDGE_FILE = Path("data/machine_knowledge.json")

_SPECS_CATEGORY = "04_machine_manuals_and_specs"

_RECOMMEND_SYSTEM_PROMPT = """\
You are a technical sales engineer for Machinecraft, a manufacturer of
industrial panel-forming, roll-forming, and slitting machinery.

Given the MACHINE CATALOG, TRUTH HINTS, and KNOWLEDGE BASE CONTEXT below,
recommend the best machines for the customer's requirements.  For each
recommendation include: model, why it fits, any caveats, and a rough
budget indication.

Return ONLY valid JSON — an array of objects:
[{"model": "", "reason": "", "caveats": "", "budget_indication": ""}]"""

_COMPARE_SYSTEM_PROMPT = """\
You are a technical sales engineer for Machinecraft.

Given the specs and context for two machines, produce a detailed Markdown
comparison table covering: category, throughput, material range, key
features, lead time, and ideal use-case.  Be precise and factual."""


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
    ) -> None:
        self._retriever = retriever

        data = _load_knowledge(knowledge_path)
        self.machine_catalog: dict[str, dict[str, Any]] = data.get("machine_catalog", {})
        self.truth_hints: dict[str, str] = data.get("truth_hints", {})

        settings = get_settings()
        self._openai_key = settings.llm.openai_api_key.get_secret_value()
        self._openai_model = settings.llm.openai_model

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
        if not self._openai_key:
            return "(No OpenAI key configured — cannot generate response)"

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError):
            logger.exception("LLM call failed in MachineIntelligence")
            return "(LLM call failed)"
