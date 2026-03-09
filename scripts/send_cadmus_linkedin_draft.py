#!/usr/bin/env python3
"""Send Cadmus's first LinkedIn post draft to the founder via email."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "openclaw" / "agents" / "ira" / "src" / "tools"))

from google_tools import gmail_send

subject = "Cadmus: LinkedIn Post Draft — Automotive Bedliner Case Study"

body = """Hi Founder,

Cadmus here. Your first LinkedIn post is ready. Copy-paste the text below, attach the images, and post.

---

POST TEXT (copy everything below this line):

How do you thermoform a 5.5mm HDPE pickup truck bedliner without burning it or losing control of the sag?

You build a machine from scratch. That is what we did.

Customer-H — a major automotive components conglomerate — needed to produce bedliners for an OEM partner. The challenge? Deep-draw forming of thick HDPE sheets into a massive mould (1830 x 2550 mm) with precise sag control. No off-the-shelf machine could do it.

So we designed the PF1-3520/S/A — a custom thermoforming machine with an innovation we are proud of:

-> Sag-following bottom heater — sensors track the HDPE sheet sag in real-time, and servo motors move the heater down to maintain optimal heating distance. The sheet sags 250-400mm during heating — the heater follows it.

Specs:
- Forming area: 3500 x 2000 mm
- 560 IR ceramic heating elements (280 top + 280 bottom)
- 435 kW total connected load
- 300 m3/hr Busch vacuum pump + 9000L tank
- All-servo: mould table (2.2T), clamp frame, plug assist, heater movement
- Automatic sheet loading + closed-loop cooling with IR pyrometer

The machine is running at the customer's plant, producing bedliners for the OEM partner.

What started as a machine order turned into a long-term partnership — consulting, additional machines, and technology introductions.

We do not just sell machines. We solve forming problems.

#thermoforming #Machinecraft #MadeInIndia #automotive #HDPE #vacuumforming #innovation #bedliner #deepdraw #thermoformage #Thermoformen

---

IMAGES TO ATTACH (in this order):

1. LEAD IMAGE: The 3D CAD render of the full machine with sheets loaded (shows scale with person for reference)
   File: Customer-H Project/2.Order Details from Client/Cad Concept Pictures/Sheet_Loaded_Isometric.png

2. Machine with sheet in forming position (shows the bottom heater mechanism)
   File: Customer-H Project/2.Order Details from Client/Cad Concept Pictures/Sheet_Down_Isometric.png

3. Engineering drawing of the bedliner mould (shows technical depth)
   File: Customer-H Project/2.Order Details from Client/Tool CAD/Tool Drg. bedliner.png

4. PROOF SHOT: The actual mould marked HERO LINER OEM MODEL
   File: Customer-H Project/2.Order Details from Client/Tool Photos/57258.jpg

All files are in: data/imports/11_Project_Case_Studies/Customer-H Project/

If you have factory photos of the machine running at the customer's plant, use those as slide 1 instead.

---

- Cadmus, your CMO
"""

body_html = (
    "<html><body>"
    "<p>Hi Founder,</p>"
    "<p><b>Cadmus here.</b> Your first LinkedIn post is ready. Copy-paste the text below, attach the images, and post.</p>"
    "<hr>"
    "<h3>POST TEXT (copy everything below):</h3>"
    "<p>How do you thermoform a 5.5mm HDPE pickup truck bedliner without burning it or losing control of the sag?</p>"
    "<p>You build a machine from scratch. That is what we did.</p>"
    '<p>Customer-H &mdash; a major automotive components conglomerate &mdash; needed to produce bedliners for an OEM partner. '
    "The challenge? Deep-draw forming of thick HDPE sheets into a massive mould (1830 x 2550 mm) with precise sag control. No off-the-shelf machine could do it.</p>"
    "<p>So we designed the PF1-3520/S/A &mdash; a custom thermoforming machine with an innovation we are proud of:</p>"
    "<p>&rarr; <b>Sag-following bottom heater</b> &mdash; sensors track the HDPE sheet sag in real-time, and servo motors move the heater down to maintain optimal heating distance. "
    "The sheet sags 250-400mm during heating &mdash; the heater follows it.</p>"
    "<p><b>Specs:</b><br>"
    "&bull; Forming area: 3500 x 2000 mm<br>"
    "&bull; 560 IR ceramic heating elements (280 top + 280 bottom)<br>"
    "&bull; 435 kW total connected load<br>"
    "&bull; 300 m&sup3;/hr Busch vacuum pump + 9000L tank<br>"
    "&bull; All-servo: mould table (2.2T), clamp frame, plug assist, heater movement<br>"
    "&bull; Automatic sheet loading + closed-loop cooling with IR pyrometer</p>"
    "<p>The machine is running at the customer's plant, producing bedliners for the OEM partner.</p>"
    "<p>What started as a machine order turned into a long-term partnership &mdash; consulting, additional machines, and technology introductions.</p>"
    "<p><b>We do not just sell machines. We solve forming problems.</b></p>"
    "<p>#thermoforming #Machinecraft #MadeInIndia #automotive #HDPE #vacuumforming #innovation #bedliner #deepdraw #thermoformage #Thermoformen</p>"
    "<hr>"
    "<h3>IMAGES TO ATTACH (in this order):</h3>"
    "<ol>"
    "<li><b>LEAD IMAGE:</b> 3D CAD render of the full machine with sheets loaded<br><code>Sheet_Loaded_Isometric.png</code></li>"
    "<li>Machine with sheet in forming position (shows bottom heater)<br><code>Sheet_Down_Isometric.png</code></li>"
    "<li>Engineering drawing of the bedliner mould<br><code>Tool Drg. bedliner.png</code></li>"
    "<li><b>PROOF SHOT:</b> Actual mould marked HERO LINER OEM MODEL<br><code>57258.jpg</code></li>"
    "</ol>"
    "<p>All files in: <code>data/imports/11_Project_Case_Studies/Customer-H Project/</code></p>"
    "<p>If you have factory photos of the machine running at the customer's plant, use those as slide 1 instead.</p>"
    "<hr>"
    "<p>&mdash; Cadmus, your CMO</p>"
    "</body></html>"
)

result = gmail_send(
    to="founder@example-company.org",
    subject=subject,
    body=body,
    body_html=body_html,
)
print(result)
