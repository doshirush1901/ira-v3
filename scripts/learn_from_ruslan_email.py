#!/usr/bin/env python3
"""Store learnings from the Ruslan (lead 2) engagement email in long-term memory.

So Hermes, Calliope, and other agents can recall this when drafting future lead emails.
Requires MEM0_API_KEY in .env. Run after sending the Ruslan email.

  poetry run python scripts/learn_from_ruslan_email.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


async def main() -> None:
    from ira.memory.long_term import LongTermMemory

    mem = LongTermMemory()
    if not getattr(mem, "_api_key", None) or not mem._api_key:
        print("MEM0_API_KEY not set; skipping memory store.")
        sys.exit(0)

    # 1) Ruslan send summary — recallable for "Ruslan", "SAFARI", "Turkey lead", "lead 2"
    ruslan_fact = (
        "Machinecraft sent a lead engagement email on 2026-03-10 to Ruslan Didenko (SAFARI, Turkey). "
        "Structure: NewsData.io ice breaker (Turkey–Europe trade), inquiry date 31 Oct 2022, "
        "2000×2000 PF1 specs as bullets, ~150k USD / 5 months lead time, EU refs (Netherlands, Dutch Tides, Sweden/UK/Belgium), "
        "stated we have no customer in Turkey yet, Dutch Tides PF1-X-6520 and NRC Russia two machines in production, "
        "application questions, CTA video call Thu/Fri. Subject: Your PF1 2000×2000 inquiry — EU references, Dutch Tides, and a quick catch-up."
    )
    r1 = await mem.store_fact(
        ruslan_fact,
        source="outbound_email:ruslan_didenko_safari_2026-03-10",
        confidence=0.9,
    )
    print("Stored Ruslan send summary:", len(r1), "memory entries")

    # 2) Validated lead-email pattern — recallable for "lead engagement", "draft email for lead", "outbound marketing"
    pattern_fact = (
        "Lead engagement emails use: ice breaker from news (e.g. NewsData.io), inquiry reminder with specs as bullets, "
        "budget and lead time from playbook, EU references and 'no customer in [country]' when true, then single CTA (e.g. video call). "
        "Validated by two sends: Vladimir Komplektant 2026-03-09, Ruslan Didenko SAFARI Turkey 2026-03-10. "
        "See data/knowledge/outgoing_marketing_email_workflow.md and lead_engagement_email_skill.md."
    )
    r2 = await mem.store_fact(
        pattern_fact,
        source="outbound_email:workflow_validated_2026-03-10",
        confidence=0.85,
    )
    print("Stored validated lead-email pattern:", len(r2), "memory entries")
    print("Done. Agents (Hermes, Calliope, Clio) will recall these when drafting or researching lead emails.")


if __name__ == "__main__":
    asyncio.run(main())
