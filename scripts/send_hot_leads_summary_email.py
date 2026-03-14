#!/usr/bin/env python3
"""Draft hot-leads summary email via LLM and send to rushabh@ with CC to deepak@, manan@, rajesh@machinecraft.org.

Drafts via Ira API (POST /api/query) or, if API fails, in-process LLM. Sends via POST /api/email/send.
Run with Ira API up for send; for draft-only, only LLM env (OpenAI/Anthropic) is needed.

Usage:
  poetry run python scripts/send_hot_leads_summary_email.py           # draft + send
  poetry run python scripts/send_hot_leads_summary_email.py --dry-run  # draft only, print to stderr
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Install httpx: poetry add httpx", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env for in-process LLM fallback
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

CONTEXT_PATH = PROJECT_ROOT / "data/imports/24_WebSite_Leads/hot_leads_context_for_llm_draft.md"
API_URL = os.environ.get("IRA_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SECRET_KEY", "")

TO = "rushabh@machinecraft.org"
CC = "deepak@machinecraft.org, manan@machinecraft.org, rajesh@machinecraft.org"


def load_context() -> str:
    if not CONTEXT_PATH.exists():
        raise FileNotFoundError(f"Context file not found: {CONTEXT_PATH}")
    return CONTEXT_PATH.read_text()


def build_prompt(context: str) -> str:
    return f"""You are drafting a short, professional internal email for Machinecraft sales leadership.

**To:** {TO}
**CC:** {CC}

**Context (use this to write the email body):**
{context}

**Instructions:**
- Write one brief paragraph of intro (e.g. "Hot leads summary as of today — specs, quoted price, what we're waiting on, and how long we've been in touch.").
- Then list each lead (HOT first, then FROZEN) with: company/contact, machine specs summary, price we quoted (if known), what we're waiting on, since when we're talking.
- Keep each lead to 2–4 lines. Be factual; if price or "since when" is unknown, say "check quote" or "see email history".
- End with a single line on re-engage (e.g. "Re-engage: hot = clear CTA every 1–2 weeks; frozen = gentle check-in every 4–6 weeks.").
- Plain text only, no markdown. Sign off as appropriate for an internal update (e.g. "— Ira" or no sign-off).

**Output format (use exactly this so the script can parse it):**
SUBJECT: <one line subject, e.g. Hot leads summary — specs, quotes, status>

BODY:
<plain text email body, no markdown>"""


def parse_llm_response(response_text: str) -> tuple[str, str]:
    """Extract SUBJECT and BODY from LLM response. Handles markdown code blocks."""
    text = response_text.strip()
    # Remove markdown code block if present
    if "```" in text:
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    subject = ""
    body = ""
    if "SUBJECT:" in text:
        subj_match = re.search(r"SUBJECT:\s*(.+?)(?=\n\nBODY:|\nBODY:|\Z)", text, re.DOTALL)
        if subj_match:
            subject = subj_match.group(1).strip().split("\n")[0].strip()
    if "BODY:" in text:
        body_match = re.search(r"BODY:\s*(.+)", text, re.DOTALL)
        if body_match:
            body = body_match.group(1).strip()
    if not subject:
        subject = "Hot leads summary — specs, quotes, status"
    if not body:
        body = text  # fallback: use full response as body
    return subject, body


async def draft_via_llm_client(prompt: str) -> str:
    """Use Ira LLMClient in-process (no API)."""
    from ira.services.llm_client import get_llm_client

    client = get_llm_client()
    return await client.generate_text_with_fallback(
        system="You are a concise internal email drafter. Output only the requested SUBJECT and BODY in the exact format requested.",
        user=prompt,
        max_tokens=2048,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft and send hot leads summary email via LLM")
    parser.add_argument("--dry-run", action="store_true", help="Only draft; print to stderr, do not send")
    args = parser.parse_args()

    context = load_context()
    prompt = build_prompt(context)

    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    # 1) Draft via Ira API or in-process LLM
    response_text = ""
    print("Drafting email (trying Ira API)...", file=sys.stderr)
    try:
        r = httpx.post(
            f"{API_URL}/api/query",
            json={"query": prompt, "user_id": "hot_leads_script"},
            headers=headers,
            timeout=25.0,
        )
        r.raise_for_status()
        data = r.json()
        response_text = data.get("response", "")
    except Exception as e:
        print(f"API draft failed ({e}), using in-process LLM...", file=sys.stderr)
        try:
            response_text = asyncio.run(draft_via_llm_client(prompt))
        except Exception as e2:
            print(f"LLM draft failed: {e2}", file=sys.stderr)
            return 1

    if not response_text:
        print("Empty response from draft.", file=sys.stderr)
        return 1

    subject, body = parse_llm_response(response_text)
    print("Subject:", subject, file=sys.stderr)
    print("Body length:", len(body), "chars", file=sys.stderr)
    print("\n--- BODY ---\n", file=sys.stderr)
    print(body, file=sys.stderr)
    print("\n--- END BODY ---", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY-RUN] Not sending. Remove --dry-run to send.", file=sys.stderr)
        return 0

    # 2) Send
    print("\nSending email...", file=sys.stderr)
    try:
        send_r = httpx.post(
            f"{API_URL}/api/email/send",
            json={
                "to": TO,
                "subject": subject,
                "body": body,
                "cc": CC,
            },
            headers=headers,
            timeout=30.0,
        )
        send_r.raise_for_status()
        result = send_r.json()
        print("Sent:", result.get("message_id", "ok"), file=sys.stderr)
    except httpx.HTTPError as e:
        print(f"Send failed: {e}", file=sys.stderr)
        if hasattr(e, "response") and e.response is not None:
            print(e.response.text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
