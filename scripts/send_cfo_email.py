#!/usr/bin/env python3
"""Send the CFO dashboard email to the board."""
from pathlib import Path
from openclaw.agents.ira.src.tools.google_tools import gmail_send

html_path = Path(__file__).parent / "cfo_email_body.html"
body_html = html_path.read_text()

result = gmail_send(
    to="rushabh@machinecraft.org",
    subject="Machinecraft CFO Dashboard - March 2026",
    body="Please view this email in HTML format for the full dashboard.",
    body_html=body_html,
    cc="manan@machinecraft.org,rajesh@machinecraft.org,deepak@machinecraft.org",
)
print(result)
