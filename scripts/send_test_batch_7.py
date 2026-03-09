#!/usr/bin/env python3
"""
Test batch: 7 Indian leads through the full Board Meeting pipeline.
New Rushabh voice, plain text, deep research per lead.

Usage:
  python scripts/send_test_batch_7.py --preview   # Review all 7
  python scripts/send_test_batch_7.py --send       # Send all 7
"""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test_batch_7")

CRM_DB = PROJECT_ROOT / "crm" / "ira_crm.db"

TARGETS = [
    "gaurang.pandya@mutualautomotive.in",   # Critical — blazing hot, 10 quotes
    "vishnudas.gujarathi@vipbags.com",      # VIP Industries — luggage giant, past customer
    "spbhatia@jaquar.com",                  # Jaquar — sanitaryware, past customer
    "mirekthermoformers@gmail.com",         # Mirek — thermoformer, bought INP-5060
    "nanda.kishor@ltcompany.com",           # Lighting Technologies — past customer
    "ranjivrataboli@gmail.com",             # Smartline Coach — bus components
    "delmore.exp@delmore.in",              # Delmore Trading — pressure forming customer
]

SIGNATURE = "Best,\nRushabh Doshi\nSales Head, Machinecraft Technologies\nrushabh@machinecraft.in\nwww.machinecraft.in"


def _get_leads():
    conn = sqlite3.connect(str(CRM_DB))
    conn.row_factory = sqlite3.Row
    leads = []
    for email in TARGETS:
        row = conn.execute("""
            SELECT l.email, l.company, l.country, l.priority, l.notes,
                   c.name, c.source
            FROM leads l LEFT JOIN contacts c ON l.email = c.email
            WHERE l.email = ?
        """, (email,)).fetchone()
        if row:
            leads.append(dict(row))
    conn.close()
    return leads


async def _research_and_craft(lead: dict) -> dict:
    from openclaw.agents.ira.src.agents.hermes.board_meeting import get_researcher
    import openai

    researcher = get_researcher()
    intel = await researcher.research(lead)

    company = lead["company"]
    name = lead.get("name", "")
    first_name = name.split()[0] if name else ""
    # Strip honorifics
    if first_name in ("Mr.", "Ms.", "Mrs.", "Dr."):
        parts = name.split()
        first_name = parts[1] if len(parts) > 1 else parts[0]

    context_parts = [
        f"COMPANY: {company} ({lead.get('country', 'India')})",
        f"CONTACT: {name}" if name else "",
        f"PRIORITY: {lead.get('priority', 'high')}",
    ]
    for key, label in [
        ("company_news", "COMPANY NEWS"),
        ("past_interactions", "PAST INTERACTIONS"),
        ("past_documents", "PAST DOCUMENTS IN OUR ARCHIVE"),
        ("company_profile", "COMPANY PROFILE"),
        ("proof_stories", "PROOF STORIES"),
        ("news_hook", "SUGGESTED NEWS HOOK"),
        ("personal_hook", "SUGGESTED PERSONAL HOOK"),
        ("company_insight", "COMPANY INSIGHT"),
        ("machine_recommendation", "MACHINE RECOMMENDATION"),
    ]:
        if intel.get(key):
            context_parts.append(f"\n{label}:\n{intel[key]}")

    system = (
        "You ARE Rushabh Doshi. You're the Sales Head at Machinecraft Technologies. "
        "You build thermoforming machines. You're writing to someone you know or "
        "have researched thoroughly.\n\n"
        "HOW YOU WRITE:\n"
        "- Start with 'Hi [first name]!' — never 'Dear' or 'Respected'\n"
        "- Conversational. Like you're writing to a colleague, not a stranger.\n"
        "- Short paragraphs, no bullet points in the email.\n"
        "- Use 'I' — 'I saw that...', 'I wanted to share...'\n"
        "- Mention specifics: machine models, cycle times, sheet thickness, forming area\n"
        "- NEVER say 'I hope this email finds you well', 'touching base', 'reaching out', "
        "'synergies', 'leverage', or any corporate jargon\n"
        "- If you have past history with them, talk about it like you remember it\n"
        "- If you found news about them, mention it naturally — 'I saw that...' or 'Congrats on...'\n"
        "- If you have past quotes/documents, reference them casually\n"
        "- Include one proof story with real numbers\n"
        "- End casually: 'Let me know?', 'Worth a quick call?', 'Happy to chat.'\n"
        "- PF1 = vacuum forming only. AM = thin gauge <=1.5mm only. No pressure forming on PF1.\n"
        "- 8-12 sentences. Detailed but sounds like a person, not a brochure.\n"
        "- Plain text. No HTML. No bullet points. No numbered lists.\n\n"
        "Sign off EXACTLY like this (include all lines):\nBest,\nRushabh Doshi\nSales Head, Machinecraft Technologies\nrushabh@machinecraft.in\nwww.machinecraft.in\n\n"
        "Return valid JSON with 'subject' and 'body'.\n"
    )

    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n".join(p for p in context_parts if p)},
            ],
            temperature=0.85,
            max_tokens=1500,
        )
        result = json.loads(response.choices[0].message.content)
        subject = result.get("subject", f"Quick note — {company}")
        body = result.get("body", "")

        if "machinecraft" not in body[-200:].lower():
            body = body.rstrip() + f"\n\n{SIGNATURE}"

        return {
            "to_email": lead["email"],
            "to_name": first_name or company,
            "company": company,
            "subject": subject,
            "body": body,
            "intel": {k: bool(v) for k, v in intel.items() if v},
        }
    except Exception as e:
        log.error(f"Failed for {company}: {e}")
        return None


async def preview():
    leads = _get_leads()
    log.info(f"Researching and crafting {len(leads)} emails...\n")

    for i, lead in enumerate(leads, 1):
        log.info(f"[{i}/{len(leads)}] Researching {lead['company']}...")
        email = await _research_and_craft(lead)
        if not email:
            continue

        sources = [k for k in ("company_news", "past_interactions", "past_documents", "proof_stories", "news_hook") if email["intel"].get(k)]

        log.info(f"\n{'='*65}")
        log.info(f"EMAIL {i}/{len(leads)}")
        log.info(f"{'='*65}")
        log.info(f"To:      {email['to_name']} <{email['to_email']}>")
        log.info(f"Company: {email['company']}")
        log.info(f"Subject: {email['subject']}")
        log.info(f"Sources: {', '.join(sources)}")
        log.info(f"{'─'*65}")
        log.info(email["body"])
        log.info("")


async def send():
    try:
        from openclaw.agents.ira.src.tools.google_tools import gmail_send
    except Exception as e:
        log.error(f"Gmail not available: {e}")
        return

    leads = _get_leads()
    conn = sqlite3.connect(str(CRM_DB))
    sent = 0

    for i, lead in enumerate(leads, 1):
        log.info(f"[{i}/{len(leads)}] Researching {lead['company']}...")
        email = await _research_and_craft(lead)
        if not email:
            continue

        log.info(f"  Subject: {email['subject']}")
        try:
            result = gmail_send(
                to=email["to_email"],
                subject=email["subject"],
                body=email["body"],
                plain_text_only=True,
            )
            if result and "Error" not in result:
                log.info(f"  SENT (plain text)")
                sent += 1
                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT INTO email_log (email, direction, subject, body_preview, drip_stage, batch_id, sent_at) "
                    "VALUES (?, 'sent', ?, ?, 2, 'test_batch_7', ?)",
                    (email["to_email"], email["subject"], email["body"][:200], now),
                )
                conn.execute(
                    "UPDATE leads SET emails_sent = COALESCE(emails_sent, 0) + 1, last_email_sent = ?, updated_at = ? WHERE email = ?",
                    (now, now, email["to_email"]),
                )
                conn.commit()
                time.sleep(1.5)
            else:
                log.warning(f"  FAILED: {result}")
        except Exception as e:
            log.error(f"  ERROR: {e}")

    conn.close()
    log.info(f"\nDone. Sent {sent}/{len(leads)}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    if args.send:
        asyncio.run(send())
    else:
        asyncio.run(preview())
