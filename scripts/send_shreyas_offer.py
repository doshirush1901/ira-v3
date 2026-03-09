#!/usr/bin/env python3
"""Send PF1-C-2010 + PF1-C-3020 offer to Shreyas Enterprises (Nashik)."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

from openclaw.agents.ira.src.tools.google_tools import gmail_send

html_path = Path(__file__).parent / "send_shreyas_offer.html"
body_html = html_path.read_text()

result = gmail_send(
    to="enterprises.shreyas@gmail.com",
    subject="Machinecraft — PF1-C-2010 & PF1-C-3020 Details as Discussed",
    body="Hi Shreyas, please find the machine details as discussed. View in HTML for the full spec tables.",
    body_html=body_html,
)
print(result)
