#!/usr/bin/env python3
"""Send the investor demo email v2 to Saurin Shah (via Rushabh for forwarding)."""
from pathlib import Path
from openclaw.agents.ira.src.tools.google_tools import gmail_send

html_path = Path(__file__).parent / "send_investor_saurin_v2.html"
body_html = html_path.read_text()

result = gmail_send(
    to="rushabh@machinecraft.org",
    subject="FWD TO SAURIN: We built an AI CFO. Here is what it sees.",
    body="Please view in HTML. Forward to Saurin.shah@aromaagencies.com",
    body_html=body_html,
)
print(result)
