#!/usr/bin/env python3
"""Fetch NewsData.io headlines for the Marc/Bermaq reminder email. Run from project root."""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


async def main():
    from openclaw.agents.ira.src.tools.newsdata_client import search_news

    # Queries relevant to Marc: Spain/Europe thermoforming, packaging, plastics manufacturing
    queries = [
        ("thermoforming plastics manufacturing Europe", "es"),
        ("packaging manufacturing Spain", ""),
    ]
    all_lines = []
    for query, country in queries:
        result = await search_news(query=query, country=country or "", max_results=3)
        if result and not result.strip().startswith("("):
            all_lines.append(result.strip())
    if all_lines:
        return "\n\n".join(all_lines)
    return None


if __name__ == "__main__":
    out = asyncio.run(main())
    if out:
        print(out)
    else:
        print("(No news returned — check NEWSDATA_API_KEY or try different query)")
