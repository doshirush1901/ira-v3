#!/usr/bin/env python3
"""
Extract top job candidates from the Recruitment CVs Gmail label.

Fetches threads from the label (with PDF/DOCX attachment text when available),
parses each with an LLM to extract: name, location, what they do (~100 words),
position applied for, suggested role at Machinecraft, and email.

Requires: API server running (restart after pulling to get CV attachment parsing),
and OpenAI/Anthropic configured in .env.

Usage:
  poetry run python scripts/top_candidates_from_recruitment_mailbox.py
  poetry run python scripts/top_candidates_from_recruitment_mailbox.py --max-threads 15 --label "Recruitment CVs"
  poetry run python scripts/top_candidates_from_recruitment_mailbox.py --no-attachments   # body only, no PDF/DOCX
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Pydantic model for LLM extraction
from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    """One candidate parsed from an application email thread."""

    name: str = Field(description="Full name of the applicant")
    location: str = Field(description="City, region or country")
    summary: str = Field(
        description="What they do in about 100 words: experience, skills, current role, education if mentioned"
    )
    position_applied_for: str = Field(
        description="Job title or role they applied to (from subject/body)"
    )
    suggested_role_at_machinecraft: str = Field(
        description="Best-fit role at Machinecraft (e.g. Design Engineer, Plant Manager, CAD Drafter)"
    )
    email: str = Field(description="Applicant email address")


def _extract_email_from_from_field(from_str: str) -> str:
    """Parse email from 'Name <email@domain.com>' or plain email."""
    match = re.search(r"<([^>]+)>", from_str)
    if match:
        return match.group(1).strip().lower()
    return from_str.strip().lower()


async def fetch_emails_via_api(
    base_url: str,
    label: str,
    query: str,
    max_results: int,
    after: str = "",
    before: str = "",
) -> list[dict]:
    """POST /api/email/search; return list of email dicts."""
    import urllib.error
    import urllib.request

    payload = {
        "label": label,
        "query": query,
        "max_results": max_results,
    }
    if after:
        payload["after"] = after
    if before:
        payload["before"] = before
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/email/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data.get("emails", [])


def fetch_thread_via_api(base_url: str, thread_id: str) -> list[dict]:
    """GET /api/email/thread/{thread_id}; return list of message dicts."""
    import urllib.request

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/email/thread/{thread_id}",
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data.get("messages", [])


def fetch_thread_with_attachments_via_api(
    base_url: str,
    thread_id: str,
    max_attachment_chars: int = 50000,
) -> list[dict]:
    """GET /api/email/thread/{thread_id}/with-attachments; returns messages with attachment_texts (CV/resume text).
    Falls back to regular thread (no attachment text) if endpoint returns 404 (e.g. server not restarted)."""
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/email/thread/{thread_id}/with-attachments?max_attachment_chars={max_attachment_chars}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return data.get("messages", [])
    except urllib.error.HTTPError as e:
        if e.code in (404, 503):
            # 404: server may not have the new route; 503: Gmail/attachment error — fall back to thread without attachments
            with urllib.request.urlopen(
                f"{base_url.rstrip('/')}/api/email/thread/{thread_id}", timeout=30
            ) as r2:
                data = json.loads(r2.read().decode())
            return data.get("messages", [])
        raise


def build_thread_text(
    messages: list[dict],
    *,
    include_attachment_texts: bool = False,
) -> str:
    """Build a single text blob for LLM from thread messages (from, subject, body, optional attachment text)."""
    parts = []
    for m in messages:
        from_addr = m.get("from", "")
        subject = m.get("subject", "")
        body = (m.get("body") or "")[:6000]
        block = f"From: {from_addr}\nSubject: {subject}\n\n{body}"
        if include_attachment_texts and m.get("attachment_texts"):
            for i, att_text in enumerate(m["attachment_texts"], 1):
                block += f"\n\n[Attachment {i} (e.g. CV/Resume)]\n{att_text[:12000]}"
        parts.append(block)
    return "\n\n---\n\n".join(parts)


def is_likely_applicant_message(from_str: str, to_str: str) -> bool:
    """True if message is from external applicant (not machinecraft sending out)."""
    from_lower = from_str.lower()
    if "machinecraft" in from_lower and "@machinecraft.org" in from_lower:
        return False
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract top candidates from Recruitment CVs mailbox via LLM."
    )
    parser.add_argument(
        "--label",
        default="Recruitment CVs",
        help="Gmail label name (default: Recruitment CVs)",
    )
    parser.add_argument(
        "--query",
        default="has:attachment",
        help="Gmail query to narrow (default: has:attachment for CVs)",
    )
    parser.add_argument(
        "--max-threads",
        type=int,
        default=12,
        help="Max threads to process with LLM (default 12)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=30,
        help="Max emails from search (default 30)",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("IRA_API_BASE_URL", "http://localhost:8000"),
        help="API base URL",
    )
    parser.add_argument("--after", default="", help="Only emails after YYYY/MM/DD")
    parser.add_argument("--before", default="", help="Only emails before YYYY/MM/DD")
    parser.add_argument(
        "--no-attachments",
        action="store_true",
        help="Do not fetch or parse PDF/DOCX attachments (faster, but no CV text).",
    )
    args = parser.parse_args()
    args.with_attachments = not args.no_attachments

    # 1) Search emails
    try:
        emails = await fetch_emails_via_api(
            args.base_url,
            args.label,
            args.query,
            args.max_results,
            after=args.after,
            before=args.before,
        )
    except OSError as e:
        print(
            f"Cannot reach API at {args.base_url}. Start server first.\nError: {e}",
            file=sys.stderr,
        )
        return 1

    if not emails:
        print(f"No emails found in label '{args.label}' with query '{args.query}'.")
        return 0

    # 2) Dedupe by thread_id and take first N threads
    seen_threads: set[str] = set()
    thread_ids: list[str] = []
    for e in emails:
        tid = e.get("thread_id")
        if tid and tid not in seen_threads:
            seen_threads.add(tid)
            thread_ids.append(tid)
            if len(thread_ids) >= args.max_threads:
                break

    # 3) Load LLM client
    from ira.config import get_settings
    from ira.services.llm_client import LLMClient

    settings = get_settings()
    llm = LLMClient(settings)

    system = """You are extracting job applicant or relevant contact profiles from email threads in Machinecraft's Recruitment CVs folder.
Prefer threads that are JOB APPLICATIONS (someone applying for a job / sending CV or resume). If the thread is clearly not a person applying for a job (e.g. Naukri sales, vendor logistics, LinkedIn alert), set name to exactly "SKIP".
From each thread that looks like an application or recruitment-related contact, extract: full name, location, what they do in ~100 words (experience, skills, role, education),
the position they applied for (or "Not stated"), a suggested role at Machinecraft (Design Engineer, Plant Manager, CAD Drafter, PLC Programmer, etc.), and their email.
Use only information present in the thread. If something is missing, say "Not stated" or infer briefly from context.
Machinecraft roles: Design Engineer, CAD Drafter, Plant Manager, Production, Procurement, PLC Programmer, Mechanical Engineer, Quality."""

    candidates: list[CandidateProfile] = []

    use_attachments = getattr(args, "with_attachments", True)

    for i, thread_id in enumerate(thread_ids):
        try:
            if use_attachments:
                messages = fetch_thread_with_attachments_via_api(
                    args.base_url, thread_id, max_attachment_chars=40000
                )
            else:
                messages = fetch_thread_via_api(args.base_url, thread_id)
        except Exception as e:
            print(f"  Thread {thread_id}: fetch failed — {e}", file=sys.stderr)
            continue

        if not messages:
            continue

        # Prefer first message from external sender (applicant)
        applicant_msgs = [
            m
            for m in messages
            if is_likely_applicant_message(m.get("from", ""), m.get("to", ""))
        ]
        if not applicant_msgs:
            applicant_msgs = messages

        thread_text = build_thread_text(
            applicant_msgs[:3],
            include_attachment_texts=use_attachments,
        )

        if len(thread_text.strip()) < 50:
            continue

        try:
            profile = await llm.generate_structured(
                system=system,
                user=thread_text,
                response_model=CandidateProfile,
                max_tokens=600,
                name="recruitment_candidate_extract",
            )
            if profile.name and profile.name.strip().upper() != "SKIP":
                if profile.name.lower().startswith("not stated"):
                    continue
                candidates.append(profile)
        except Exception as e:
            print(f"  Thread {thread_id}: LLM failed — {e}", file=sys.stderr)

    # 4) Output
    if not candidates:
        print("No candidate profiles extracted.")
        return 0

    print(f"# Top candidates from {args.label} (parsed via LLM)\n")
    print(f"*{len(candidates)} candidates from {len(thread_ids)} threads.*\n")

    # Compact table
    print("| # | Name | Location | Position applied | Suggested role | Email |")
    print("|---|------|----------|------------------|----------------|-------|")
    for i, c in enumerate(candidates, 1):
        loc = (c.location or "")[:25] + ("..." if len(c.location or "") > 25 else "")
        pos = (c.position_applied_for or "")[:22] + ("..." if len(c.position_applied_for or "") > 22 else "")
        role = (c.suggested_role_at_machinecraft or "")[:20] + ("..." if len(c.suggested_role_at_machinecraft or "") > 20 else "")
        print(f"| {i} | {c.name} | {loc} | {pos} | {role} | {c.email} |")
    print()

    for i, c in enumerate(candidates, 1):
        print(f"## {i}. {c.name}")
        print(f"- **Email:** {c.email}")
        print(f"- **Location:** {c.location}")
        print(f"- **Position applied for:** {c.position_applied_for}")
        print(f"- **Suggested role at Machinecraft:** {c.suggested_role_at_machinecraft}")
        print(f"- **Summary:** {c.summary}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
