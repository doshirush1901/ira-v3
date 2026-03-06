"""Fast, pattern-based intent router for Ira.

Before invoking an LLM to decide which agents should handle a query, the
:class:`DeterministicRouter` attempts a cheap keyword/regex classification.
If the match confidence is high enough the routing table is returned
immediately, saving an LLM round-trip on the most common query shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class IntentCategory(str, Enum):
    """High-level intent buckets recognised by the deterministic router."""

    SALES_PIPELINE = "SALES_PIPELINE"
    FINANCE_REVIEW = "FINANCE_REVIEW"
    HR_OVERVIEW = "HR_OVERVIEW"
    MACHINE_SPECS = "MACHINE_SPECS"
    PRODUCTION_STATUS = "PRODUCTION_STATUS"
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    MARKETING_CAMPAIGN = "MARKETING_CAMPAIGN"
    RESEARCH = "RESEARCH"
    QUOTE_REQUEST = "QUOTE_REQUEST"
    GENERAL = "GENERAL"


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """Which agents and tools a given intent requires."""

    required_agents: tuple[str, ...]
    optional_agents: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()


ROUTING_TABLE: dict[IntentCategory, RoutingConfig] = {
    IntentCategory.SALES_PIPELINE: RoutingConfig(
        required_agents=("prometheus", "clio"),
        optional_agents=("tyche", "calliope"),
        required_tools=("crm", "retriever"),
    ),
    IntentCategory.FINANCE_REVIEW: RoutingConfig(
        required_agents=("plutus",),
        optional_agents=("prometheus", "tyche"),
        required_tools=("crm", "retriever"),
    ),
    IntentCategory.HR_OVERVIEW: RoutingConfig(
        required_agents=("themis",),
        optional_agents=("clio",),
        required_tools=("retriever",),
    ),
    IntentCategory.MACHINE_SPECS: RoutingConfig(
        required_agents=("hephaestus", "clio"),
        optional_agents=("vera",),
        required_tools=("retriever", "machine_intelligence"),
    ),
    IntentCategory.PRODUCTION_STATUS: RoutingConfig(
        required_agents=("hephaestus",),
        optional_agents=("clio",),
        required_tools=("retriever",),
    ),
    IntentCategory.CUSTOMER_SERVICE: RoutingConfig(
        required_agents=("clio", "prometheus"),
        optional_agents=("calliope",),
        required_tools=("crm", "retriever"),
    ),
    IntentCategory.MARKETING_CAMPAIGN: RoutingConfig(
        required_agents=("hermes",),
        optional_agents=("calliope", "arachne"),
        required_tools=("retriever", "drip_engine"),
    ),
    IntentCategory.RESEARCH: RoutingConfig(
        required_agents=("clio",),
        optional_agents=("iris", "vera"),
        required_tools=("retriever",),
    ),
    IntentCategory.QUOTE_REQUEST: RoutingConfig(
        required_agents=("prometheus", "plutus", "hephaestus"),
        optional_agents=("calliope",),
        required_tools=("pricing_engine", "crm", "retriever"),
    ),
    IntentCategory.GENERAL: RoutingConfig(
        required_agents=("clio",),
        optional_agents=("sphinx",),
        required_tools=("retriever",),
    ),
}


# ── keyword patterns ─────────────────────────────────────────────────────────
# Each entry is (compiled regex, intent, per-match weight).  A query can
# match multiple patterns; the intent with the highest cumulative weight wins.

@dataclass(frozen=True, slots=True)
class _Pattern:
    regex: re.Pattern[str]
    intent: IntentCategory
    weight: float = 1.0


def _compile(patterns: Sequence[tuple[str, IntentCategory, float]]) -> list[_Pattern]:
    return [
        _Pattern(re.compile(p, re.IGNORECASE), intent, w)
        for p, intent, w in patterns
    ]


_PATTERNS: list[_Pattern] = _compile([
    # Sales / pipeline
    (r"\bpipeline\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bdeals?\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bleads?\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bcrm\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bsales\s+funnel\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bconversion\s+rate\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bwin\s+rate\b", IntentCategory.SALES_PIPELINE, 1.5),

    # Quote / pricing
    (r"\bquote\b", IntentCategory.QUOTE_REQUEST, 2.0),
    (r"\bpric(e|ing)\b", IntentCategory.QUOTE_REQUEST, 2.0),
    (r"\bcost\b", IntentCategory.QUOTE_REQUEST, 1.5),
    (r"\bproposal\b", IntentCategory.QUOTE_REQUEST, 1.5),
    (r"\bestimate\b", IntentCategory.QUOTE_REQUEST, 1.0),
    (r"\bbudget\b", IntentCategory.QUOTE_REQUEST, 1.0),

    # Machine specs
    (r"\bmachine\b", IntentCategory.MACHINE_SPECS, 1.5),
    (r"\bspecs?\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bspecification", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bPF[12]\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bPF1-C\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bAM[\s-]?series\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bRF-100\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bSL-500\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\broll\s*form", IntentCategory.MACHINE_SPECS, 1.5),
    (r"\bpanel\s*form", IntentCategory.MACHINE_SPECS, 1.5),

    # Finance
    (r"\brevenue\b", IntentCategory.FINANCE_REVIEW, 2.0),
    (r"\bfinancial\b", IntentCategory.FINANCE_REVIEW, 2.0),
    (r"\bprofit\b", IntentCategory.FINANCE_REVIEW, 1.5),
    (r"\bmargin\b", IntentCategory.FINANCE_REVIEW, 1.5),
    (r"\bcash\s*flow\b", IntentCategory.FINANCE_REVIEW, 2.0),
    (r"\bforecast\b", IntentCategory.FINANCE_REVIEW, 1.0),

    # HR
    (r"\bhr\b", IntentCategory.HR_OVERVIEW, 2.0),
    (r"\bhuman\s+resources\b", IntentCategory.HR_OVERVIEW, 2.0),
    (r"\bemployee", IntentCategory.HR_OVERVIEW, 1.5),
    (r"\bheadcount\b", IntentCategory.HR_OVERVIEW, 2.0),
    (r"\bhiring\b", IntentCategory.HR_OVERVIEW, 1.5),

    # Production
    (r"\bproduction\b", IntentCategory.PRODUCTION_STATUS, 1.5),
    (r"\bmanufactur", IntentCategory.PRODUCTION_STATUS, 1.5),
    (r"\bassembly\b", IntentCategory.PRODUCTION_STATUS, 1.5),
    (r"\blead\s*time\b", IntentCategory.PRODUCTION_STATUS, 1.5),

    # Marketing
    (r"\bmarketing\b", IntentCategory.MARKETING_CAMPAIGN, 2.0),
    (r"\bcampaign\b", IntentCategory.MARKETING_CAMPAIGN, 2.0),
    (r"\bdrip\b", IntentCategory.MARKETING_CAMPAIGN, 2.0),
    (r"\bnewsletter\b", IntentCategory.MARKETING_CAMPAIGN, 2.0),
    (r"\bemail\s+blast\b", IntentCategory.MARKETING_CAMPAIGN, 1.5),

    # Customer service
    (r"\bcomplaint\b", IntentCategory.CUSTOMER_SERVICE, 2.0),
    (r"\bsupport\s+ticket\b", IntentCategory.CUSTOMER_SERVICE, 2.0),
    (r"\bwarranty\b", IntentCategory.CUSTOMER_SERVICE, 1.5),
    (r"\bafter[\s-]?sales\b", IntentCategory.CUSTOMER_SERVICE, 2.0),

    # Research
    (r"\bresearch\b", IntentCategory.RESEARCH, 1.5),
    (r"\bmarket\s+analysis\b", IntentCategory.RESEARCH, 2.0),
    (r"\bcompetitor", IntentCategory.RESEARCH, 1.5),
    (r"\bindustry\s+trend", IntentCategory.RESEARCH, 1.5),
])

_CONFIDENCE_THRESHOLD = 3.0


class DeterministicRouter:
    """Pattern-based intent classifier and routing-table lookup."""

    def classify_intent(self, query: str) -> IntentCategory | None:
        """Classify *query* by keyword patterns.

        Returns the best-matching :class:`IntentCategory`, or ``None`` if
        no pattern exceeds the confidence threshold (signalling that
        LLM-based routing should be used).
        """
        scores: dict[IntentCategory, float] = {}
        for pat in _PATTERNS:
            if pat.regex.search(query):
                scores[pat.intent] = scores.get(pat.intent, 0.0) + pat.weight

        if not scores:
            return None

        best_intent = max(scores, key=scores.__getitem__)
        if scores[best_intent] < _CONFIDENCE_THRESHOLD:
            return None

        return best_intent

    def get_routing(self, intent: IntentCategory) -> dict:
        """Return the routing configuration for *intent* as a plain dict."""
        cfg = ROUTING_TABLE.get(intent, ROUTING_TABLE[IntentCategory.GENERAL])
        return {
            "intent": intent.value,
            "required_agents": list(cfg.required_agents),
            "optional_agents": list(cfg.optional_agents),
            "required_tools": list(cfg.required_tools),
        }

    def route(self, query: str) -> dict | None:
        """Convenience: classify and route in one call.

        Returns the routing dict, or ``None`` if the query should be
        routed by the LLM instead.
        """
        intent = self.classify_intent(query)
        if intent is None:
            return None
        return self.get_routing(intent)
