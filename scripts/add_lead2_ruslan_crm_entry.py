#!/usr/bin/env python3
"""Add Ruslan Didenko (SAFARI, Turkey) to CRM and log the engagement email we sent.

Run once after sending the lead 2 engagement email.
Requires PostgreSQL (e.g. docker compose -f docker-compose.local.yml up -d).

  poetry run python scripts/add_lead2_ruslan_crm_entry.py
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


async def _ensure_company(crm, name: str, region: str | None = None):
    companies = await crm.list_companies()
    for c in companies:
        if c.name and c.name.lower() == name.lower():
            return str(c.id)
    company = await crm.create_company(name=name, region=region)
    return str(company.id)


async def main() -> None:
    from ira.data.crm import CRMDatabase
    from ira.data.models import Channel, DealStage, Direction

    crm = CRMDatabase()
    await crm.create_tables()

    email = "ruslan.didenko@safariotomotiv.com"
    company_name = "SAFARI ARAÇ EKİPMANLARI SAN. ve TİC"
    contact = await crm.get_contact_by_email(email)
    if contact:
        print(f"Contact exists: {contact.name} ({contact.email})")
        contact_id = str(contact.id)
    else:
        company_id = await _ensure_company(crm, company_name, region="Turkey")
        contact = await crm.create_contact(
            name="Ruslan Didenko",
            email=email,
            company_id=company_id,
            source="24_WebSite_Leads",
            role=None,
        )
        contact_id = str(contact.id)
        print(f"Created contact: {contact.name} ({contact.email})")

    title = "PF1 2000×2000 automotive thermoforming inquiry"
    deals = await crm.list_deals(filters={"contact_id": contact_id})
    deal = next((d for d in deals if d.title and "2000" in (d.title or "")), None)
    if deal:
        print(f"Deal exists: {deal.title} (stage={deal.stage})")
        deal_id = str(deal.id)
    else:
        deal = await crm.create_deal(
            contact_id=contact_id,
            title=title,
            stage=DealStage.CONTACTED,
            machine_model="PF1 2000×2000",
            value=0,
            notes="Engagement email sent 2026-03-10. ~150k USD, 5 months lead time. EU refs, Dutch Tides, NRC Russia in production.",
        )
        deal_id = str(deal.id)
        print(f"Created deal: {deal.title} (stage={deal.stage})")

    subject = "Your PF1 2000×2000 inquiry — EU references, Dutch Tides, and a quick catch-up"
    await crm.create_interaction(
        contact_id=contact_id,
        deal_id=deal_id,
        channel=Channel.EMAIL,
        direction=Direction.OUTBOUND,
        subject=subject,
        content="Engagement email sent 2026-03-10 from rushabh@machinecraft.org. NewsData.io ice breaker (Türkiye–Europe trade). Specs, 150k USD, 5 mo lead time, EU refs, Dutch Tides, NRC Russia 2 machines in production. CTA video call Thu/Fri.",
    )
    print("Logged interaction: outbound email sent 2026-03-10")

    await crm.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
