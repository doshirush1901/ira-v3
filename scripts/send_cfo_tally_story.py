#!/usr/bin/env python3
"""Send the CFO Tally story email."""
from pathlib import Path
from openclaw.agents.ira.src.tools.google_tools import gmail_send

html_path = Path(__file__).parent / "cfo_email_tally_story.html"
body_html = html_path.read_text()

result = gmail_send(
    to="rushabh@machinecraft.org",
    subject="The Machinecraft Money Story - What Tally Told Us",
    body="Please view this email in HTML format.",
    body_html=body_html,
    cc="manan@machinecraft.org,rajesh@machinecraft.org,deepak@machinecraft.org",
)
print(result)
