#!/usr/bin/env python3
"""
Ask Alexandros-style search for bath/sanitary files, read those PDFs,
extract cool information via LLM, and generate the final Vladimir Kilunin
engagement email.

Flow:
  1. hybrid_search("bath sanitary bathtub PF1 Mirsant Jaguar") or fallback file list
  2. Extract text from top N PDFs (extract_file_text)
  3. LLM: extract specs, process details, differentiators, quotable lines
  4. LLM: generate final email body + subject using draft + extracted insights
  5. Write to data/imports/24_WebSite_Leads/email_vladimir_kilunin_FINAL.md

Usage:
  poetry run python scripts/vladimir_email_from_imports.py
  poetry run python scripts/vladimir_email_from_imports.py --max-pdfs 3
"""

from __future__ import annotations

import asyncio
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

# Paths
IMPORTS_DIR = PROJECT_ROOT / "data" / "imports"
DRAFT_PATH = PROJECT_ROOT / "data" / "imports" / "24_WebSite_Leads" / "email_vladimir_kilunin_engagement_draft.md"
FINAL_PATH = PROJECT_ROOT / "data" / "imports" / "24_WebSite_Leads" / "email_vladimir_kilunin_FINAL.md"

# Fallback PDF list when metadata index is empty (bath/sanitary from find)
FALLBACK_BATH_PDFS = [
    IMPORTS_DIR / "11_Project_Case_Studies" / "RMbathroom bath for KSA.pdf",
    IMPORTS_DIR / "01_Quotes_and_Proposals" / "MT2021062301 Bathtub Machinecraft PF1 Thermoforming 1200 2000.pdf",
    IMPORTS_DIR / "01_Quotes_and_Proposals" / "MT2023132 PF1 3030 Machinecraft for Jaguar Revised Offer.pdf",
    IMPORTS_DIR / "01_Quotes_and_Proposals" / "Machinecraft Quote for Thermoforming Machine 2116 PF1 - Mirsant -V07.pdf",
    IMPORTS_DIR / "05_Presentations" / "Presentation for Stas Russia - Bathtubs - Machinecraft.pdf",
]

MAX_EXTRACT_CHARS_PER_FILE = 10_000


async def get_files_to_read(max_pdfs: int) -> list[tuple[Path, str]]:
    """Alexandros-style: hybrid search for bath/sanitary; fallback to known list. Returns [(path, name), ...]."""
    from ira.brain.imports_fallback_retriever import hybrid_search

    query = "bath sanitary ware vacuum forming bathtub PF1 Mirsant Jaguar RMbathroom 1200 2000"
    candidates = await hybrid_search(query, limit=max_pdfs * 2)

    out: list[tuple[Path, str]] = []
    seen_paths: set[str] = set()
    for c in candidates:
        path_str = c.get("path", "")
        if not path_str or path_str in seen_paths:
            continue
        path = Path(path_str)
        if not path.suffix.lower() == ".pdf":
            continue
        if not path.exists():
            continue
        seen_paths.add(path_str)
        out.append((path, c.get("name", path.name)))
        if len(out) >= max_pdfs:
            break

    if not out:
        for path in FALLBACK_BATH_PDFS:
            if path.exists() and len(out) < max_pdfs:
                out.append((path, path.name))
    return out


async def extract_texts(files: list[tuple[Path, str]]) -> list[tuple[str, str]]:
    """Extract text from each file. Returns [(filename, text), ...]."""
    from ira.brain.imports_fallback_retriever import extract_file_text

    results = []
    for path, name in files:
        text = await extract_file_text(path, max_chars=MAX_EXTRACT_CHARS_PER_FILE)
        if text and len(text.strip()) > 100:
            results.append((name, text))
        else:
            print(f"  [skip] {name}: too little text")
    return results


async def extract_insights_with_llm(doc_snippets: list[tuple[str, str]]) -> str:
    """Call LLM to extract cool information from doc snippets."""
    from ira.services.llm_client import get_llm_client

    combined = "\n\n---\n\n".join(
        f"[Document: {name}]\n\n{text}" for name, text in doc_snippets
    )

    system = """You are a sales-support analyst for Machinecraft (thermoforming machinery).
Your task: read document excerpts and extract the most useful facts for a sales email to a sanitary-ware / bathtub vacuum-forming prospect.
Focus on: specs (forming area, draw, cycle time), customer names and projects, process differentiators, and any quotable or impressive details.
Output a concise bullet list. No preamble."""

    user = f"""From these document excerpts, extract the best facts for a sanitary-ware prospect email (Vladimir, 1200×2000 mm inquiry, bathtub/sanitary).

{combined[:28000]}

Bullet list of insights (one line per bullet):"""

    client = get_llm_client()
    return await client.generate_text(
        system=system,
        user=user,
        max_tokens=1500,
        temperature=0.2,
        name="vladimir_email_extract_insights",
    )


async def generate_final_email_with_llm(draft_body: str, insights: str) -> str:
    """Generate final email body + subject using draft, insights, and Rushabh voice + brand guidelines."""
    from ira.services.llm_client import get_llm_client
    from ira.prompt_loader import load_prompt

    voice_brand = load_prompt("email_rushabh_voice_brand")

    system = f"""You are Calliope, Machinecraft's writer. Write the final email for Vladimir Kilunin (Komplektant, kiluninv@gmail.com).
We already sent a generic intro 13 days ago with no reply. This email must be concrete and valuable so he replies.
Use the draft body as the base. Weave in 1–3 concrete details from the EXTRACTED INSIGHTS to make the email more specific and engaging.
Keep: spec summary, indicative budget (EUR 280k–380k), sanitary references (Jaguar PF1-3030, Mirsant PF1-2116, RMbathroom KSA), Netherlands reference, production table, single CTA (15–20 min video call Thu/Fri).
Tone: professional, warm, decisive. No fluff.

Apply Rushabh's voice and Machinecraft brand (packaging rules below). Prefer "Hi Vladimir," for warmth; if the draft uses "Dear Vladimir," you may keep it for this formal re-engagement. Use "I" not "we". Short paragraphs. No corporate buzzwords. One clear CTA at the end. Sign-off: Best regards, Rushabh Doshi, Director — Machinecraft (international/formal).

--- RUSHABH VOICE & BRAND (final email packaging) ---
{voice_brand}
--- END ---

Output format:
Subject: <subject line>
<blank line>
<body>"""

    user = f"""DRAFT BODY (use as base, improve with insights):

{draft_body}

EXTRACTED INSIGHTS (weave in 1–3 concrete details where they fit naturally):

{insights}

Produce the final email: Subject line then body. Follow the Rushabh voice and brand rules above."""

    client = get_llm_client()
    return await client.generate_text(
        system=system,
        user=user,
        max_tokens=2500,
        temperature=0.35,
        name="vladimir_email_final",
    )


def read_draft_body() -> str:
    """Read the engagement draft body (section 2) from the markdown file."""
    text = DRAFT_PATH.read_text()
    # Extract from "**Draft body**" to "Best regards" (inclusive)
    start = text.find("**Draft body**")
    if start == -1:
        start = text.find("Dear Vladimir,")
    if start == -1:
        return text
    end = text.find("Best regards,", start)
    if end != -1:
        end = text.find("\n", end) + 1
    else:
        end = len(text)
    return text[start:end].strip()


async def main(max_pdfs: int = 5) -> None:
    print("1. Asking Alexandros-style search for bath/sanitary files...")
    files = await get_files_to_read(max_pdfs)
    if not files:
        print("No PDFs found. Aborting.")
        return
    for path, name in files:
        print(f"   - {name}")

    print("\n2. Reading and extracting text from PDFs...")
    doc_snippets = await extract_texts(files)
    if not doc_snippets:
        print("No text extracted. Aborting.")
        return
    print(f"   Extracted {len(doc_snippets)} docs, total ~{sum(len(t) for _, t in doc_snippets)} chars.")

    print("\n3. Extracting cool information via LLM...")
    insights = await extract_insights_with_llm(doc_snippets)
    print(insights[:800] + ("..." if len(insights) > 800 else ""))

    print("\n4. Generating final email (draft + insights)...")
    draft_body = read_draft_body()
    final_email = await generate_final_email_with_llm(draft_body, insights)

    FINAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = "# Final email — Vladimir Kilunin (from Alexandros + LLM extraction)\n\n"
    header += "Sources: Alexandros-style search → PDFs read → LLM extract insights → LLM generate final.\n\n---\n\n"
    FINAL_PATH.write_text(header + final_email, encoding="utf-8")
    print(f"\n5. Wrote: {FINAL_PATH}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Vladimir engagement email from imports + LLM")
    parser.add_argument("--max-pdfs", type=int, default=5, help="Max PDFs to read (default 5)")
    args = parser.parse_args()
    asyncio.run(main(max_pdfs=args.max_pdfs))
