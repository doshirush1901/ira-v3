#!/usr/bin/env python3
"""Send reply to Shreyas Enterprises — Option 1 (PF1-C-2010) queries with 10% offer."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

from openclaw.agents.ira.src.tools.google_tools import gmail_send

BODY = """Hi Shreyas,

Thanks for the questions on Option 1 — PF1-C-2010. Here are the answers in order:

(a) Maximum sheet size
2100 × 1100 mm (50 mm larger on each side than the forming area of 2000 × 1000 mm). That works well for standard dashboards and protection covers.

(b) Cooling speed
Standard cooling is centrifugal fans at 26 m³/hr per fan. Cooling time isn’t one fixed number — it depends on material type, sheet thickness, and whether the tool is thermoregulated, so we can’t give a single figure without your exact part and tool setup.
If you want faster cycles, we can add an optional Central Ducted Cooling System for about ₹10 Lakhs. That’s a high-flow blower feeding air through ducting to specific zones on the tool for targeted cooling; it typically improves cooling time by 20–30% vs the standard fans. Happy to include it in the quote if you want higher output.

(c) Best rates to help you finalise
For the PF1-C-2010 we can offer ₹45,00,000 (₹45 Lakhs) — 10% off the earlier price — to help you close. Subject to configuration and current pricing; GST extra.

(d) Delivery from PO
12–16 weeks from receipt of PO and advance payment.

(e) Transport and other variable costs
Price is ex-works Umbergaon. We can quote transport to Nashik separately, or you can arrange. Installation, commissioning and basic training we can outline once we close the order.

If you’d like to lock in the PF1-C-2010 at this price, we can move to a formal quote/PO. If you’re still weighing the larger PF1-C-3020 for bus-size dashboards, we can extend the same 10% there as well.

Best,
Rushabh"""


def main():
    result = gmail_send(
        to="enterprises.shreyas@gmail.com",
        subject="Re: Your queries — Option 1 (PF1-C-2010)",
        body=BODY,
    )
    print(result)


if __name__ == "__main__":
    main()
