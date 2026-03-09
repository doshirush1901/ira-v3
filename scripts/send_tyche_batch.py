#!/usr/bin/env python3
"""
Tyche Board Meeting — Batch 1: Activate 7 European leads.

Each email:
  - Opens with a news/industry ice-breaker specific to the company
  - Introduces the Dutch Tides PF1-X-6520 story as proof
  - Connects Machinecraft to their specific application
  - Plain text only (no HTML)
  - Subject line designed to trigger curiosity

Usage:
  python scripts/send_tyche_batch.py --preview     # Review all drafts
  python scripts/send_tyche_batch.py --send         # Send via Gmail + log to CRM
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("tyche_batch")

SIGNATURE = """Best,
Rushabh Doshi
Sales Head, Machinecraft Technologies
rushabh@machinecraft.in
www.machinecraft.in"""

DUTCH_TIDES_BLURB = (
    "We just installed a PF1-X-6520 for Dutch Tides in the Netherlands — "
    "6.5 x 2 meters forming area, producing massive hydroponic trays in 4mm PS "
    "at ~150 seconds per cycle. It's the largest thermoformer in Europe right now. "
    "We supplied the machine, the sheets, and spent two weeks on-site fine-tuning "
    "the process with their team."
)

EMAILS = [
    # ===================================================================
    # 1. DUROtherm — Pavel Votruba (WARM)
    # News: Hartl brothers expanding Durotherm Holding (SPE article)
    # History: K-Fair 2019, tea gift, window plate quote, K2025
    # ===================================================================
    {
        "to_email": "pavel.votruba@durotherm.cz",
        "to_name": "Pavel",
        "company": "DUROtherm",
        "country": "Germany",
        "subject": "Pavel, the Hartl brothers are expanding — can we help?",
        "body": f"""Hi Pavel,

I came across an SPE article about the Hartl brothers combining Durotherm's thermoforming expertise with extrusion capabilities. Sounds like the group is growing — congratulations.

It's been a few months since K2025. You mentioned you'd talk to Mr. Hartl about Machinecraft, and I wanted to make that conversation easier with something concrete.

{DUTCH_TIDES_BLURB}

I bring this up because DUROtherm's strength in thick-sheet automotive and logistics parts is exactly where our PF1-X series fits. If the Hartl group is adding capacity — even one production cell for a new project — we can put together a technical comparison against Geiss that focuses on what matters to your team: cycle time, energy per shot, and total cost of ownership.

Also — the delivery time concern from the 2023 window plate quote is solved. We now have European service support with faster response times.

Would it make sense to set up a call with you and Mr. Hartl? I'll bring the data.

(And I hope Mrs. Votruba is still enjoying the tea.)

{SIGNATURE}""",
    },

    # ===================================================================
    # 2. Lakowa — Michael Jank (WARM)
    # News: 14th European Thermoforming Conference coming up
    # History: LinkedIn 2023, their auto-reply mentioned "PF1-3030"
    # ===================================================================
    {
        "to_email": "michael.jank@lakowa.com",
        "to_name": "Michael",
        "company": "Lakowa GmbH",
        "country": "Germany",
        "subject": "Michael, a question about Lakowa's PF1-3030",
        "body": f"""Hi Michael,

We connected on LinkedIn back in 2023, and I noticed something in a recent Lakowa communication — a reference to a "New PF1-3030 Vacuum Forming Machine."

Genuine question: is that one of ours, or a competitor's? Either way, I'd love to hear how it's performing.

The reason I ask — we just did something in the Netherlands that might interest your team:

{DUTCH_TIDES_BLURB}

Lakowa's work in technical parts for vehicles and machinery — ambulance interiors, tractor dashboards, machine covers — is exactly the space we're built for. Our PF1-X series (all-servo) gives you tight tolerances and consistent wall thickness on complex contours, and the 5-axis CNC routers (Shoda) we supply can help if trimming is ever a bottleneck.

With the 14th European Thermoforming Conference coming up, it might be a good time to connect. Would a short call work?

{SIGNATURE}""",
    },

    # ===================================================================
    # 3. VDL Wientjes Roden — Chris Mulder (COLD)
    # News: VDL ended public bus manufacturing in NL, moving to Belgium
    # History: We quoted them 3 machines in 2023
    # ===================================================================
    {
        "to_email": "c.mulder@vdlwientjesroden.nl",
        "to_name": "Chris",
        "company": "VDL Wientjes Roden",
        "country": "Netherlands",
        "subject": "Chris, we quoted VDL Roden 3 machines in 2023 — still relevant?",
        "body": f"""Hi Chris,

I'm Rushabh Doshi from Machinecraft Technologies. We prepared three quotes for VDL Roden back in 2023 — a PF1-1010, PF1-2010, and PF1-2520. I wanted to check if those projects are still alive, or if your needs have changed.

I also saw that VDL is restructuring bus manufacturing between the Netherlands and Belgium. If that's shifting production priorities or freeing up capex for the plastics division, the timing might be right to revisit.

Meanwhile, something happened in your backyard:

{DUTCH_TIDES_BLURB}

Dutch Tides is in the Netherlands, so you could visit the installation if you wanted to see it running. They're producing 6x2 meter hydroponic trays — different application from bus panels, but the machine capability and scale are directly relevant to VDL's large-format thermoforming needs.

If you're evaluating capacity for any upcoming contracts — bus panels, truck components, industrial housings — I'd be happy to put together an updated proposal based on where things stand now.

20 minutes on a call?

{SIGNATURE}""",
    },

    # ===================================================================
    # 4. AHT Cooling Systems — Daniel Stark (COLD)
    # News: AHT + Daikin showcasing at EuroShop 2026
    # ===================================================================
    {
        "to_email": "daniel.stark@aht.at",
        "to_name": "Daniel",
        "company": "AHT Cooling Systems",
        "country": "Austria",
        "subject": "Saw AHT at EuroShop 2026 — question about your liner production",
        "body": f"""Hi Daniel,

I'm Rushabh Doshi, founder of Machinecraft Technologies. I saw that AHT and the Daikin group showcased new refrigeration solutions at EuroShop 2026 — looks like the product range is expanding.

That got me thinking about the thermoforming side of your business. The fridge and freezer liners AHT produces in HIPS and ABS are exactly the kind of large-format, high-volume parts our machines are designed for.

Quick example of what we just did in Europe:

{DUTCH_TIDES_BLURB}

Different application, but the point is the same — large sheets, precise forming, high repeatability, and we supported the customer on-site until the process was dialed in.

For AHT specifically, our PF1-C series (closed-chamber, pneumatic) offers zone-by-zone ceramic IR heating that typically cuts energy consumption 15-20% versus older machines. At your production volumes, that adds up fast.

If AHT is looking at new product lines from EuroShop or upgrading existing liner capacity, I'd welcome a conversation about how we can help.

{SIGNATURE}""",
    },

    # ===================================================================
    # 5. Agoform — Jan Ottensmeyer (COLD)
    # News: Agoform recovering thermal energy from production lines
    # ===================================================================
    {
        "to_email": "jan.ottensmeyer@agoform.de",
        "to_name": "Jan",
        "company": "Agoform",
        "country": "Germany",
        "subject": "Jan, Agoform's energy recovery setup caught my eye",
        "body": f"""Hi Jan,

I'm Rushabh Doshi, founder of Machinecraft Technologies. I was reading about Agoform's approach to sustainability — recovering thermal energy from your production lines to heat your premises. That's smart engineering.

It tells me your team thinks carefully about energy efficiency in manufacturing, which is exactly why I'm reaching out.

Our thermoforming machines are designed with the same mindset. The PF1 series uses ceramic IR heaters with zone-by-zone control — you heat only where you need to, and the result is typically 15-20% lower energy per cycle compared to older machines. For a company already optimizing energy use, this fits naturally.

Here's what we just did in Europe:

{DUTCH_TIDES_BLURB}

For Agoform's products — cutlery trays, drawer inserts, automotive compartment liners — our machines deliver the dimensional consistency you need so parts fit perfectly every time. We also supply 5-axis CNC routers (Shoda) for clean, precise trimming on complex shapes.

If you're considering upgrading any of your forming lines or adding capacity, I'd love to understand what Agoform's current setup looks like.

Quick call?

{SIGNATURE}""",
    },

    # ===================================================================
    # 6. Fritzmeier Group — Alexandra Herrmann (COLD)
    # News: Fritzmeier Motherson rated by ICRA, growing in India
    # ===================================================================
    {
        "to_email": "alexandra_herrmann@hotmail.de",
        "to_name": "Alexandra",
        "company": "Fritzmeier Group",
        "country": "Germany",
        "subject": "Fritzmeier's cabin systems + a 6.5m thermoformer in Europe",
        "body": f"""Hi Alexandra,

I'm Rushabh Doshi, founder of Machinecraft Technologies. We build heavy-gauge thermoforming machines and CNC routers.

Fritzmeier's cabin systems for tractors, excavators, and utility vehicles — roof panels, headliners, door panels, engine covers — are exactly the kind of large, complex thermoformed parts our PF1-X series is designed for.

I also noticed the Fritzmeier Motherson joint venture is growing in India. We're based in India and already supply machines to automotive OEM suppliers here, so there may be a connection on that side too.

Here's what we just delivered in Europe:

{DUTCH_TIDES_BLURB}

For Fritzmeier, the relevance is scale and precision. Our PF1-X (all-servo) handles deep draws and complex contours — tractor roof panels with cosmetic surfaces and structural requirements. We offer turnkey cells: thermoforming machine + 5-axis CNC router + tooling, designed for a specific vehicle program.

If there's a new vehicle program coming up that needs dedicated thermoforming capacity, or if you're looking at equipment for the Indian operations, I'd welcome the chance to discuss it.

{SIGNATURE}""",
    },

    # ===================================================================
    # 7. Reiss Kunststofftechnik — Daniel Huber (COLD)
    # News: 95 years in business, precision focus
    # ===================================================================
    {
        "to_email": "d.huber@reiss-kt.de",
        "to_name": "Daniel",
        "company": "Reiss Kunststofftechnik",
        "country": "Germany",
        "subject": "95 years of Reiss precision — and a machine that matches it",
        "body": f"""Hi Daniel,

I'm Rushabh Doshi, founder of Machinecraft Technologies. 95 years of thermoforming expertise at Reiss is remarkable — not many companies can say that.

I'm reaching out because precision is what we build for. Our PF1-X series (all-servo) offers zone-by-zone temperature control and consistent vacuum distribution that directly reduces part warpage and wall thickness variation. For the kind of technical components Reiss produces — automotive, electronics, industrial — that consistency is everything.

Here's a recent example of what we can do:

{DUTCH_TIDES_BLURB}

Different scale, but the same engineering philosophy: we don't just deliver a machine, we stay on-site and fine-tune the process until it's right.

For Reiss, I'd focus on two things:

1. If you're running older thermoformers, a modern Machinecraft unit can shorten cycle times while improving quality stability — our ceramic IR heater zoning gives you granular control over heat distribution.

2. We also supply 5-axis CNC routers (Shoda) for trimming. For precision parts that need clean edges and tight tolerances, this complements the forming process.

Would a short call work to discuss what Reiss's equipment roadmap looks like?

{SIGNATURE}""",
    },
]


def preview_all():
    """Print all emails for review."""
    for i, email in enumerate(EMAILS, 1):
        print(f"\n{'='*70}")
        print(f"EMAIL {i}/7")
        print(f"{'='*70}")
        print(f"To:      {email['to_name']} <{email['to_email']}>")
        print(f"Company: {email['company']} ({email['country']})")
        print(f"Subject: {email['subject']}")
        print(f"{'─'*70}")
        print(email["body"])
        print()


def send_all():
    """Send all emails via Gmail and log to CRM."""
    try:
        from openclaw.agents.ira.src.tools.google_tools import gmail_send
    except Exception as e:
        log.error(f"Gmail not available: {e}")
        log.error("Run with --preview first to review drafts.")
        return

    crm_db = PROJECT_ROOT / "crm" / "ira_crm.db"
    crm_conn = None
    if crm_db.exists():
        crm_conn = sqlite3.connect(str(crm_db))

    sent_count = 0
    for i, email in enumerate(EMAILS, 1):
        log.info(f"\n[{i}/7] Sending to {email['to_name']} at {email['company']}...")
        try:
            result = gmail_send(
                to=email["to_email"],
                subject=email["subject"],
                body=email["body"],
                plain_text_only=True,
            )
            if result and "Error" not in result:
                log.info(f"  SENT: {result[:100]}")
                sent_count += 1

                thread_id = ""
                if "threadId" in result:
                    import re
                    m = re.search(r"threadId['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9]+)", result)
                    if m:
                        thread_id = m.group(1)

                if crm_conn:
                    now = datetime.now().isoformat()
                    crm_conn.execute(
                        "INSERT INTO email_log (email, direction, subject, body_preview, thread_id, drip_stage, batch_id, sent_at) "
                        "VALUES (?, 'sent', ?, ?, ?, 1, 'tyche_batch_1', ?)",
                        (email["to_email"], email["subject"], email["body"][:200], thread_id, now),
                    )
                    crm_conn.execute(
                        "UPDATE leads SET emails_sent = emails_sent + 1, last_email_sent = ?, "
                        "deal_stage = CASE WHEN deal_stage = '' OR deal_stage = 'new' THEN 'contacted' ELSE deal_stage END, "
                        "updated_at = ? WHERE email = ?",
                        (now, now, email["to_email"]),
                    )
                    crm_conn.execute(
                        "INSERT INTO deal_events (email, event, old_value, new_value, notes) "
                        "VALUES (?, 'email_sent', '', 'tyche_batch_1', ?)",
                        (email["to_email"], f"Subject: {email['subject']}"),
                    )
                    crm_conn.commit()
            else:
                log.warning(f"  FAILED: {result}")
        except Exception as e:
            log.error(f"  ERROR: {e}")

    if crm_conn:
        crm_conn.close()

    log.info(f"\nDone. Sent {sent_count}/7 emails.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tyche Batch 1 — Activate 7 European leads")
    parser.add_argument("--preview", action="store_true", help="Preview all emails")
    parser.add_argument("--send", action="store_true", help="Send all emails via Gmail")
    args = parser.parse_args()

    if args.send:
        send_all()
    else:
        preview_all()
