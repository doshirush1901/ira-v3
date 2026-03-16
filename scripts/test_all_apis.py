#!/usr/bin/env python3
"""One-off connectivity test for all Ira external APIs. Loads .env and pings each service.
Usage: poetry run python scripts/test_all_apis.py
Does not print secrets."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Load .env
repo = Path(__file__).resolve().parents[1]
env_path = repo / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(repo / "src"))
import httpx


async def test_tavily() -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": "test", "max_results": 1},
            )
            r.raise_for_status()
            return "ok"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_serper() -> str:
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://google.serper.dev/search",
                json={"q": "test", "num": 1},
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
            )
            r.raise_for_status()
            return "ok"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_searchapi() -> str:
    key = os.environ.get("SEARCHAPI_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                "https://www.searchapi.io/api/v1/search",
                params={"engine": "google", "q": "test", "num": 1, "api_key": key},
            )
            r.raise_for_status()
            return "ok"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_firecrawl() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={"url": "https://example.com"},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            # 200 or 202 accepted
            if r.status_code in (200, 202):
                return "ok"
            return f"fail (HTTP {r.status_code})"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_unstructured() -> str:
    key = os.environ.get("UNSTRUCTURED_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    url = os.environ.get("UNSTRUCTURED_API_URL", "https://api.unstructuredapp.io/general/v0/general").strip()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            # Minimal request: general endpoint with a tiny payload
            r = await c.post(
                url,
                json={"input": "Hello world"},
                headers={"unstructured-api-key": key, "Content-Type": "application/json"},
            )
            if r.status_code in (200, 201, 422):
                return "ok"
            return f"fail (HTTP {r.status_code})"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_mem0() -> str:
    key = os.environ.get("MEM0_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.mem0.ai/v1/ping/",
                headers={"Authorization": f"Token {key}"},
            )
            if r.status_code < 400:
                return "ok"
            return f"fail (HTTP {r.status_code})"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_newsdata() -> str:
    key = os.environ.get("NEWSDATA_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                "https://newsdata.io/api/1/news",
                params={"apikey": key, "q": "test", "language": "en"},
            )
            if r.status_code == 200:
                return "ok"
            return f"fail (HTTP {r.status_code})"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def test_pdfco() -> str:
    key = os.environ.get("PDFCO_API_KEY", "").strip()
    if not key:
        return "skip (no key)"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.pdf.co/v1/pdf/convert/from/html",
                json={"html": "<p>test</p>", "name": "test.pdf"},
                headers={"x-api-key": key, "Content-Type": "application/json"},
            )
            if r.status_code == 200:
                return "ok"
            return f"fail (HTTP {r.status_code})"
    except Exception as e:
        return f"fail ({str(e)[:50]})"


async def main() -> None:
    tests = [
        ("Tavily (web search)", test_tavily),
        ("Serper (web search)", test_serper),
        ("SearchAPI (web search)", test_searchapi),
        ("Firecrawl (scrape)", test_firecrawl),
        ("Unstructured (doc parse)", test_unstructured),
        ("Mem0 (memory)", test_mem0),
        ("Newsdata (news)", test_newsdata),
        ("PDF.co (PDF)", test_pdfco),
    ]
    results = []
    for name, fn in tests:
        try:
            out = await fn()
        except Exception as e:
            out = f"error ({str(e)[:50]})"
        results.append((name, out))
        print(f"  {name}: {out}")
    print()
    ok = sum(1 for _, v in results if v == "ok")
    skip = sum(1 for _, v in results if v.startswith("skip"))
    fail = sum(1 for _, v in results if v.startswith("fail") or v.startswith("error"))
    print(f"  Summary: ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    asyncio.run(main())
