#!/usr/bin/env python3
"""Draft Lead 21 (Mustapha Hadjri, Ekoless, Algeria) with full workflow context. Uses Ira draft API."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"

CONTEXT = """
You are drafting a single re-engagement email to this lead. Follow the FULL workflow from data/knowledge/outgoing_marketing_email_workflow.md and prompts/email_rushabh_voice_brand.txt.

Recipient: ekoless.dz@gmail.com
Contact name: Mustapha Hadjri
Company: Ekoless
Region: Algeria (.dz). Quote in EUR.

--- OPENING NEWS HOOK (use in first 1–2 sentences; do not say "I saw on your site") ---
In May 2025 Algeria's Industry Ministry announced a new Algero-Italian GIE (Siplast-ENPC and SIGIT) for plastic and rubber automotive components, with production in Sétif — part of localising the automotive supply chain. Use this as ice breaker; ask how things are on their side with Ekoless.

--- CONTACT CONTEXT ---
Lead 21: Mustapha Hadjri, Ekoless, Algeria. Form inquiry Mar 2023: 2500×2500 mm forming area, 500 mm depth, up to 4 mm sheet, PE-HD. Professional tier: full servo (heater, upper/lower table). Multi-segment interest (automotive, sanitary, refrigeration, pallets, suitcases). Only our outbound so far (PF1-3030, K-Show drip); no reply. No formal quote sent. Not a client.

--- MACHINE THAT FITS + PRICE ---
Their ask: 2500×2500 mm, 500 mm depth, 4 mm, PE-HD, full servo. Match: PF1-X class (servo). Closest standard PF1-3030 (3000×3000) or we quote 2500×2500. Include in email as bullets: forming area, max depth, sheet thickness, materials (PE-HD and broader), loading (manual cut-sheet), movements (servo), heater (IR Quartz). Indicative price: ~€150,000–180,000 EUR (EXW). Lead time 24–28 weeks from PO.

--- REGION REFERENCES ---
EU references (where they can see machines): Netherlands — Dezet Plastics, Dutch Tides (near Den Haag). Dutch Tides has our PF1-X-6520 (6.5×2 m), largest in Europe. Mention one short sentence so they know we have references in the region.

--- COUNTRY CHECK ---
We have NO customer in Algeria yet. Say so clearly: "I've checked our installation list — we don't yet have a customer in Algeria. Ekoless could be the first; we're keen to support a reference in the region."

--- DRIVE CURIOSITY: APPLICATION QUESTIONS ---
Ask 1–2 short questions about their application: What parts are they planning to form (dashboards, trim, sanitary, pallets)? Volumes? Is this their first thermoforming line or do they already have equipment?

--- STRUCTURE AND VOICE ---
Structure: Greeting → NEWS HOOK (1–2 sentences) → WHERE WE LEFT OFF — (short recap: they got in touch in 2023, we've sent updates, we've kept their spec on file) → THE MACHINE THAT FITS YOUR SPEC — (bullets: forming area, depth, sheet, materials, loading, servo, heater; then indicative € and lead time) → EU references (one short paragraph) → "We don't have a customer in Algeria yet" → A FEW QUESTIONS ABOUT YOUR APPLICATION — (bullets) → Single CTA: video call (e.g. Thu or Fri) or reply for formal quote. Sign-off: Best regards, Rushabh Doshi, Director — Machinecraft, rushabh@machinecraft.org, www.machinecraft.org.
Use Rushabh voice: "I" not "we", short paragraphs, no buzzwords. No pipe tables; bullets only. Human, not bot. One clear CTA.
"""


def main() -> int:
    history_path = PROJECT_ROOT / "data/imports/24_WebSite_Leads/lead21_mustapha_hadjri_email_history.md"
    context = CONTEXT
    if history_path.exists():
        context += "\n\n--- CONTACT HISTORY (logic tree; use for recap, do not repeat proposals verbatim) ---\n\n"
        context += history_path.read_text(encoding="utf-8")

    try:
        r = httpx.post(
            f"{BASE}/api/email/draft",
            json={
                "to": "ekoless.dz@gmail.com",
                "subject": "Your 2500×2500 thermoforming inquiry — Algeria and an offer",
                "context": context,
                "tone": "professional",
            },
            timeout=90.0,
        )
        r.raise_for_status()
        out = r.json()
        body = out.get("body", "")
        subject = out.get("subject", "Your 2500×2500 thermoforming inquiry — Algeria and an offer")
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        return 1
    except Exception as e:
        print(e, file=sys.stderr)
        return 1

    out_path = PROJECT_ROOT / "data/imports/24_WebSite_Leads/email_lead21_mustapha_hadjri_TO_SEND.md"
    out_path.write_text(
        f"""# Email to send — Mustapha Hadjri (Ekoless, Algeria)

**To:** ekoless.dz@gmail.com  
**From:** rushabh@machinecraft.org  
**Lead:** Mustapha Hadjri, Ekoless — Multi-segment (automotive, sanitary, pallets, etc.), Algeria. 2500×2500 mm, 500 mm, 4 mm PE-HD, servo. Full workflow.

**Send as new thread.**

**Source:** lead21_mustapha_hadjri_contact_context.md, lead21_mustapha_hadjri_email_history.md. News: Algeria Siplast-SIGIT GIE May 2025. No customer in Algeria yet.

---

## Email body (copy below)

**Subject:** {subject}

{body}
""",
        encoding="utf-8",
    )
    print(f"Wrote draft to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
