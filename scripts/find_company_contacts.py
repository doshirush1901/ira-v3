#!/usr/bin/env python3
"""Search mailbox for emails mentioning a company and return up to 3 unique contacts (emails) at that company.

Use before sending lead emails so we can send to multiple people (to + cc) — if one has left, others still get it.

Usage:
  poetry run python scripts/find_company_contacts.py "Big Bear"
  poetry run python scripts/find_company_contacts.py "Big Bear" --domain big-bear.co.uk
  poetry run python scripts/find_company_contacts.py "Tricomposite" --max 5

Requires: Ira API running (Gmail).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"

# Our sending addresses — exclude so we don't list ourselves as contacts
OUR_DOMAINS = ("machinecraft.org", "machinecraft.in")


def extract_emails(from_or_to: str) -> list[str]:
    """Parse 'Name <email>' or 'email' or 'a@x.com, b@y.com' into list of lowercase emails."""
    if not from_or_to or not from_or_to.strip():
        return []
    out = set()
    # Split by comma for multiple recipients
    for part in from_or_to.split(","):
        part = part.strip()
        # Match <email@domain.com>
        m = re.search(r"<([^>]+@[^>]+)>", part)
        if m:
            out.add(m.group(1).strip().lower())
        else:
            # Plain email
            if "@" in part and " " not in part.split("@")[0]:
                out.add(part.lower())
    return list(out)


def is_our_domain(email: str) -> bool:
    return any(d in email.lower() for d in OUR_DOMAINS)


def find_company_contacts(
    company_query: str,
    *,
    domain_hint: str | None = None,
    max_results: int = 30,
    max_contacts: int = 3,
) -> list[str]:
    """Search Gmail for company_query; return up to max_contacts unique emails at that company."""
    try:
        r = httpx.post(
            f"{BASE}/api/email/search",
            json={"query": company_query, "max_results": max_results},
            timeout=30.0,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Search failed: {e}", file=sys.stderr)
        return []

    data = r.json()
    emails = data.get("emails", [])
    candidates: set[str] = set()

    for e in emails:
        for field in ("from", "to"):
            raw = e.get(field) or ""
            for addr in extract_emails(raw):
                if is_our_domain(addr):
                    continue
                if domain_hint:
                    if domain_hint.lower() in addr.lower():
                        candidates.add(addr)
                else:
                    # Search was by company name — any external address in results is a candidate
                    candidates.add(addr)

    # Prefer addresses that match company name/domain slug (e.g. big-bear in addr)
    slug = company_query.lower().replace(" ", "-").replace(" ", "")
    with_domain = [a for a in candidates if slug in a or company_query.lower() in a]
    rest = [a for a in candidates if a not in with_domain]
    ordered = with_domain + rest

    return ordered[:max_contacts]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find up to 3 contacts at a company from your mailbox.")
    ap.add_argument("company_query", help="Company name to search (e.g. 'Big Bear')")
    ap.add_argument("--domain", default=None, help="Optional domain to filter (e.g. big-bear.co.uk)")
    ap.add_argument("--max", type=int, default=3, help="Max contacts to return (default 3)")
    ap.add_argument("--search-max", type=int, default=30, help="Max emails to fetch from search (default 30)")
    args = ap.parse_args()

    contacts = find_company_contacts(
        args.company_query,
        domain_hint=args.domain,
        max_results=args.search_max,
        max_contacts=args.max,
    )
    if not contacts:
        print("No contacts found. Try a different query or --domain.", file=sys.stderr)
        sys.exit(1)
    for c in contacts:
        print(c)


if __name__ == "__main__":
    main()
