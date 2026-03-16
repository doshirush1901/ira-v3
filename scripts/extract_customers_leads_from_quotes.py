#!/usr/bin/env python3
"""Extract customers, leads, and contact details from 01_Quotes_and_Proposals.

Reads the imports metadata index (data/brain/imports_metadata.json) and
optionally Qdrant/Neo4j to produce a structured report of companies and
people mentioned in quote PDFs, with document context.

Usage:
  poetry run python scripts/extract_customers_leads_from_quotes.py
  poetry run python scripts/extract_customers_leads_from_quotes.py --json > report.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = PROJECT_ROOT / "data" / "brain" / "imports_metadata.json"
QUOTES_PREFIX = "01_Quotes_and_Proposals/"

# Internal / skip
SKIP_ENTITIES = {"Machinecraft", "Machinecraft Technologies", "India", "Mumbai", "Rushabh Doshi"}


def normalize_company(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).strip()


def main() -> None:
    if not INDEX_PATH.exists():
        print("Metadata index not found. Run: ira index-imports --force --include-prefix 01_Quotes_and_Proposals")
        return

    index = json.loads(INDEX_PATH.read_text())
    files = index.get("files", {})

    # Aggregate by entity (company/person) -> list of (filename, summary, machines, doc_type)
    companies: dict[str, list[dict]] = defaultdict(list)
    people: dict[str, list[dict]] = defaultdict(list)
    seen_docs: dict[str, set[str]] = defaultdict(set)  # entity -> set of rel_path

    for rel_path, meta in files.items():
        if not rel_path.startswith(QUOTES_PREFIX):
            continue
        name = meta.get("name", rel_path.split("/")[-1])
        summary = meta.get("summary", "")
        doc_type = meta.get("doc_type", "other")
        machines = meta.get("machines", [])
        entities = meta.get("entities", [])
        keywords = meta.get("keywords", [])

        doc_ctx = {
            "document": name,
            "summary": summary[:300] + "..." if len(summary) > 300 else summary,
            "doc_type": doc_type,
            "machines": machines,
            "keywords": keywords[:8],
        }

        for e in entities:
            e_clean = normalize_company(e)
            if not e_clean or e_clean in SKIP_ENTITIES:
                continue
            # Heuristic: title case with multiple words or known suffixes -> company
            is_likely_company = (
                " " in e_clean
                or e_clean.endswith("AG")
                or e_clean.endswith("GmbH")
                or e_clean.endswith("Ltd")
                or e_clean.endswith("Inc")
                or e_clean.endswith("LLC")
                or e_clean.endswith("Corp")
                or e_clean.endswith("India")
                or e_clean.endswith("Canada")
                or e_clean.endswith("Russia")
                or e_clean.endswith("UAE")
            )
            if rel_path not in seen_docs[e_clean]:
                seen_docs[e_clean].add(rel_path)
                if is_likely_company:
                    companies[e_clean].append(doc_ctx)
                else:
                    people[e_clean].append(doc_ctx)

    # Build report
    report = {
        "source": "data/brain/imports_metadata.json",
        "folder": "01_Quotes_and_Proposals",
        "total_quote_documents": len([p for p in files if p.startswith(QUOTES_PREFIX)]),
        "customers_and_leads": [],
        "contacts_mentioned": [],
    }

    for company, docs in sorted(companies.items(), key=lambda x: -len(x[1])):
        report["customers_and_leads"].append({
            "name": company,
            "type": "company",
            "quote_count": len(docs),
            "documents": docs[:5],
            "machines_mentioned": list({m for d in docs for m in d.get("machines", [])})[:15],
        })

    for person, docs in sorted(people.items(), key=lambda x: -len(x[1])):
        report["contacts_mentioned"].append({
            "name": person,
            "quote_count": len(docs),
            "documents": docs[:3],
        })

    # Print Markdown report
    print("# Customers & leads from 01_Quotes_and_Proposals\n")
    print(f"*Source: imports metadata index. Total quote documents: {report['total_quote_documents']}.*\n")
    print("## Companies / customers (by number of quotes)\n")
    for c in report["customers_and_leads"][:80]:
        print(f"### {c['name']}")
        print(f"- **Quotes:** {c['quote_count']}")
        if c.get("machines_mentioned"):
            print(f"- **Machines:** {', '.join(c['machines_mentioned'][:10])}")
        for d in c["documents"][:2]:
            print(f"- *{d['document']}* — {d['summary'][:120]}...")
        print()
    print("## Contacts / people mentioned\n")
    for p in report["contacts_mentioned"][:40]:
        print(f"- **{p['name']}** — in {p['quote_count']} quote(s)")
    print("\n---")
    print("*Semantic note: these are outbound quotes we sent; follow-up status is not in the documents.*")


if __name__ == "__main__":
    main()
