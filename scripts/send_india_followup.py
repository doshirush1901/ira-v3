#!/usr/bin/env python3
"""
Board Meeting Follow-Up: Detailed emails for 30 critical+high Indian leads.

Uses the BoardMeetingResearcher pipeline to run deep research on each lead,
then GPT-4.1 to craft a personalized follow-up email.

Each email gets:
  1. Tavily company news search
  2. CRM past interaction history
  3. Alexandros archive search (past quotes, proposals)
  4. Company profile synthesis
  5. Proof story selection
  6. LLM synthesis for angle + hooks

Usage:
  python scripts/send_india_followup.py --preview          # Show first 3 drafts
  python scripts/send_india_followup.py --preview --all     # Show all drafts
  python scripts/send_india_followup.py --send              # Send all
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
log = logging.getLogger("india_followup")

CRM_DB = PROJECT_ROOT / "crm" / "ira_crm.db"

SIGNATURE = """Best,
Rushabh Doshi
Sales Head, Machinecraft Technologies
rushabh@machinecraft.in
www.machinecraft.in"""


def _get_hot_leads():
    conn = sqlite3.connect(str(CRM_DB))
    conn.row_factory = sqlite3.Row
    leads = conn.execute("""
        SELECT l.email, l.company, l.country, l.priority, l.notes,
               c.name, c.source
        FROM leads l LEFT JOIN contacts c ON l.email = c.email
        WHERE l.country = 'India'
          AND l.priority IN ('critical', 'high')
          AND l.email NOT LIKE '%placeholder%'
        ORDER BY
          CASE l.priority WHEN 'critical' THEN 1 ELSE 2 END,
          l.company
    """).fetchall()
    conn.close()
    return [dict(l) for l in leads]


async def _research_and_craft(lead: dict) -> dict:
    """Run board meeting research, then craft email with GPT-4.1."""
    from openclaw.agents.ira.src.agents.hermes.board_meeting import get_researcher
    import openai

    researcher = get_researcher()
    intel = await researcher.research(lead)

    company = lead["company"]
    name = lead.get("name", "")
    first_name = name.split()[0] if name else ""

    # Build rich context for GPT-4.1
    context_parts = [
        f"COMPANY: {company} ({lead.get('country', 'India')})",
        f"CONTACT: {name}" if name else "",
        f"PRIORITY: {lead.get('priority', 'high')}",
    ]
    if intel.get("company_news"):
        context_parts.append(f"\nCOMPANY NEWS:\n{intel['company_news']}")
    if intel.get("past_interactions"):
        context_parts.append(f"\nPAST INTERACTIONS:\n{intel['past_interactions']}")
    if intel.get("past_documents"):
        context_parts.append(f"\nPAST DOCUMENTS IN OUR ARCHIVE:\n{intel['past_documents']}")
    if intel.get("company_profile"):
        context_parts.append(f"\nCOMPANY PROFILE:\n{intel['company_profile']}")
    if intel.get("proof_stories"):
        context_parts.append(f"\nPROOF STORIES:\n{intel['proof_stories']}")
    if intel.get("news_hook"):
        context_parts.append(f"\nSUGGESTED NEWS HOOK: {intel['news_hook']}")
    if intel.get("personal_hook"):
        context_parts.append(f"\nSUGGESTED PERSONAL HOOK: {intel['personal_hook']}")
    if intel.get("company_insight"):
        context_parts.append(f"\nCOMPANY INSIGHT: {intel['company_insight']}")
    if intel.get("machine_recommendation"):
        context_parts.append(f"\nMACHINE RECOMMENDATION: {intel['machine_recommendation']}")

    system = (
        "You ARE Rushabh Doshi. You're the Sales Head at Machinecraft Technologies. "
        "You build thermoforming machines. You're writing a follow-up email to someone "
        "you've either met, sold to before, or researched thoroughly.\n\n"
        "HOW RUSHABH WRITES:\n"
        "- Starts with 'Hi [name]!' or 'Hey [name],' — never 'Dear' or 'Respected'\n"
        "- Conversational, warm, direct. Like texting a business contact, not writing a proposal.\n"
        "- Short paragraphs. No bullet-point lists in the email body.\n"
        "- Uses 'I' not 'we' — 'I wanted to share...' not 'We would like to inform...'\n"
        "- Mentions specific things: machine models, cycle times, sheet thickness, forming area\n"
        "- Never says 'I hope this email finds you well', 'touching base', 'reaching out', "
        "'synergies', 'leverage', or any corporate buzzwords\n"
        "- Ends casually: 'Let me know?', 'Worth a quick call?', 'Happy to chat.'\n"
        "- Signs off: just 'Best,' or 'Cheers,' then name and one-line title\n\n"
        "CONTENT RULES:\n"
        "- Open with the NEWS HOOK or PERSONAL HOOK naturally — weave it in, don't announce it\n"
        "- If we have PAST DOCUMENTS (quotes, NDAs), mention them casually\n"
        "- If we have PAST INTERACTIONS, reference them like you remember the conversation\n"
        "- Include a proof story with real numbers (forming area, cycle time, material)\n"
        "- Recommend a specific machine and say why in plain language\n"
        "- PF1 series = vacuum forming only. Never mention pressure forming for PF1.\n"
        "- AM series = thin gauge <=1.5mm only\n"
        "- Write 8-12 sentences. Detailed but not long-winded.\n"
        "- Plain text only. No HTML, no formatting, no bullet points.\n\n"
        "Sign off as:\nBest,\nRushabh Doshi\nSales Head, Machinecraft Technologies\n"
        "rushabh@machinecraft.in\nwww.machinecraft.in\n\n"
        "Return valid JSON with 'subject' and 'body' fields.\n"
    )

    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "\n".join(context_parts)},
            ],
            temperature=0.8,
            max_tokens=1500,
        )
        result = json.loads(response.choices[0].message.content)
        subject = result.get("subject", f"Follow-up for {company}")
        body = result.get("body", "")

        if "machinecraft" not in body[-200:].lower():
            body = body.rstrip() + f"\n\n{SIGNATURE}"

        return {
            "to_email": lead["email"],
            "to_name": first_name or company,
            "company": company,
            "country": lead.get("country", "India"),
            "priority": lead.get("priority", "high"),
            "subject": subject,
            "body": body,
            "intel_summary": {
                "news": bool(intel.get("company_news")),
                "crm": bool(intel.get("past_interactions")),
                "archive": bool(intel.get("past_documents")),
                "proof": bool(intel.get("proof_stories")),
            },
        }
    except Exception as e:
        log.error(f"  GPT-4.1 failed for {company}: {e}")
        return {
            "to_email": lead["email"],
            "to_name": first_name or company,
            "company": company,
            "country": lead.get("country", "India"),
            "priority": lead.get("priority", "high"),
            "subject": f"Following up — {company}",
            "body": f"Hi {first_name or 'there'},\n\n(Email generation failed — manual follow-up needed)\n\n{SIGNATURE}",
            "intel_summary": {},
        }


async def preview(show_all=False):
    leads = _get_hot_leads()
    limit = len(leads) if show_all else min(3, len(leads))
    log.info(f"Total hot Indian leads: {len(leads)}")
    log.info(f"Researching and crafting {'all' if show_all else f'first {limit}'}...\n")

    for i, lead in enumerate(leads[:limit], 1):
        log.info(f"[{i}/{limit}] Researching {lead['company']}...")
        email = await _research_and_craft(lead)
        intel = email.get("intel_summary", {})
        sources = [k for k, v in intel.items() if v]

        log.info(f"\n{'='*60}")
        log.info(f"EMAIL {i}/{limit} [{email['priority'].upper()}]")
        log.info(f"{'='*60}")
        log.info(f"To:      {email['to_name']} <{email['to_email']}>")
        log.info(f"Company: {email['company']} ({email['country']})")
        log.info(f"Subject: {email['subject']}")
        log.info(f"Sources: {', '.join(sources) if sources else 'none'}")
        log.info(f"{'─'*60}")
        log.info(email["body"])
        log.info("")

    if not show_all and len(leads) > limit:
        log.info(f"\n... and {len(leads) - limit} more. Use --all to see all.")


async def send():
    try:
        from openclaw.agents.ira.src.tools.google_tools import gmail_send
    except Exception as e:
        log.error(f"Gmail not available: {e}")
        return

    leads = _get_hot_leads()
    log.info(f"Sending follow-up emails to {len(leads)} hot Indian leads...\n")

    conn = sqlite3.connect(str(CRM_DB))
    sent = 0
    failed = 0

    for i, lead in enumerate(leads, 1):
        log.info(f"[{i}/{len(leads)}] Researching {lead['company']}...")
        email = await _research_and_craft(lead)

        log.info(f"  Subject: {email['subject']}")
        try:
            result = gmail_send(
                to=email["to_email"],
                subject=email["subject"],
                body=email["body"],
                plain_text_only=True,
            )
            if result and "Error" not in result:
                log.info(f"  SENT")
                sent += 1

                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT INTO email_log (email, direction, subject, body_preview, drip_stage, batch_id, sent_at) "
                    "VALUES (?, 'sent', ?, ?, 2, 'india_followup_1', ?)",
                    (email["to_email"], email["subject"], email["body"][:200], now),
                )
                conn.execute(
                    "UPDATE leads SET emails_sent = COALESCE(emails_sent, 0) + 1, last_email_sent = ?, updated_at = ? WHERE email = ?",
                    (now, now, email["to_email"]),
                )
                conn.execute(
                    "INSERT INTO deal_events (email, event, old_value, new_value, notes) "
                    "VALUES (?, 'email_sent', 'india_batch_1', 'india_followup_1', ?)",
                    (email["to_email"], f"Board Meeting follow-up: {email['subject']}"),
                )
                conn.commit()
                time.sleep(1.5)
            else:
                log.warning(f"  FAILED: {result}")
                failed += 1
        except Exception as e:
            log.error(f"  ERROR: {e}")
            failed += 1

    conn.close()
    log.info(f"\nDone. Sent: {sent}, Failed: {failed}, Total: {len(leads)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Board Meeting Follow-Up — Hot Indian Leads")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.send:
        asyncio.run(send())
    else:
        asyncio.run(preview(show_all=args.all))
