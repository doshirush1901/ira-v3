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
    VENDOR_PROCUREMENT = "VENDOR_PROCUREMENT"
    PROJECT_MANAGEMENT = "PROJECT_MANAGEMENT"
    QUALITY_MANAGEMENT = "QUALITY_MANAGEMENT"
    CASE_STUDY = "CASE_STUDY"
    QUOTE_GENERATION = "QUOTE_GENERATION"
    ARCHIVE_SEARCH = "ARCHIVE_SEARCH"
    CONTACT_CLASSIFICATION = "CONTACT_CLASSIFICATION"
    MEMORY_RECALL = "MEMORY_RECALL"
    SYSTEM_TRAINING = "SYSTEM_TRAINING"
    GENERAL = "GENERAL"


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """Which agents and tools a given intent requires."""

    required_agents: tuple[str, ...]
    optional_agents: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()


ROUTING_TABLE: dict[IntentCategory, RoutingConfig] = {
    IntentCategory.SALES_PIPELINE: RoutingConfig(
        required_agents=("prometheus", "atlas", "clio", "chiron"),
        optional_agents=("tyche", "alexandros"),
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
        required_tools=("retriever",),
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
        optional_agents=("iris", "vera", "alexandros"),
        required_tools=("retriever",),
    ),
    IntentCategory.QUOTE_REQUEST: RoutingConfig(
        required_agents=("prometheus", "plutus", "hephaestus"),
        optional_agents=("calliope",),
        required_tools=("pricing_engine", "crm", "retriever"),
    ),
    IntentCategory.VENDOR_PROCUREMENT: RoutingConfig(
        required_agents=("hera",),
        optional_agents=("clio", "plutus"),
        required_tools=("retriever",),
    ),
    IntentCategory.PROJECT_MANAGEMENT: RoutingConfig(
        required_agents=("atlas",),
        optional_agents=("clio", "hephaestus"),
        required_tools=("retriever",),
    ),
    IntentCategory.QUALITY_MANAGEMENT: RoutingConfig(
        required_agents=("asclepius",),
        optional_agents=("atlas", "hephaestus"),
        required_tools=("retriever",),
    ),
    IntentCategory.CASE_STUDY: RoutingConfig(
        required_agents=("cadmus",),
        optional_agents=("clio", "calliope"),
        required_tools=("retriever",),
    ),
    IntentCategory.QUOTE_GENERATION: RoutingConfig(
        required_agents=("quotebuilder", "plutus", "hephaestus"),
        optional_agents=("calliope",),
        required_tools=("pricing_engine", "retriever"),
    ),
    IntentCategory.ARCHIVE_SEARCH: RoutingConfig(
        required_agents=("alexandros",),
        optional_agents=("clio",),
        required_tools=("retriever",),
    ),
    IntentCategory.CONTACT_CLASSIFICATION: RoutingConfig(
        required_agents=("delphi",),
        optional_agents=("clio", "prometheus"),
        required_tools=("crm", "retriever"),
    ),
    IntentCategory.MEMORY_RECALL: RoutingConfig(
        required_agents=("mnemosyne", "sophia"),
        optional_agents=("clio",),
        required_tools=("retriever",),
    ),
    IntentCategory.SYSTEM_TRAINING: RoutingConfig(
        required_agents=("nemesis", "sophia", "chiron"),
        optional_agents=(),
        required_tools=("retriever",),
    ),
    IntentCategory.GENERAL: RoutingConfig(
        required_agents=("clio",),
        optional_agents=("sphinx", "alexandros"),
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
    # Sales / pipeline / order book
    (r"\bpipeline\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bsales\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bdeals?\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bleads?\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bcrm\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bsales\s+funnel\b", IntentCategory.SALES_PIPELINE, 2.0),
    (r"\bconversion\s+rate\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\bwin\s+rate\b", IntentCategory.SALES_PIPELINE, 1.5),
    (r"\border\s*book\b", IntentCategory.SALES_PIPELINE, 3.0),
    (r"\bhot\s+leads?\b", IntentCategory.SALES_PIPELINE, 3.0),
    (r"\bproposals?\s+sent\b", IntentCategory.SALES_PIPELINE, 2.5),
    (r"\bquotes?\s+sent\b", IntentCategory.SALES_PIPELINE, 2.5),
    (r"\bmissed\s+leads?\b", IntentCategory.SALES_PIPELINE, 3.0),
    (r"\bclient\s*list\b", IntentCategory.SALES_PIPELINE, 2.5),
    (r"\bcustomer\s*list\b", IntentCategory.SALES_PIPELINE, 2.5),
    (r"\bactive\s+orders?\b", IntentCategory.SALES_PIPELINE, 2.5),
    (r"\bin\s+production\b", IntentCategory.SALES_PIPELINE, 1.5),

    # Quote / pricing — checked before machine specs so that queries
    # mentioning both a model name and a pricing keyword route here.
    (r"\bquote\b", IntentCategory.QUOTE_REQUEST, 3.0),
    (r"\bpric(e|ing)\b", IntentCategory.QUOTE_REQUEST, 3.0),
    (r"\bcost\b", IntentCategory.QUOTE_REQUEST, 2.5),
    (r"\bhow\s+much\b", IntentCategory.QUOTE_REQUEST, 3.0),
    (r"\bproposal\b", IntentCategory.QUOTE_REQUEST, 1.5),
    (r"\bestimate\b", IntentCategory.QUOTE_REQUEST, 1.0),
    (r"\bbudget\b", IntentCategory.QUOTE_REQUEST, 1.0),

    # Machine specs
    (r"\bmachine\b", IntentCategory.MACHINE_SPECS, 1.5),
    (r"\bspecs?\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bspecification", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bPF[12]-[A-Z]-?\d+\b", IntentCategory.MACHINE_SPECS, 3.0),
    (r"\bPF[12]-[A-Z]\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bPF[12]\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bPF1-C\b", IntentCategory.MACHINE_SPECS, 2.5),
    (r"\bAM[\s-]?series\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bRF-100\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bSL-500\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bVFM\b", IntentCategory.MACHINE_SPECS, 2.0),
    (r"\bthermoform", IntentCategory.MACHINE_SPECS, 1.5),
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

    # Customer service / email
    (r"\bcomplaint\b", IntentCategory.CUSTOMER_SERVICE, 2.0),
    (r"\bsupport\s+ticket\b", IntentCategory.CUSTOMER_SERVICE, 2.0),
    (r"\bwarranty\b", IntentCategory.CUSTOMER_SERVICE, 1.5),
    (r"\bafter[\s-]?sales\b", IntentCategory.CUSTOMER_SERVICE, 2.0),
    (r"\bemail\s+(from|to|about|thread)\b", IntentCategory.CUSTOMER_SERVICE, 3.0),
    (r"\bfind\s+emails?\b", IntentCategory.CUSTOMER_SERVICE, 3.0),
    (r"\bpull\s+up\s+emails?\b", IntentCategory.CUSTOMER_SERVICE, 3.0),
    (r"\blast\s+email\b", IntentCategory.CUSTOMER_SERVICE, 2.5),
    (r"\binbox\b", IntentCategory.CUSTOMER_SERVICE, 1.5),

    # Research
    (r"\bresearch\b", IntentCategory.RESEARCH, 1.5),
    (r"\bmarket\s+analysis\b", IntentCategory.RESEARCH, 2.0),
    (r"\bcompetitor", IntentCategory.RESEARCH, 1.5),
    (r"\bindustry\s+trend", IntentCategory.RESEARCH, 1.5),

    # Vendor / procurement
    (r"\bvendor\b", IntentCategory.VENDOR_PROCUREMENT, 2.0),
    (r"\bsupplier\b", IntentCategory.VENDOR_PROCUREMENT, 2.0),
    (r"\bprocurement\b", IntentCategory.VENDOR_PROCUREMENT, 2.5),
    (r"\bcomponent\b", IntentCategory.VENDOR_PROCUREMENT, 1.5),
    (r"\binventory\b", IntentCategory.VENDOR_PROCUREMENT, 1.5),
    (r"\bstock\b", IntentCategory.VENDOR_PROCUREMENT, 1.0),
    (r"\bpart\s+number\b", IntentCategory.VENDOR_PROCUREMENT, 2.0),

    # Project management / delivery / order status
    (r"\bproject\b", IntentCategory.PROJECT_MANAGEMENT, 1.5),
    (r"\blogbook\b", IntentCategory.PROJECT_MANAGEMENT, 2.0),
    (r"\bmilestone\b", IntentCategory.PROJECT_MANAGEMENT, 2.0),
    (r"\bdelivery\s+schedule\b", IntentCategory.PROJECT_MANAGEMENT, 2.0),
    (r"\bpayment\s+alert\b", IntentCategory.PROJECT_MANAGEMENT, 2.0),
    (r"\bdelivery\s+(date|status|time)", IntentCategory.PROJECT_MANAGEMENT, 3.0),
    (r"\border\s+status\b", IntentCategory.PROJECT_MANAGEMENT, 3.0),
    (r"\bwhen\s+(is|will)\s+.+\s+(ship|deliver|dispatch)", IntentCategory.PROJECT_MANAGEMENT, 3.0),
    (r"\bshipping\s+date\b", IntentCategory.PROJECT_MANAGEMENT, 2.5),
    (r"\bdispatch\b", IntentCategory.PROJECT_MANAGEMENT, 1.5),

    # Payment / invoice (routes to finance)
    (r"\bpayment\s+status\b", IntentCategory.FINANCE_REVIEW, 3.0),
    (r"\binvoice\b", IntentCategory.FINANCE_REVIEW, 2.5),
    (r"\bpayment\s+(due|overdue|received|pending)\b", IntentCategory.FINANCE_REVIEW, 3.0),
    (r"\b(AR|AP)\s+(aging|status|overdue)\b", IntentCategory.FINANCE_REVIEW, 3.0),
    (r"\baccounts?\s+(receivable|payable)\b", IntentCategory.FINANCE_REVIEW, 2.5),

    # Quality management
    (r"\bpunch\s*list\b", IntentCategory.QUALITY_MANAGEMENT, 3.0),
    (r"\bquality\b", IntentCategory.QUALITY_MANAGEMENT, 1.5),
    (r"\bFAT\b", IntentCategory.QUALITY_MANAGEMENT, 2.5),
    (r"\binstallation\b", IntentCategory.QUALITY_MANAGEMENT, 1.0),
    (r"\bcommissioning\b", IntentCategory.QUALITY_MANAGEMENT, 2.0),
    (r"\bdefect\b", IntentCategory.QUALITY_MANAGEMENT, 2.0),
    (r"\bsnag\b", IntentCategory.QUALITY_MANAGEMENT, 2.0),

    # Case study / content
    (r"\bcase\s+stud", IntentCategory.CASE_STUDY, 3.0),
    (r"\blinkedin\s+post\b", IntentCategory.CASE_STUDY, 3.0),
    (r"\bsuccess\s+stor", IntentCategory.CASE_STUDY, 2.5),
    (r"\bcontent\s+draft\b", IntentCategory.CASE_STUDY, 2.0),

    # Quote generation (PDF/document, not pricing inquiry)
    (r"\bgenerate\s+quote\b", IntentCategory.QUOTE_GENERATION, 3.0),
    (r"\bbuild\s+quote\b", IntentCategory.QUOTE_GENERATION, 3.0),
    (r"\bquote\s+PDF\b", IntentCategory.QUOTE_GENERATION, 3.0),
    (r"\bformal\s+quote\b", IntentCategory.QUOTE_GENERATION, 3.0),
    (r"\bquote\s+document\b", IntentCategory.QUOTE_GENERATION, 2.5),

    # Contact classification
    (r"\bclassif", IntentCategory.CONTACT_CLASSIFICATION, 2.0),
    (r"\bwho\s+is\b.*\bcontact\b", IntentCategory.CONTACT_CLASSIFICATION, 2.5),
    (r"\bcontact\s+type\b", IntentCategory.CONTACT_CLASSIFICATION, 2.5),
    (r"\bcustomer\s+or\s+vendor\b", IntentCategory.CONTACT_CLASSIFICATION, 3.0),

    # Memory recall
    (r"\bremember\b", IntentCategory.MEMORY_RECALL, 2.0),
    (r"\brecall\b", IntentCategory.MEMORY_RECALL, 2.0),
    (r"\bwhat\s+did\s+(we|i|you)\s+(discuss|talk|say)\b", IntentCategory.MEMORY_RECALL, 3.0),
    (r"\blast\s+time\b", IntentCategory.MEMORY_RECALL, 1.5),
    (r"\bprevious\s+conversation\b", IntentCategory.MEMORY_RECALL, 3.0),

    # System training / self-improvement
    (r"\btrain\b", IntentCategory.SYSTEM_TRAINING, 2.0),
    (r"\bself[\s-]?assess", IntentCategory.SYSTEM_TRAINING, 2.5),
    (r"\bweak\s+area", IntentCategory.SYSTEM_TRAINING, 2.0),
    (r"\bimprove\s+yourself\b", IntentCategory.SYSTEM_TRAINING, 2.5),

    # Archive / document search
    (r"\barchive\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bimports?\b", IntentCategory.ARCHIVE_SEARCH, 2.0),
    (r"\bbrowse\s+documents?\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bbrowse\s+files?\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bfind\s+the\s+file\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bfind\s+the\s+document\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bread\s+the\s+document\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\braw\s+document\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\bdata/imports\b", IntentCategory.ARCHIVE_SEARCH, 3.0),
    (r"\blook\s+up\s+file\b", IntentCategory.ARCHIVE_SEARCH, 2.5),
    (r"\boriginal\s+(file|document|pdf)\b", IntentCategory.ARCHIVE_SEARCH, 2.5),
    (r"\bsource\s+document\b", IntentCategory.ARCHIVE_SEARCH, 2.5),
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
