"""
E1.5: Enrich company and country for new leads from inbound email body.

Extracts company name and country from signature and body using regex patterns.
Optional: LLM extraction for ambiguous cases (future).
"""

import re
import logging
from typing import Dict

logger = logging.getLogger("ira.crm.lead_enrichment")

# Common signature patterns (order matters: more specific first)
_COMPANY_PATTERNS = [
    re.compile(r"(?:company|organisation|organization|firma)\s*[:\-]\s*([^\n<,]+)", re.I),
    re.compile(r"^([A-Za-z0-9][A-Za-z0-9\s&\-\.]+(?:GmbH|Ltd|Limited|Inc|LLC|B\.V\.|BV|Pty|AG|SA|S\.A\.|Corp|Corporation))\s*$", re.M),
    re.compile(r"(?:at|@)\s+([A-Za-z0-9][A-Za-z0-9\s&\-\.]+(?:GmbH|Ltd|Limited|Inc|B\.V\.|BV))\b", re.I),
]
_COUNTRY_PATTERNS = [
    re.compile(r"(?:country|based in|located in|office in)\s*[:\-]\s*([^\n<,]+)", re.I),
    re.compile(r"\b(Germany|Netherlands|India|USA|United States|UK|United Kingdom|France|Italy|Spain|Poland|Czech Republic|Belgium|Austria|Switzerland|Japan|China|UAE|Canada|Australia)\b", re.I),
]


def enrich_contact_from_email(body: str, from_email: str = "") -> Dict[str, str]:
    """
    Extract company and country from email body (e.g. signature block).

    Returns {"company": "...", "country": ""}. Empty string if not found.
    """
    out: Dict[str, str] = {"company": "", "country": ""}
    if not (body or "").strip():
        return out
    text = (body or "")[:4000]  # focus on first part (signature often at end, but we scan full)
    # Prefer last occurrence (signature usually at bottom)
    for pat in _COMPANY_PATTERNS:
        matches = pat.findall(text)
        if matches:
            candidate = matches[-1].strip()
            if len(candidate) > 1 and len(candidate) < 120:
                out["company"] = candidate
                break
    for pat in _COUNTRY_PATTERNS:
        matches = pat.findall(text)
        if matches:
            candidate = matches[-1].strip()
            if len(candidate) > 1 and len(candidate) < 80:
                out["country"] = candidate
                break
    # Fallback: domain hint (e.g. name@acme.de -> Germany)
    if not out["country"] and from_email and "@" in from_email:
        domain = from_email.split("@")[-1].lower()
        if domain.endswith(".de"):
            out["country"] = "Germany"
        elif domain.endswith(".nl"):
            out["country"] = "Netherlands"
        elif domain.endswith(".in"):
            out["country"] = "India"
        elif domain.endswith(".co.uk") or domain.endswith(".uk"):
            out["country"] = "United Kingdom"
        elif domain.endswith(".fr"):
            out["country"] = "France"
        elif domain.endswith(".it"):
            out["country"] = "Italy"
        elif domain.endswith(".es"):
            out["country"] = "Spain"
        elif domain.endswith(".pl"):
            out["country"] = "Poland"
        elif domain.endswith(".jp"):
            out["country"] = "Japan"
        elif domain.endswith(".cn"):
            out["country"] = "China"
        elif domain.endswith(".ae"):
            out["country"] = "UAE"
        elif domain.endswith(".com") or domain.endswith(".org"):
            pass  # too generic
    return out
