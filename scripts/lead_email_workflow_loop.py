#!/usr/bin/env python3
"""Run the full lead email workflow for the next N leads: design → score → redo/improve until ≥9 → send.

Follows outgoing_marketing_email_workflow.md §2a: context → research → draft → score gate → pre-send → send & log.

Usage:
  poetry run python scripts/lead_email_workflow_loop.py --next 1 --send     # one email at a time (recommended)
  poetry run python scripts/lead_email_workflow_loop.py --next 5 --after 49 --dry-run
  poetry run python scripts/lead_email_workflow_loop.py --next 5 --send

--dry-run: draft and score only; do not send. Use to review drafts and scores.
--send: actually send emails once score ≥ 9 (default is dry-run for safety).

Slow step: drafting (POST /api/email/draft) runs Calliope and can take 1–3 min per lead. Use --next 1 to send one email at a time and avoid long runs.

Requires: Ira API running. OpenAI/Anthropic for scoring. Gmail for send.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
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
LEADS_DIR = PROJECT_ROOT / "data/imports/24_WebSite_Leads"
ENRICHED_LEADS_PATH = LEADS_DIR / "ira-drip-campaign/data/enriched_leads.json"
BLACKLIST_PATH = LEADS_DIR / "lead_blacklist.json"

# Lead IDs already sent (from lead_email_workflow_scores.md)
SENT_LEAD_IDS = {38, 39, 40, 41, 42, 43, 45, 46, 48, 49}


def load_blacklist() -> tuple[set[int], set[str]]:
    """Return (blacklisted_lead_ids, blacklisted_emails) from lead_blacklist.json."""
    ids, emails = set(), set()
    if not BLACKLIST_PATH.exists():
        return (ids, emails)
    try:
        data = json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            if e.get("lead_id") is not None:
                ids.add(int(e["lead_id"]))
            if e.get("email"):
                emails.add((e.get("email") or "").strip().lower())
        return (ids, emails)
    except Exception:
        return (ids, emails)

# Scoring rubric (10 points) — matches lead_email_workflow_scores.md
SCORING_RUBRIC = """
Score this lead email draft from 0 to 10 using these criteria (subtract points when missing):
1. Contact history / logic tree used in draft (1 pt)
2. Machine match — what they asked + what we offer, PF1-C/PF1-X, size (1 pt)
3. Small talk + industry talk + at least one curious question (1 pt)
4. Geopolitics / raw materials / India resin when relevant (0.5 pt)
5. Tooling or Industry 4.0 / govt perks — at least one ask (0.5 pt)
6. Our latest builds / one concrete region reference (1 pt)
7. Reference past convos or quotes — one line of context (1 pt)
8. Tech specs + prices, currency by region (1.5 pt)
9. Case study by industry+size + funny last line / joke (1 pt)
10. CTA web call next week + Rushabh sign-off (1 pt)

Respond with JSON only: {"score": <number 0-10>, "missing": ["brief item 1", "brief item 2"], "reason": "one sentence"}.
"""


def load_leads() -> list[dict]:
    if not ENRICHED_LEADS_PATH.exists():
        return []
    return json.loads(ENRICHED_LEADS_PATH.read_text(encoding="utf-8"))


def get_next_lead_ids(leads: list[dict], after: int, count: int) -> list[int]:
    """Return the next `count` lead IDs after `after` that are not sent and not blacklisted."""
    blacklisted_ids, blacklisted_emails = load_blacklist()
    ids = []
    for L in leads:
        lid = L.get("id")
        if lid is None or lid <= after or lid in SENT_LEAD_IDS:
            continue
        if lid in blacklisted_ids:
            continue
        if (L.get("email") or "").strip().lower() in blacklisted_emails:
            continue
        ids.append(lid)
    ids = sorted(ids)[:count]
    return ids


def get_lead(leads: list[dict], lead_id: int) -> dict | None:
    for L in leads:
        if L.get("id") == lead_id:
            return L
    return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "lead"


def run_pull_contact_history(email: str, name: str | None, out_path: Path) -> bool:
    """Run pull_contact_email_history.py; return True if output was written."""
    script = PROJECT_ROOT / "scripts/pull_contact_email_history.py"
    cmd = [
        sys.executable,
        str(script),
        "--email", email,
        "--output", str(out_path),
        "--store-memory",
    ]
    if name:
        cmd.extend(["--name", name])
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  [pull_contact_history] stderr: {result.stderr}", file=sys.stderr)
        return False
    return out_path.exists()


def recall_memory(contact_email: str, limit: int = 5) -> list[str]:
    try:
        r = httpx.get(
            f"{BASE}/api/memory/recall",
            params={"query": f"contact {contact_email} past interactions", "user_id": contact_email, "limit": limit},
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json().get("memories", [])
    except Exception:
        return []


def build_context(
    contact_email: str,
    contact_name: str | None,
    history_path: Path | None,
    memories: list[str],
    extra_instruction: str | None = None,
) -> str:
    parts = [
        "You are drafting a single outbound lead email. Apply: (1) Rushabh voice (prompts/email_rushabh_voice_brand.txt), (2) Structure from prompts/email_final_format_style.txt. Include: opening hook, context/recap, key data (specs; price and lead time only if from playbook/quote/Plutus), one CTA (web call next week), Rushabh sign-off. Follow full agentic workflow: machine match, small talk, curious questions, geopolitics/tooling when relevant, one concrete reference, past convos. **Never invent price or lead time**—only use figures from sales_playbook, a past quote to this contact, or Plutus; if no source, say 'Happy to send a formal quote once we lock the spec' or omit. Case study + closing joke.",
        "",
        "Recipient: " + contact_email,
    ]
    if contact_name:
        parts.append(f"Contact name: {contact_name}")
    parts.append("")
    if memories:
        parts.append("--- RECALLED MEMORIES ---")
        for m in memories:
            parts.append(f"- {m}")
        parts.append("")
    if history_path and history_path.exists():
        parts.append("--- CONTACT HISTORY (logic tree + recap) ---")
        parts.append(history_path.read_text(encoding="utf-8")[:15000])
        parts.append("")
    parts.append("Produce the email body only (no Subject: line in body).")
    if extra_instruction:
        parts.append("")
        parts.append("--- EXTRA ---")
        parts.append(extra_instruction)
    return "\n".join(parts)


def draft_email(lead: dict, history_path: Path | None, extra_instruction: str | None = None) -> tuple[str, str] | None:
    """Return (subject, body) or None on failure."""
    email = (lead.get("email") or "").strip()
    name = (lead.get("client_name") or lead.get("company_name") or "").strip() or None
    if not email:
        return None
    memories = recall_memory(email)
    context = build_context(email, name, history_path, memories, extra_instruction=extra_instruction)
    try:
        r = httpx.post(
            f"{BASE}/api/email/draft",
            json={"to": email, "subject": f"{lead.get('company_name', 'Inquiry')} — catching up", "context": context, "tone": "professional"},
            timeout=300.0,
        )
        r.raise_for_status()
        out = r.json()
        body = out.get("body", "")
        subject = out.get("subject", "")
        return (subject, body)
    except Exception as e:
        print(f"  [draft] {e}", file=sys.stderr)
        return None


async def score_draft(subject: str, body: str) -> tuple[float, list[str], str]:
    """Return (score, missing_list, reason). Uses LLM with rubric."""
    from pydantic import BaseModel

    class DraftScoreResult(BaseModel):
        score: float
        missing: list[str] = []
        reason: str = ""

    user = f"Subject: {subject}\n\nBody:\n{body[:8000]}"
    try:
        from ira.services.llm_client import get_llm_client

        client = get_llm_client()
        result = await client.generate_structured(
            system=SCORING_RUBRIC,
            user=user,
            response_model=DraftScoreResult,
            temperature=0.2,
            max_tokens=500,
        )
        return (float(result.score), result.missing or [], result.reason or "")
    except Exception as e:
        print(f"  [score] Structured failed, trying text fallback: {e}", file=sys.stderr)
        try:
            from ira.services.llm_client import get_llm_client
            text = await get_llm_client().generate_text(
                system=SCORING_RUBRIC,
                user=user,
                temperature=0.2,
                max_tokens=500,
            )
            # Parse JSON from response (may be wrapped in markdown)
            for start in ("{", "```json"):
                i = text.find(start)
                if i != -1:
                    text = text[i:].replace("```json", "").replace("```", "").strip()
                    break
            data = json.loads(text)
            return (
                float(data.get("score", 0)),
                data.get("missing") if isinstance(data.get("missing"), list) else [],
                data.get("reason", "") or "",
            )
        except Exception as e2:
            print(f"  [score] Fallback failed: {e2}", file=sys.stderr)
            return (0.0, ["Scoring failed"], str(e2))


def improve_draft(body: str, subject: str, missing: list[str]) -> tuple[str, str] | None:
    """Use LLM to add missing elements to the email; return (new_subject, new_body) or None."""
    try:
        import asyncio
        from ira.services.llm_client import get_llm_client

        async def _run():
            client = get_llm_client()
            system = "You are an editor. Add the missing elements to this email. Keep Rushabh voice and structure. Return the full revised email: first line 'Subject: ...', then a blank line, then the body. Do not add commentary."
            user = f"Missing elements to add: {chr(10).join('- ' + m for m in missing)}\n\nCurrent email:\nSubject: {subject}\n\n{body}"
            text = await client.generate_text(system=system, user=user[:12000], temperature=0.3, max_tokens=4000)
            subj = subject
            if text.strip().lower().startswith("subject:"):
                idx = text.find("\n")
                if idx != -1:
                    subj = text[len("subject:"):idx].strip()
                    text = text[idx:].lstrip()
            return (subj, text.strip())

        return asyncio.run(_run())
    except Exception as e:
        print(f"  [improve] {e}", file=sys.stderr)
        return None


def find_company_contacts(company: str, max_contacts: int = 3) -> list[str]:
    script = PROJECT_ROOT / "scripts/find_company_contacts.py"
    result = subprocess.run(
        [sys.executable, str(script), company, "--max", str(max_contacts), "--search-max", "50"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip() and "@" in line]


def extract_body_for_send(text: str) -> str:
    for start in ("Hi all,", "Hi team,", "Hi "):
        idx = text.find(start)
        if idx != -1:
            text = text[idx:]
            break
    end = text.rfind("www.machinecraft.org")
    if end != -1:
        text = text[: end + len("www.machinecraft.org")]
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def send_email(to: str, subject: str, body: str, cc: list[str] | None = None) -> bool:
    payload = {"to": to, "subject": subject, "body": body}
    if cc:
        payload["cc"] = ", ".join(cc)
    try:
        r = httpx.post(f"{BASE}/api/email/send", json=payload, timeout=30.0)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"  [send] {e}", file=sys.stderr)
        return False


def write_to_send(lead_id: int, lead: dict, subject: str, body: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    company_slug = _slug(lead.get("company_name", "company")[:40])
    name_slug = _slug((lead.get("client_name") or "contact")[:30])
    content = f"Subject: {subject}\n\n{body}"
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lead email workflow loop: draft → score → redo/improve until ≥9 → send")
    parser.add_argument("--next", type=int, default=5, help="Number of leads to process (default 5)")
    parser.add_argument("--after", type=int, default=49, help="Start after this lead ID (default 49)")
    parser.add_argument("--dry-run", action="store_true", help="Only draft and score; do not send (default)")
    parser.add_argument("--send", action="store_true", help="Actually send when score ≥ 9")
    parser.add_argument("--score-file", type=Path, metavar="PATH", help="Score an existing TO_SEND.md file and print score/missing; then exit")
    args = parser.parse_args()

    if args.score_file:
        path = args.score_file if args.score_file.is_absolute() else PROJECT_ROOT / args.score_file
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        text = path.read_text(encoding="utf-8")
        lines = text.strip().split("\n")
        subject = lines[0].replace("Subject: ", "").strip() if lines else ""
        body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        score, missing, reason = asyncio.run(score_draft(subject, body))
        print(f"Score: {score}/10")
        print(f"Reason: {reason}")
        if missing:
            print("Missing:", ", ".join(missing))
        return 0

    do_send = args.send and not args.dry_run
    leads = load_leads()
    if not leads:
        print("No enriched_leads.json found.", file=sys.stderr)
        return 1

    next_ids = get_next_lead_ids(leads, args.after, args.next)
    if not next_ids:
        print(f"No leads after ID {args.after} (excluding already sent).")
        return 0

    print(f"Next {len(next_ids)} leads: {next_ids}")
    if do_send:
        print("Mode: SEND (emails will be sent when score ≥ 9)")
    else:
        print("Mode: DRY-RUN (draft + score only; use --send to send)")

    for lead_id in next_ids:
        lead = get_lead(leads, lead_id)
        if not lead:
            continue
        email = (lead.get("email") or "").strip()
        company = (lead.get("company_name") or "").strip()
        name = (lead.get("client_name") or "").strip()
        if not email:
            print(f"\n[Lead {lead_id}] Skipping: no email")
            continue

        print(f"\n——— Lead {lead_id}: {name or company} ({email}) ———")

        # 1. Pull contact history
        print("  [1] Pulling contact history (Gmail)...")
        history_path = LEADS_DIR / f"lead{lead_id}_{_slug(company[:30])}_email_history.md"
        if not run_pull_contact_history(email, name or None, history_path):
            print("  [1] Pull history: no output (first-touch or API issue)")
        else:
            print("  [1] Pull history: OK")

        # 2. Draft
        draft_result = draft_email(lead, history_path if history_path.exists() else None, None)
        if not draft_result:
            print("  [2] Draft: FAILED")
            continue
        subject, body = draft_result
        to_send_path = LEADS_DIR / f"email_lead{lead_id}_{_slug((name or company)[:30])}_TO_SEND.md"
        write_to_send(lead_id, lead, subject, body, to_send_path)
        print("  [2] Draft: OK →", to_send_path.name)

        # 3. Score (async)
        print("  [3] Scoring draft...")
        score, missing, reason = asyncio.run(score_draft(subject, body))
        print(f"  [3] Score: {score}/10 — {reason}")

        # 4. Score gate: redo if < 8, improve if 8–9 until ≥ 9
        max_redo, max_improve = 1, 2
        redo_count, improve_count = 0, 0

        while score < 8 and redo_count < max_redo:
            redo_count += 1
            extra = f"Previous draft scored {score}. Missing: {', '.join(missing[:5])}. Produce a new draft that includes these elements."
            draft_result = draft_email(lead, history_path if history_path.exists() else None, extra)
            if not draft_result:
                break
            subject, body = draft_result
            write_to_send(lead_id, lead, subject, body, to_send_path)
            score, missing, reason = asyncio.run(score_draft(subject, body))
            print(f"  [4a] After redo: score {score}/10")

        while 8 <= score < 9 and improve_count < max_improve:
            improve_count += 1
            revised = improve_draft(body, subject, missing)
            if not revised:
                break
            subject, body = revised
            write_to_send(lead_id, lead, subject, body, to_send_path)
            score, missing, reason = asyncio.run(score_draft(subject, body))
            print(f"  [4b] After improve: score {score}/10")

        if score < 9:
            print(f"  [5] Score {score} < 9 — NOT SENDING. Review {to_send_path} and re-run or send manually.")
            continue

        # 5. Pre-send: multi-recipient
        contacts = find_company_contacts(company) if company else []
        if not contacts:
            contacts = [email]
        to_addr = contacts[0]
        cc_list = contacts[1:3]

        # 6. Send (if --send)
        if do_send:
            plain_body = extract_body_for_send(body)
            if send_email(to_addr, subject, plain_body, cc_list if cc_list else None):
                print(f"  [6] Sent to {to_addr}" + (f" Cc: {', '.join(cc_list)}" if cc_list else ""))
            else:
                print("  [6] Send FAILED")
        else:
            print(f"  [6] Would send to {to_addr}" + (f" Cc: {', '.join(cc_list)}" if cc_list else "") + " (use --send to send)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
