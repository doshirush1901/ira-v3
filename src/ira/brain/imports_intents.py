"""Intent taxonomy and lightweight classifiers for imports metadata.

This module defines a controlled multi-label intent vocabulary used by
Alexandros metadata indexing and retrieval. Intents are normalized to avoid
free-form drift and provide predictable fast filtering.
"""

from __future__ import annotations

import re
from collections import Counter

INTENT_TAGS: tuple[str, ...] = (
    "quote_customer",
    "quote_vendor",
    "quote_internal",
    "rfq_customer",
    "rfq_vendor",
    "presentation_sales",
    "presentation_technical",
    "part_detail",
    "bom",
    "drawing",
    "spec_sheet",
    "invoice_customer",
    "invoice_vendor",
    "po_customer",
    "po_vendor",
    "contract_customer",
    "contract_vendor",
    "nda",
    "project_update",
    "installation_report",
    "service_report",
    "lead_list",
    "customer_profile",
    "vendor_profile",
)

COUNTERPARTY_TYPES: tuple[str, ...] = ("customer", "vendor", "internal", "unknown")

INTENT_ALIASES: dict[str, str] = {
    "customer quote": "quote_customer",
    "vendor quote": "quote_vendor",
    "quote": "quote_internal",
    "rfq": "rfq_customer",
    "customer rfq": "rfq_customer",
    "vendor rfq": "rfq_vendor",
    "presentation": "presentation_sales",
    "technical presentation": "presentation_technical",
    "part detail": "part_detail",
    "part details": "part_detail",
    "bom": "bom",
    "bill of materials": "bom",
    "drawing": "drawing",
    "spec sheet": "spec_sheet",
    "specification": "spec_sheet",
    "invoice": "invoice_vendor",
    "purchase order": "po_vendor",
    "po": "po_vendor",
    "contract": "contract_customer",
    "nda": "nda",
}

DOC_TYPE_DEFAULT_INTENTS: dict[str, list[str]] = {
    "quote": ["quote_internal"],
    "order": ["po_vendor"],
    "presentation": ["presentation_sales"],
    "manual": ["spec_sheet"],
    "technical_spec": ["spec_sheet"],
    "invoice": ["invoice_vendor"],
    "contract": ["contract_customer"],
    "lead_list": ["lead_list"],
    "customer_data": ["customer_profile"],
}

_RULE_PATTERNS: dict[str, tuple[str, ...]] = {
    "quote_customer": ("customer quote", "quote for", "quotation to customer"),
    "quote_vendor": ("vendor quote", "supplier quote", "quotation from"),
    "rfq_customer": ("rfq", "request for quotation", "customer inquiry"),
    "rfq_vendor": ("vendor inquiry", "request quote from vendor"),
    "presentation_sales": ("sales deck", "company profile", "pitch deck", "presentation"),
    "presentation_technical": ("technical presentation", "process flow", "line layout"),
    "part_detail": ("part detail", "part number", "component detail"),
    "bom": ("bill of materials", "bom"),
    "drawing": ("drawing", "cad", "dwg"),
    "spec_sheet": ("specification", "spec sheet", "technical spec"),
    "invoice_customer": ("invoice to customer",),
    "invoice_vendor": ("vendor invoice", "supplier invoice", "tax invoice"),
    "po_customer": ("customer po", "purchase order from customer"),
    "po_vendor": ("purchase order", "po ", "order to vendor"),
    "contract_customer": ("customer contract", "sales agreement"),
    "contract_vendor": ("vendor contract", "supplier agreement"),
    "nda": ("nda", "non disclosure"),
    "project_update": ("project update", "status report", "weekly update"),
    "installation_report": ("installation report", "commissioning report"),
    "service_report": ("service report", "after sales report"),
    "lead_list": ("lead list", "prospect list", "inquiry list"),
    "customer_profile": ("customer profile", "customer details"),
    "vendor_profile": ("vendor profile", "supplier details"),
}


def normalize_intent_tags(tags: list[str] | tuple[str, ...] | str | None) -> list[str]:
    """Normalize aliases and filter out unknown tags."""
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        raw = (tag or "").strip().lower().replace("-", "_")
        if not raw:
            continue
        canonical = INTENT_ALIASES.get(raw, raw)
        if canonical in INTENT_TAGS and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    return normalized


def infer_intents_from_text(text: str, *, doc_type: str = "") -> tuple[list[str], str, str, dict[str, float]]:
    """Infer intent tags from document text using deterministic rules."""
    haystack = text.lower()
    hits = Counter()

    for intent, phrases in _RULE_PATTERNS.items():
        for phrase in phrases:
            if phrase in haystack:
                hits[intent] += 1

    inferred = [intent for intent, _count in hits.most_common(4)]
    if not inferred and doc_type:
        inferred = DOC_TYPE_DEFAULT_INTENTS.get(doc_type.lower(), [])

    normalized = normalize_intent_tags(inferred)
    counterparty = infer_counterparty_type(haystack)
    role = infer_document_role(normalized)
    confidence = {intent: min(0.95, 0.55 + 0.1 * hits.get(intent, 0)) for intent in normalized}
    return normalized, counterparty, role, confidence


def infer_query_intents(query: str) -> tuple[list[str], str, str]:
    """Infer intent filters from a user query."""
    intents, counterparty, role, _ = infer_intents_from_text(query)
    return intents, counterparty, role


def infer_counterparty_type(text: str) -> str:
    """Infer counterparty type from lexical cues."""
    lowered = text.lower()
    if re.search(r"\b(vendor|supplier)\b", lowered):
        return "vendor"
    if re.search(r"\b(customer|client|buyer)\b", lowered):
        return "customer"
    if re.search(r"\b(internal|team|machinecraft)\b", lowered):
        return "internal"
    return "unknown"


def infer_document_role(intent_tags: list[str]) -> str:
    """Pick a single best document role from intent tags."""
    if not intent_tags:
        return "other"
    priority = [
        "quote_customer",
        "quote_vendor",
        "rfq_customer",
        "rfq_vendor",
        "part_detail",
        "bom",
        "drawing",
        "spec_sheet",
        "presentation_technical",
        "presentation_sales",
        "invoice_customer",
        "invoice_vendor",
        "po_customer",
        "po_vendor",
        "contract_customer",
        "contract_vendor",
        "nda",
        "project_update",
        "installation_report",
        "service_report",
        "lead_list",
        "customer_profile",
        "vendor_profile",
    ]
    for role in priority:
        if role in intent_tags:
            return role
    return intent_tags[0]
