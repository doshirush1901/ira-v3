#!/usr/bin/env python3
"""Pull all threads with a contact from your mailbox, build an interaction logic tree, and optionally store in memory.

**Always run this first** before drafting any email to a CRM/lead. It:
1. Searches your Gmail for every email to/from the contact
2. Builds an interaction logic tree: timeline, proposals sent, their feedback
3. Optionally --summarize: parses tech spec and proposal data via LLM and generates a client-facing recap (so when you email after a long time, they see what they asked and what we offered)
4. Writes the full context to a markdown file
5. With --store-memory: stores a condensed contact context in long-term memory so agents can recall when drafting

Usage:
  poetry run python scripts/pull_contact_email_history.py --email pinto@forma3d.pt --output data/imports/24_WebSite_Leads/eduardo_forma3d_email_history.md
  poetry run python scripts/pull_contact_email_history.py --email pinto@forma3d.pt --store-memory --summarize --name "Eduardo Pinto"

Requires: Ira API running for Gmail. MEM0_API_KEY for --store-memory. OpenAI/Anthropic for --summarize.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

BASE = "http://localhost:8000"
OUTPUT_DIR = PROJECT_ROOT / "data/imports/24_WebSite_Leads"


def search_emails(email: str, max_results: int = 50) -> list[dict]:
    """Search your mailbox (Gmail): to this address + from this address, then merge by thread."""
    all_emails = []
    seen_ids = set()
    for param, value in [("to_address", email), ("from_address", email)]:
        try:
            r = httpx.post(
                f"{BASE}/api/email/search",
                json={param: value, "max_results": max_results},
                timeout=30.0,
            )
            r.raise_for_status()
            for e in r.json().get("emails", []):
                if e.get("id") and e["id"] not in seen_ids:
                    seen_ids.add(e["id"])
                    all_emails.append(e)
        except Exception:
            continue
    return all_emails


def get_thread(thread_id: str) -> list[dict]:
    """Fetch full thread by ID."""
    r = httpx.get(f"{BASE}/api/email/thread/{thread_id}", timeout=15.0)
    r.raise_for_status()
    data = r.json()
    return data.get("messages", [])


def extract_date(msg: dict) -> datetime | None:
    s = msg.get("date") or msg.get("received_at")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def is_from_us(to_address: str, our_domains: tuple = ("machinecraft.org", "machinecraft.in")) -> bool:
    if not to_address:
        return False
    return any(d in (to_address or "").lower() for d in our_domains)


def _build_conversation_text(threads_detail: list[dict], contact_email: str, max_chars: int = 14000) -> str:
    """Build a single text block of all messages for LLM consumption."""
    parts = []
    for t in threads_detail:
        msgs = t.get("messages") or []
        if not msgs:
            continue
        subj = (msgs[0].get("subject") or "(no subject)")
        for m in sorted(msgs, key=lambda x: extract_date(x) or datetime.min):
            d = extract_date(m)
            dt = d.strftime("%Y-%m-%d %H:%M") if d else "?"
            fr = m.get("from", "")
            body = (m.get("body") or "").strip()[:600]
            from_them = contact_email.lower() in (fr or "").lower()
            role = "THEM" if from_them else "US"
            parts.append(f"[{dt}] {role}: {body}")
        parts.append("---")
    text = "\n".join(parts)
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


async def _llm_summarize(threads_detail: list[dict], contact_email: str, contact_name: str) -> tuple[str, str]:
    """Use LLM to extract tech spec + proposal data and generate a client-facing recap."""
    try:
        from ira.services.llm_client import get_llm_client
    except Exception:
        return "(LLM not available)", "(LLM not available)"
    conv_text = _build_conversation_text(threads_detail, contact_email)
    if not conv_text.strip():
        return "(no conversation text)", "(no conversation text)"
    system = """You are summarizing past email threads between Machinecraft (thermoforming machinery) and a contact.
From the conversation log, extract:
1) **What they asked for:** forming area, materials, application (e.g. pallets, automotive), thickness, any specific requirements.
2) **What we offered:** machine model(s), indicative price or range, lead time, key terms (EXW, etc.), attachments or quotes mentioned.
Output two blocks exactly as below — no extra commentary.

Block A — Parsed tech spec & proposal data (use bullet points):
- Their ask: ...
- Our offer: ...

Block B — Recap for email (2–4 sentences, client-facing): A short paragraph we can paste into an email after a long gap, so the client sees what they had asked and what we had proposed. Example: "When we last spoke you were looking for [X]. We had proposed [machine/specs], with [price], [lead time]. If you would like to pick this up, we can …" Keep it warm and factual."""
    user = f"Contact: {contact_name or contact_email}\n\nConversation log:\n{conv_text}"
    llm = get_llm_client()
    raw = await llm.generate_text(system=system, user=user, max_tokens=1024)
    if not raw or not raw.strip():
        return "(no response)", "(no response)"
    # Split into Block A and Block B if possible
    block_a = []
    block_b = []
    in_b = False
    for line in raw.split("\n"):
        if "Block B" in line or "Recap for email" in line:
            in_b = True
            continue
        if "Block A" in line or "Parsed tech spec" in line:
            continue
        if in_b:
            block_b.append(line)
        else:
            block_a.append(line)
    parsed = "\n".join(block_a).strip() or raw[:1500]
    recap = "\n".join(block_b).strip() or raw[-1500:] if len(raw) > 1500 else raw
    return parsed, recap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="Contact email")
    parser.add_argument("--output", type=Path, help="Output markdown path")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--store-memory", action="store_true", help="Store condensed contact context in long-term memory (Mem0)")
    parser.add_argument("--name", type=str, help="Contact name for memory (e.g. Eduardo Pinto)")
    parser.add_argument("--summarize", action="store_true", help="Use LLM to parse tech spec & proposal data and generate a client-facing recap for email after a long gap")
    args = parser.parse_args()

    email = args.email.strip().lower()
    output_path = args.output or OUTPUT_DIR / "contact_email_history.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        emails = search_emails(email, max_results=args.max_results)
    except httpx.HTTPStatusError as e:
        print(f"Search failed: {e.response.status_code} {e.response.text}", flush=True)
        raise SystemExit(1)
    except httpx.ConnectError:
        print("Cannot connect to Ira API. Start the server (see .cursor/rules/ira-api.mdc).", flush=True)
        raise SystemExit(1)

    # Unique thread IDs, preserve order
    thread_ids = []
    seen = set()
    for e in emails:
        tid = e.get("thread_id")
        if tid and tid not in seen:
            seen.add(tid)
            thread_ids.append(tid)

    threads_detail: list[dict] = []
    for tid in thread_ids:
        try:
            messages = get_thread(tid)
            if messages:
                threads_detail.append({"thread_id": tid, "messages": messages})
        except Exception as ex:
            threads_detail.append({"thread_id": tid, "error": str(ex), "messages": []})

    # Sort threads by earliest message in thread (use timestamp to avoid naive/aware comparison)
    def thread_date(t: dict) -> float:
        msgs = t.get("messages") or []
        dates = [extract_date(m) for m in msgs if extract_date(m)]
        if not dates:
            return 0.0
        d = min(dates)
        return d.timestamp() if d.tzinfo else d.replace(tzinfo=timezone.utc).timestamp()

    threads_detail.sort(key=thread_date)

    # Build summary
    lines = [
        f"# Email history: {email}",
        "",
        f"*Generated by `scripts/pull_contact_email_history.py`. Pulls all Gmail threads involving this address.*",
        "",
        f"**Total threads found:** {len(threads_detail)}",
        "",
        "---",
        "",
        "## Summary for agent",
        "",
    ]

    proposal_keywords = re.compile(
        r"\b(quote|proposal|offer|quotation|specification|specs?|pricing|price|budget|delivery|lead time|PF1|machine)\b",
        re.I,
    )

    # --- Build interaction logic tree ---
    tree_interactions: list[dict] = []
    proposals_sent: list[dict] = []
    their_feedback: list[str] = []

    for t in threads_detail:
        msgs = t.get("messages") or []
        if not msgs:
            continue
        first = msgs[0]
        subj = first.get("subject", "(no subject)")
        has_proposal = any(proposal_keywords.search(m.get("body") or m.get("subject") or "") for m in msgs)
        thread_dates = [extract_date(m) for m in msgs if extract_date(m)]
        date_str = min(thread_dates).strftime("%Y-%m-%d") if thread_dates else "?"
        if has_proposal:
            proposals_sent.append({"date": date_str, "subject": subj})
        # Order messages in thread by date
        for m in sorted(msgs, key=lambda x: extract_date(x) or datetime.min):
            d = extract_date(m)
            dt = d.strftime("%Y-%m-%d") if d else "?"
            fr = (m.get("from") or "").lower()
            body = (m.get("body") or "").strip()
            from_them = email in fr
            direction = "Them → Us" if from_them else "Us → Them"
            tree_interactions.append({
                "date": dt,
                "direction": direction,
                "subject": subj,
                "proposal": "Y" if (has_proposal and not from_them) else ("Y (in thread)" if has_proposal else "N"),
                "feedback": body[:150] + "…" if from_them and body else "",
            })
            if from_them and body:
                their_feedback.append(f"[{dt}] {body[:200]}{'…' if len(body) > 200 else ''}")

    # Write logic tree section (after Summary for agent, before thread details)
    lines.append("## Interaction logic tree (use this before drafting)")
    lines.append("")
    lines.append("Chronological view of all interactions, proposals we sent, and their feedback.")
    lines.append("")
    lines.append("### Timeline")
    lines.append("")
    for ix in tree_interactions:
        fb = f" | Feedback: {ix['feedback']}" if ix.get("feedback") else ""
        lines.append(f"- **{ix['date']}** | {ix['direction']} | {ix['subject'][:50]} | Proposal: {ix['proposal']}{fb}")
    lines.append("")
    lines.append("### Proposals we sent")
    lines.append("")
    if proposals_sent:
        for p in proposals_sent:
            lines.append(f"- **{p['date']}**: {p['subject']}")
    else:
        lines.append("- (none detected in threads)")
    lines.append("")
    lines.append("### Their feedback (snippets)")
    lines.append("")
    if their_feedback:
        for s in their_feedback[:15]:
            lines.append(f"- {s}")
    else:
        lines.append("- (no replies captured)")
    lines.append("")
    lines.append("---")
    lines.append("")

    for t in threads_detail:
        msgs = t.get("messages") or []
        if not msgs:
            continue
        first = msgs[0]
        subj = first.get("subject", "(no subject)")
        dates = [extract_date(m) for m in msgs if extract_date(m)]
        date_str = min(dates).strftime("%Y-%m-%d") if dates else "?"
        # Who sent what
        outbound = []
        inbound = []
        for m in msgs:
            d = extract_date(m)
            dt = d.strftime("%Y-%m-%d %H:%M") if d else "?"
            fr = (m.get("from") or "").lower()
            to = (m.get("to") or "").lower()
            body = (m.get("body") or "")[:500]
            if email in fr:
                inbound.append(f"  - **{dt}** (from them): {body[:200]}…")
            else:
                outbound.append(f"  - **{dt}** (from us): {body[:200]}…")
        has_proposal = any(proposal_keywords.search(m.get("body") or m.get("subject") or "") for m in msgs)

        lines.append(f"### Thread: {subj}")
        lines.append(f"- **Date:** {date_str} | **Messages:** {len(msgs)}")
        if has_proposal:
            lines.append("- **Contains:** quote/proposal/specs or pricing mention")
        lines.append("")
        if outbound:
            lines.append("**From us:**")
            lines.extend(outbound[:5])
            lines.append("")
        if inbound:
            lines.append("**From them:**")
            lines.extend(inbound[:5])
            lines.append("")
        lines.append("---")
        lines.append("")

    # One-line timeline
    lines.append("## Timeline (threads)")
    lines.append("")
    for t in threads_detail:
        msgs = t.get("messages") or []
        if not msgs:
            continue
        dates = [extract_date(m) for m in msgs if extract_date(m)]
        date_str = min(dates).strftime("%Y-%m-%d") if dates else "?"
        subj = (msgs[0].get("subject") or "(no subject)")[:60]
        lines.append(f"- {date_str}: {subj}")
    lines.append("")

    # LLM: parse tech spec + proposal and generate client-facing recap (for email after a long time)
    if getattr(args, "summarize", False) and threads_detail:
        try:
            name = getattr(args, "name", None) or email.split("@")[0]
            parsed, recap = asyncio.run(_llm_summarize(threads_detail, email, name))
            lines.append("## Parsed tech spec & proposal data")
            lines.append("")
            lines.append(parsed)
            lines.append("")
            lines.append("## Recap summary (for email — use when emailing after a long time)")
            lines.append("")
            lines.append("Short client-facing recap so they know what they asked and what we offered:")
            lines.append("")
            lines.append(recap)
            lines.append("")
            print("LLM summary: parsed tech spec & proposal + recap for email.", flush=True)
        except Exception as e:
            lines.append("## Parsed tech spec & proposal data")
            lines.append("")
            lines.append(f"(LLM summarize failed: {e})")
            lines.append("")
            print(f"LLM summarize failed: {e}", flush=True)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(threads_detail)} threads + logic tree to {output_path}")

    # Store in long-term memory so agents recall when drafting
    if getattr(args, "store_memory", False):
        try:
            from ira.memory.long_term import LongTermMemory
            mem = LongTermMemory()
            if not getattr(mem, "_api_key", None) or not mem._api_key:
                print("MEM0_API_KEY not set; skip --store-memory.", flush=True)
            else:
                name = getattr(args, "name", None) or email.split("@")[0]
                proposals_str = "; ".join(f"{p['date']} {p['subject'][:40]}" for p in proposals_sent[:5]) if proposals_sent else "none"
                feedback_str = " ".join(their_feedback[:3])[:300] if their_feedback else "no reply snippets"
                fact = (
                    f"Contact {name} ({email}): {len(threads_detail)} threads, {len(proposals_sent)} proposal(s) sent ({proposals_str}). "
                    f"Their feedback: {feedback_str}. "
                    f"When drafting: use full context from interaction logic tree; do not repeat proposals or specs already sent."
                )
                mem.store_fact(fact, source=f"contact_history:{email}", confidence=0.9)
                print("Stored contact context in long-term memory.", flush=True)
        except Exception as e:
            print(f"Store memory failed: {e}", flush=True)


if __name__ == "__main__":
    main()
