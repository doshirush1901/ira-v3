#!/usr/bin/env python3
"""Send the investor demo email to Saurin Shah."""
from pathlib import Path
from openclaw.agents.ira.src.tools.google_tools import gmail_send

html_path = Path(__file__).parent / "send_investor_saurin.html"
body_html = html_path.read_text()

result = gmail_send(
    to="Saurin.shah@aromaagencies.com",
    subject="We built an AI CFO. Here is what it sees inside Machinecraft.",
    body="Please view this email in HTML format.",
    body_html=body_html,
)
print(result)
