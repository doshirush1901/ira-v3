#!/usr/bin/env python3
"""
Draft a document-backed engagement email for any lead from enriched_leads.json.

Flow (same as Vladimir): hybrid_search by industry/specs → extract PDF text →
LLM extract insights → LLM generate final email (Rushabh voice, mobile-friendly bullets).

Usage:
  poetry run python scripts/draft_lead_engagement_email.py --lead-id 2
  poetry run python scripts/draft_lead_engagement_email.py --lead-id 2 --max-pdfs 5
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

IMPORTS_DIR = PROJECT_ROOT / "data" / "imports"
LEADS_DIR = IMPORTS_DIR / "24_WebSite_Leads"
ENRICHED_LEADS_PATH = LEADS_DIR / "ira-drip-campaign" / "data" / "enriched_leads.json"
MAX_EXTRACT_CHARS_PER_FILE = 10_000


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "lead"


def load_lead(lead_id: int) -> dict:
    data = json.loads(ENRICHED_LEADS_PATH.read_text(encoding="utf-8"))
    for L in data:
        if L.get("id") == lead_id:
            return L
    raise ValueError(f"Lead id {lead_id} not found in {ENRICHED_LEADS_PATH}")


async def get_files_for_lead(lead: dict, max_pdfs: int) -> list[tuple[Path, str]]:
    from ira.brain.imports_fallback_retriever import hybrid_search

    industry = lead.get("industry_segment") or lead.get("customer_interest") or ""
    specs = lead.get("specs") or {}
    area = specs.get("forming_area", "")
    materials = specs.get("materials", "")
    query = f"thermoforming PF1 vacuum forming {industry} {area} {materials}"
    query = " ".join(query.split())

    candidates = await hybrid_search(query, limit=max_pdfs * 2)
    out: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for c in candidates:
        path_str = c.get("path", "")
        if not path_str or path_str in seen:
            continue
        path = Path(path_str)
        if path.suffix.lower() != ".pdf" or not path.exists():
            continue
        seen.add(path_str)
        out.append((path, c.get("name", path.name)))
        if len(out) >= max_pdfs:
            break
    return out


async def extract_texts(files: list[tuple[Path, str]]) -> list[tuple[str, str]]:
    from ira.brain.imports_fallback_retriever import extract_file_text

    results = []
    for path, name in files:
        text = await extract_file_text(path, max_chars=MAX_EXTRACT_CHARS_PER_FILE)
        if text and len(text.strip()) > 100:
            results.append((name, text))
        else:
            print(f"  [skip] {name}: too little text")
    return results


async def extract_insights(doc_snippets: list[tuple[str, str]], lead: dict) -> str:
    from ira.services.llm_client import get_llm_client

    combined = "\n\n---\n\n".join(f"[Document: {name}]\n\n{text}" for name, text in doc_snippets)
    industry = lead.get("industry_segment") or lead.get("customer_interest") or "industrial"
    area = (lead.get("specs") or {}).get("forming_area", "")

    system = """You are a sales-support analyst for Machinecraft (thermoforming machinery).
Your task: read document excerpts and extract the most useful facts for a sales email to this prospect.
Focus on: specs (forming area, draw, cycle time), customer names and projects, process differentiators, quotable details.
Output a concise bullet list. No preamble."""

    user = f"""From these document excerpts, extract the best facts for a {industry} prospect (forming area {area}).

{combined[:28000]}

Bullet list of insights (one line per bullet):"""

    client = get_llm_client()
    return await client.generate_text(
        system=system,
        user=user,
        max_tokens=1500,
        temperature=0.2,
        name="lead_engagement_extract_insights",
    )


def read_draft_body_for_lead(lead_id: int, lead: dict) -> str:
    slug = _slug(lead.get("client_name", "") or "") or _slug(lead.get("company_name", ""))
    draft_path = LEADS_DIR / f"draft_email1_lead{lead_id}_{slug}.md"
    if not draft_path.exists():
        return ""
    text = draft_path.read_text(encoding="utf-8")
    start = text.find("## Draft body")
    if start == -1:
        start = text.find("Hi ")
    if start == -1:
        return text
    start = text.find("\n", start) + 1 if "## Draft body" in text[start:start+20] else start
    end = text.find("Best regards,", start)
    if end != -1:
        end = text.find("\n", end)
    else:
        end = len(text)
    return text[start:end].strip()


async def generate_final_email(lead: dict, draft_body: str, insights: str) -> str:
    from ira.services.llm_client import get_llm_client
    from ira.prompt_loader import load_prompt

    voice_brand = load_prompt("email_rushabh_voice_brand")
    name = lead.get("client_name", "there")
    company = lead.get("company_name", "")
    email = lead.get("email", "")
    industry = lead.get("industry_segment") or lead.get("customer_interest", "")
    specs = lead.get("specs") or {}

    system = f"""You are Calliope, Machinecraft's writer. Write a re-engagement email for {name} ({company}, {email}).
They filled out our PF1 inquiry form; this email should be concrete and valuable so they reply.
Use the draft body as the base if provided. Weave in 1–3 concrete details from the EXTRACTED INSIGHTS.
Tone: professional, warm, decisive. No fluff. Use "I" not "we". Short paragraphs. One clear CTA at the end.
Sign-off: Best regards, Rushabh Doshi, Director — Machinecraft.

IMPORTANT — Email formatting (mobile-friendly): Do NOT use Markdown pipe tables. Use bullet points for any tech specs or feature lists. Format each as: • **Label:** value — short note. No multi-column tables in the body.

--- RUSHABH VOICE & BRAND ---
{voice_brand}
--- END ---

Output format:
Subject: <subject line>
<blank line>
<body>"""

    spec_summary = ", ".join(f"{k}: {v}" for k, v in list(specs.items())[:6]) if specs else "see inquiry"
    user = f"""Lead: {name}, {company}. Industry: {industry}. Key specs: {spec_summary}.

DRAFT BODY (use as base if not empty, else write from scratch):
{draft_body or "(none — write a short, personalised re-engagement paragraph and a spec summary in bullets)"}

EXTRACTED INSIGHTS (weave in 1–3 where they fit):
{insights}

Produce the final email: Subject line then body. Use bullet points for specs/references, not tables."""

    client = get_llm_client()
    return await client.generate_text(
        system=system,
        user=user,
        max_tokens=2500,
        temperature=0.35,
        name="lead_engagement_final",
    )


async def main(lead_id: int = 2, max_pdfs: int = 5) -> None:
    lead = load_lead(lead_id)
    name = lead.get("client_name", "?")
    company = lead.get("company_name", "?")
    print(f"Lead {lead_id}: {name}, {company}")

    print("1. Alexandros-style search for relevant docs...")
    files = await get_files_for_lead(lead, max_pdfs)
    if not files:
        print("   No PDFs found. Proceeding without doc insights.")
        doc_snippets = []
    else:
        for path, fname in files:
            print(f"   - {fname}")
        print("\n2. Extracting text from PDFs...")
        doc_snippets = await extract_texts(files)
        print(f"   Extracted {len(doc_snippets)} docs.")

    insights = ""
    if doc_snippets:
        print("\n3. Extracting insights via LLM...")
        insights = await extract_insights(doc_snippets, lead)
        print(insights[:600] + ("..." if len(insights) > 600 else ""))
    else:
        print("\n3. Skipping insights (no docs).")

    print("\n4. Generating final email...")
    draft_body = read_draft_body_for_lead(lead_id, lead)
    final_email = await generate_final_email(lead, draft_body, insights)

    slug = _slug(name) or _slug(company) or f"lead{lead_id}"
    out_path = LEADS_DIR / f"email_lead{lead_id}_{slug}_FINAL.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"# Engagement email — Lead {lead_id}: {name}, {company}\n\n"
    header += "Sources: enriched_leads + Alexandros-style search → PDFs → LLM insights → LLM final. Mobile-friendly bullets, no tables.\n\n---\n\n"
    out_path.write_text(header + final_email, encoding="utf-8")
    print(f"\n5. Wrote: {out_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Draft document-backed engagement email for a lead")
    p.add_argument("--lead-id", type=int, default=2, help="enriched_leads.json id (default 2)")
    p.add_argument("--max-pdfs", type=int, default=5, help="Max PDFs to read (default 5)")
    args = p.parse_args()
    asyncio.run(main(lead_id=args.lead_id, max_pdfs=args.max_pdfs))
