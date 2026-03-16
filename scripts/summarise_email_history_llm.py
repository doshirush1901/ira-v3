#!/usr/bin/env python3
"""Summarise email history with an LLM: timeline, every machine/offer we made (specs + price), their feedback.

Uses the project's LLMClient (OpenAI/Anthropic from .env). Output is markdown.

Usage:
  poetry run python scripts/summarise_email_history_llm.py
  poetry run python scripts/summarise_email_history_llm.py --input data/reports/reto_bamert_plastikabalumag_history.md --output data/knowledge/plastikabalumag_llm_summary.md
"""

from __future__ import annotations

import argparse
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


SYSTEM_PROMPT = """You are summarizing email history between Machinecraft (thermoforming machine manufacturer) and a contact/company. Your task is to produce a clear, factual summary in markdown.

**Important:** Search the *full* email text (including thread bodies and "From us"/"From them" snippets) for any: dimensions (e.g. 724 x 924 mm, 2x3 m), forming area, heater type (quartz, ceramic, Heatronik), control (individual radiator, SSR), price (EUR, CHF, USD, INR), budget, concept price, or feature names. Include every one you find.

Extract and structure the following:

1. **Timeline** — Chronological list of main conversation milestones (dates, who wrote, main topic: meeting request, offer sent, feedback, etc.).

2. **Every machine or offer we (Machinecraft) made** — For each offer:
   - Product/machine name (e.g. Berg-type, PF1, SPM for EVA, 2×3 m machine).
   - Specs: forming area (mm or m), dimensions, features (heaters, control, loading, etc.), options — extract from thread content.
   - Price and currency when mentioned (e.g. EUR, CHF, USD, INR, "budget price", "concept price").
   - Date or thread reference.
   - Context (e.g. display at expo, for new building).

3. **Their response/feedback** — For each offer, what they said: interested, not now, pole position, waiting for building, price question, etc.

4. **Inquiries or requests from them** — Any time they asked for a quote, specs, or machine (extract what they asked for and any specs/price they mentioned).

Be concise but complete. If price or a spec truly is not in the text, say "not stated". Use bullet lists and short paragraphs. Output only the markdown summary, no preamble."""


async def run_summary(history_path: Path, output_path: Path) -> None:
    from ira.services.llm_client import get_llm_client

    raw = history_path.read_text(encoding="utf-8", errors="replace")
    # Trim if extremely long (keep under ~90k chars for context headroom)
    max_chars = 90_000
    if len(raw) > max_chars:
        raw = raw[:max_chars] + "\n\n[... truncated for length ...]"

    client = get_llm_client()
    summary = await client.generate_text(
        SYSTEM_PROMPT,
        raw,
        temperature=0.2,
        max_tokens=8192,
        name="summarise_email_history",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary.strip(), encoding="utf-8")
    print(f"Wrote: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise email history via LLM (timeline, offers with specs/price, feedback).")
    parser.add_argument("--input", "-i", type=Path, default=PROJECT_ROOT / "data" / "reports" / "reto_bamert_plastikabalumag_history.md", help="Input markdown (full email history).")
    parser.add_argument("--output", "-o", type=Path, default=PROJECT_ROOT / "data" / "knowledge" / "plastikabalumag_llm_summary.md", help="Output markdown summary.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_summary(args.input, args.output))


if __name__ == "__main__":
    main()
