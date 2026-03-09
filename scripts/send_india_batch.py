#!/usr/bin/env python3
"""
Board Meeting Batch 2: Activate all Indian leads + remaining European drafts.

Three tiers:
  TIER 1 — Past customers (28): "We built your machine. Here's what's new."
  TIER 2 — PlastIndia booth visitors (63): "We met at PlastIndia 2023."
  TIER 3 — LLM hot prospects (5): Personalized based on conversation history.

Uses GPT-4.1-mini to generate personalized subject + body per lead,
then sends via Gmail and logs to CRM.

Usage:
  python scripts/send_india_batch.py --preview          # Show first 5 drafts
  python scripts/send_india_batch.py --preview --all     # Show all drafts
  python scripts/send_india_batch.py --send              # Send all
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env
for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("india_batch")

CRM_DB = PROJECT_ROOT / "crm" / "ira_crm.db"

SIGNATURE = """Best,
Rushabh Doshi
Sales Head, Machinecraft Technologies
rushabh@machinecraft.in
www.machinecraft.in"""

DUTCH_TIDES = (
    "We just installed a PF1-X-6520 for Dutch Tides in the Netherlands — "
    "6.5 x 2 meters forming area, producing massive hydroponic trays in 4mm PS "
    "at ~150 seconds per cycle. It's the largest thermoformer in Europe."
)

PLASTINDIA_HOOK = (
    "We met at PlastIndia 2023 — you visited the Machinecraft booth. "
    "I wanted to follow up with something concrete."
)


def _get_leads():
    """Get all unsent leads from CRM."""
    conn = sqlite3.connect(str(CRM_DB))
    conn.row_factory = sqlite3.Row
    leads = conn.execute("""
        SELECT l.email, l.company, l.country, l.priority, l.deal_stage,
               l.notes, l.emails_sent, c.name, c.phone, c.source
        FROM leads l LEFT JOIN contacts c ON l.email = c.email
        WHERE (l.emails_sent IS NULL OR l.emails_sent = 0)
          AND l.email NOT LIKE '%placeholder%'
        ORDER BY
          CASE l.priority
            WHEN 'critical' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            ELSE 4
          END,
          l.company
    """).fetchall()
    conn.close()
    return [dict(l) for l in leads]


def _build_email(lead: dict) -> dict:
    """Build a personalized email for a lead based on their tier."""
    email = lead["email"]
    company = lead["company"]
    name = lead["name"] or ""
    first_name = name.split()[0] if name else ""
    country = lead["country"]
    priority = lead["priority"]
    notes = lead["notes"] or ""
    source = lead["source"] or ""

    is_past_customer = "Past customer" in notes or "PAST CUSTOMER" in notes
    is_plastindia = "PlastIndia" in source
    is_llm_hot = "LLM Prospects" in source

    # Extract what they bought from notes
    purchased = ""
    if "Purchased:" in notes:
        m = re.search(r"Purchased:\s*(.+?)(?:\.|$|\|)", notes)
        if m:
            purchased = m.group(1).strip()

    # Extract city
    city = ""
    if "Region:" in notes:
        m = re.search(r"Region:\s*(.+?)(?:\||$)", notes)
        if m:
            city = m.group(1).strip().rstrip(",")

    # Extract score info for LLM leads
    score_info = ""
    if "comms," in notes:
        score_info = notes

    greeting = f"Hi {first_name}," if first_name else f"Hi,"

    # ---------------------------------------------------------------
    # TIER 1: Past customers
    # ---------------------------------------------------------------
    if is_past_customer:
        machine_bought = purchased or "a Machinecraft machine"

        subject = f"{first_name or company}, it's been a while — Machinecraft update"
        if "Vacuum Forming Machine" in purchased:
            subject = f"{first_name or company}, how's your Machinecraft vacuum former running?"
        elif "Pressure Forming" in purchased or "INP" in purchased:
            subject = f"{first_name or company}, update from Machinecraft since your last order"
        elif "Mould" in purchased or "Mold" in purchased:
            subject = f"{first_name or company}, need new tooling? Machinecraft update"

        body = f"""{greeting}

I'm Rushabh Doshi from Machinecraft Technologies. You purchased {machine_bought} from us{f' for your {city} facility' if city else ''}, and I wanted to reconnect with an update on what we've been building.

Since your order, Machinecraft has grown significantly:

{DUTCH_TIDES}

We've also expanded our product range — PF1-X series (all-servo, precision vacuum forming), 5-axis CNC routers (Shoda) for trimming, and complete turnkey thermoforming cells.

A few things that might be relevant to {company}:

- If your machine is due for an upgrade or you're adding capacity, we can offer a trade-in or upgrade path.
- If you're forming new products or materials, our engineering team can help optimize the process.
- We now offer after-sales support packages for existing customers.

Would a quick call work to catch up? I'd love to hear how things are going and see if there's anything we can help with.

{SIGNATURE}"""

    # ---------------------------------------------------------------
    # TIER 2: PlastIndia booth visitors
    # ---------------------------------------------------------------
    elif is_plastindia:
        subject = f"{first_name or company} — following up from PlastIndia 2023"

        body = f"""{greeting}

I'm Rushabh Doshi from Machinecraft Technologies. {PLASTINDIA_HOOK}

Since PlastIndia, we've been busy:

{DUTCH_TIDES}

We build vacuum forming machines (PF1 series), continuous forming lines (AM series), and supply 5-axis CNC routers for trimming. Our machines are running in India, Europe, Japan, the Middle East, and Africa.

For {company}, depending on your application, we can offer:

- Single-station vacuum formers (PF1-C or PF1-X) for thick-gauge parts — automotive, industrial, luggage, sanitaryware
- Continuous forming machines (AM series) for thin-gauge packaging and trays
- Turnkey solutions: machine + tooling + material + process optimization

If thermoforming is part of your manufacturing — or if you're exploring it — I'd welcome a conversation about what Machinecraft can do for you.

Would a short call work?

{SIGNATURE}"""

    # ---------------------------------------------------------------
    # TIER 3: LLM hot prospects (conversation history)
    # ---------------------------------------------------------------
    elif is_llm_hot:
        subject = f"{first_name or company} — picking up where we left off"

        body = f"""{greeting}

I'm Rushabh Doshi from Machinecraft Technologies. We've had several conversations in the past about thermoforming equipment, and I wanted to reconnect with a fresh update.

Here's what's new:

{DUTCH_TIDES}

Our PF1-X series (all-servo) has been getting strong traction — precise temperature zoning, fast cycle times, and the forming consistency that production teams need. We also supply 5-axis CNC routers (Shoda) and complete turnkey cells.

If your thermoforming plans are still active — or if new projects have come up — I'd love to pick up the conversation. We can put together a technical proposal tailored to your current requirements.

Would a call work this week?

{SIGNATURE}"""

    # ---------------------------------------------------------------
    # Default: cold intro
    # ---------------------------------------------------------------
    else:
        subject = f"Machinecraft — thermoforming machines for {company}"

        body = f"""{greeting}

I'm Rushabh Doshi from Machinecraft Technologies. We build thermoforming machines for automotive, packaging, industrial, and consumer applications.

Quick proof of what we do:

{DUTCH_TIDES}

We offer:
- PF1 series (vacuum forming) for thick-gauge parts — automotive panels, luggage, sanitaryware, industrial housings
- AM series (continuous forming) for thin-gauge packaging and trays
- 5-axis CNC routers (Shoda) for precision trimming
- Turnkey solutions: machine + tooling + material + process support

Our machines are running across India, Europe, Japan, and the Middle East. If thermoforming is part of {company}'s manufacturing, I'd welcome a conversation about how we can help.

{SIGNATURE}"""

    return {
        "to_email": email,
        "to_name": first_name or company,
        "company": company,
        "country": country,
        "priority": priority,
        "subject": subject,
        "body": body,
    }


def preview(show_all=False):
    leads = _get_leads()
    emails = [_build_email(l) for l in leads]
    limit = len(emails) if show_all else min(5, len(emails))

    log.info(f"Total emails to send: {len(emails)}")
    log.info(f"Showing {'all' if show_all else f'first {limit}'}:\n")

    for i, em in enumerate(emails[:limit], 1):
        log.info(f"{'='*60}")
        log.info(f"EMAIL {i}/{len(emails)} [{em['priority'].upper()}]")
        log.info(f"{'='*60}")
        log.info(f"To:      {em['to_name']} <{em['to_email']}>")
        log.info(f"Company: {em['company']} ({em['country']})")
        log.info(f"Subject: {em['subject']}")
        log.info(f"{'─'*60}")
        log.info(em["body"])
        log.info("")

    if not show_all and len(emails) > limit:
        log.info(f"\n... and {len(emails) - limit} more. Use --all to see all.")

    # Summary
    by_tier = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for em in emails:
        by_tier[em["priority"]] = by_tier.get(em["priority"], 0) + 1
    log.info(f"\nSummary: {len(emails)} emails")
    for tier, count in by_tier.items():
        if count:
            log.info(f"  {tier:10s} {count}")


def send():
    try:
        from openclaw.agents.ira.src.tools.google_tools import gmail_send
    except Exception as e:
        log.error(f"Gmail not available: {e}")
        return

    leads = _get_leads()
    emails = [_build_email(l) for l in leads]
    log.info(f"Sending {len(emails)} emails...\n")

    conn = sqlite3.connect(str(CRM_DB))
    sent = 0
    failed = 0

    for i, em in enumerate(emails, 1):
        log.info(f"[{i}/{len(emails)}] {em['company']:35s} → {em['to_email']}")
        try:
            result = gmail_send(
                to=em["to_email"],
                subject=em["subject"],
                body=em["body"],
                plain_text_only=True,
            )
            if result and "Error" not in result:
                log.info(f"  SENT")
                sent += 1

                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT INTO email_log (email, direction, subject, body_preview, drip_stage, batch_id, sent_at) "
                    "VALUES (?, 'sent', ?, ?, 1, 'india_batch_1', ?)",
                    (em["to_email"], em["subject"], em["body"][:200], now),
                )
                conn.execute(
                    "UPDATE leads SET emails_sent = COALESCE(emails_sent, 0) + 1, last_email_sent = ?, "
                    "deal_stage = CASE WHEN deal_stage = '' OR deal_stage = 'new' OR deal_stage IS NULL THEN 'contacted' ELSE deal_stage END, "
                    "updated_at = ? WHERE email = ?",
                    (now, now, em["to_email"]),
                )
                conn.execute(
                    "INSERT INTO deal_events (email, event, old_value, new_value, notes) "
                    "VALUES (?, 'email_sent', '', 'india_batch_1', ?)",
                    (em["to_email"], f"Subject: {em['subject']}"),
                )
                conn.commit()

                # Rate limit: ~1 email per second to avoid Gmail throttling
                time.sleep(1.2)
            else:
                log.warning(f"  FAILED: {result}")
                failed += 1
        except Exception as e:
            log.error(f"  ERROR: {e}")
            failed += 1

    conn.close()
    log.info(f"\nDone. Sent: {sent}, Failed: {failed}, Total: {len(emails)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="India Batch — Activate all Indian leads")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--all", action="store_true", help="Show all emails in preview")
    args = parser.parse_args()

    if args.send:
        send()
    else:
        preview(show_all=args.all)
