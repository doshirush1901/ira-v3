#!/usr/bin/env python3
"""Send an intro from Ira to Rushabh: one email + one Telegram message."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

INTRO_EMAIL_SUBJECT = "Ira is live — your Intelligent Revenue Assistant"
INTRO_EMAIL_BODY = """Hi Rushabh,

I'm Ira, your Intelligent Revenue Assistant. I'm now up and running with access to:

• Knowledge (Qdrant, Mem0, machine specs, documents)
• Memory (long-term and conversation context)
• The full pantheon: Clio, Iris, Hermes, Plutus, Atlas, Asclepius, Tyche, Arachne, and the rest
• Board-style workflows for quotes, pipeline reviews, outreach, and production

You can talk to me on Telegram, email, or the CLI. I'll research, draft, fact-check, and follow our collaboration rules.

Let me know when you're ready to put me to work.

— Ira"""

INTRO_TELEGRAM = (
    "👋 Hi Rushabh — Ira here. I'm live and ready. "
    "You can message me here on Telegram, email me, or use the CLI. "
    "I have full access to knowledge, memory, and all agents. Say hi when you're ready."
)


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = (
        os.environ.get("RUSHABH_TELEGRAM_ID")
        or os.environ.get("EXPECTED_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID", "")
    ).strip()
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN or chat ID not set; skipping Telegram.")
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                print("Telegram: message sent.")
                return True
            print(f"Telegram: unexpected status {r.status}")
            return False
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def main():
    print("Sending intro from Ira to Rushabh...")
    # 1. Email
    try:
        from openclaw.agents.ira.src.tools.google_tools import gmail_send
        result = gmail_send(
            to="rushabh@machinecraft.org",
            subject=INTRO_EMAIL_SUBJECT,
            body=INTRO_EMAIL_BODY,
        )
        print(f"Email: {result}")
    except Exception as e:
        print(f"Email error: {e}")
    # 2. Telegram
    send_telegram(INTRO_TELEGRAM)
    print("Done.")


if __name__ == "__main__":
    main()
