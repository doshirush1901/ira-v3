#!/usr/bin/env python3
"""Send reply to Darren Aguilar at Bascom Hunter re: PF1-0609 updated quote."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

existing = os.environ.get("ALLOWED_EMAIL_DOMAINS", "")
if existing:
    os.environ["ALLOWED_EMAIL_DOMAINS"] = existing + ",bascomhunter.com"
else:
    os.environ["ALLOWED_EMAIL_DOMAINS"] = "machinecraft.org,machinecraft.com,machinecraft.in,bascomhunter.com"

from openclaw.agents.ira.src.tools.google_tools import gmail_send

TO = "aguilar@bascomhunter.com"
CC = "sales@machinecraft.org"
SUBJECT = "Re: Updated Quote – PF1-0609 Vacuum Former | Machinecraft"

BODY = """Hi Darren,

Yes, this helps — thanks for the details.

Sheet size: 24×36" matches the PF1-0609 standard sheet size (610×914 mm), so we're a good fit there.

Thickness: I'm reading your range as 0.060" to 0.125" (about 1.5–3.2 mm). Our quote is for 2–10 mm; the 2–3.2 mm part of your range is in spec. At the thin end (around 1.5 mm / 0.060") we'd confirm during trial/FAT that heating and cycle work for you, but we don't see a blocker. If you meant a different min/max, just say and we'll align.

Flexibility on sheet dimensions: Noted that thickness stays fixed per run and you can vary sheet sizes. The PF1-0609 has a fixed working window for 610×914 mm; if you later need other standard sizes we can talk options.

One more thing: is your material around 1.5 mm supplied as cut sheets or in roll form? That helps us align the quote with your setup.

Next step: if you can share your thoughts on the optional upgrades (servo lower table, fast loading, servo valve) and any voltage/power requirements for the new facility, I'll get a formal updated quotation over to you.

Best regards,
Rushabh"""

if __name__ == "__main__":
    print(f"To:      {TO}")
    print(f"CC:      {CC}")
    print(f"Subject: {SUBJECT}")
    print(f"Body length: {len(BODY)} chars")
    print("-" * 60)

    if "--send" in sys.argv:
        result = gmail_send(
            to=TO,
            subject=SUBJECT,
            body=BODY,
            cc=CC,
            plain_text_only=True,
        )
        print(f"\nResult: {result}")
    else:
        print("\nPREVIEW MODE — add --send to actually send")
        print("=" * 60)
        print(f"Subject: {SUBJECT}")
        print(f"To: {TO}")
        print(f"CC: {CC}")
        print("-" * 60)
        print(BODY)
