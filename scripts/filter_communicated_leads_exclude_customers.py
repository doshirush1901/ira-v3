#!/usr/bin/env python3
"""Filter communicated-only leads CSV by excluding known customers.

Reads data/reports/known_customers_exclude_from_leads.txt and
data/reports/leads_communicated_only.csv; writes
data/reports/leads_communicated_leads_only.csv (no customers).

Usage:
  poetry run python scripts/filter_communicated_leads_exclude_customers.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_FILE = PROJECT_ROOT / "data" / "reports" / "known_customers_exclude_from_leads.txt"
INPUT_CSV = PROJECT_ROOT / "data" / "reports" / "leads_communicated_only.csv"
OUTPUT_CSV = PROJECT_ROOT / "data" / "reports" / "leads_communicated_leads_only.csv"


def _normalize(s: str) -> str:
    """Lowercase, keep alphanumeric, collapse spaces."""
    if not s:
        return ""
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = " ".join(s.split())
    return s


def load_exclusion_list(path: Path) -> tuple[set[str], set[str]]:
    """Return (name_patterns, domains). name_patterns are normalized strings; domains are lowercased."""
    name_patterns: set[str] = set()
    domains: set[str] = set()
    if not path.exists():
        return name_patterns, domains
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("domain:"):
            domains.add(line[7:].strip().lower())
        else:
            name_patterns.add(_normalize(line))
    return name_patterns, domains


def is_customer(company: str, email: str, name_patterns: set[str], domains: set[str]) -> bool:
    """True if this row is a known customer (exclude from leads list)."""
    # Domain match first (reliable)
    if email and "@" in email:
        domain = email.split("@")[-1].lower()
        for d in domains:
            if domain == d or domain.endswith("." + d):
                return True
    norm_company = _normalize(company or "")
    # Don't treat empty/dash company as matching name patterns (would match all)
    if not norm_company or norm_company in ("x", "—"):
        return False
    company_squashed = norm_company.replace(" ", "")
    for pat in name_patterns:
        if not pat or len(pat) < 3:
            continue
        pat_squashed = pat.replace(" ", "")
        # Company contains pattern (e.g. "anatomicsitt" contains "anatomic")
        if len(pat_squashed) >= 4 and pat_squashed in company_squashed:
            return True
        # Pattern contains company only if company is substantial (avoid "tom" in "anatomic")
        if len(company_squashed) >= 5 and company_squashed in pat_squashed:
            return True
    return False


def main() -> None:
    name_patterns, domains = load_exclusion_list(EXCLUDE_FILE)
    print(f"Loaded {len(name_patterns)} name patterns and {len(domains)} domains to exclude", flush=True)

    if not INPUT_CSV.exists():
        print(f"Input not found: {INPUT_CSV}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, str]] = []
    excluded: list[tuple[str, str]] = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        fieldnames = r.fieldnames or []
        for row in r:
            company = row.get("company", "")
            email = row.get("email", "")
            if is_customer(company, email, name_patterns, domains):
                excluded.append((email, company))
                continue
            rows.append(row)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Excluded {len(excluded)} customers:", flush=True)
    for email, company in excluded:
        print(f"  - {company or '(no company)'} | {email}", flush=True)
    print(f"\nRemaining leads (no customers): {len(rows)}", flush=True)
    print(f"Wrote: {OUTPUT_CSV}", flush=True)


if __name__ == "__main__":
    main()
