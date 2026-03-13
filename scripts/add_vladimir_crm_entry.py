#!/usr/bin/env python3
"""Add Vladimir Kilunin (Komplektant) to CRM with deal and log the engagement email we sent.

Run once after sending the Vladimir engagement email (2026-03-09).
Requires PostgreSQL (e.g. docker compose -f docker-compose.local.yml up -d).

  poetry run python scripts/add_vladimir_crm_entry.py
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

    email = "kiluninv@gmail.com"
    contact = await crm.get_contact_by_email(email)
    if contact:
        print(f"Contact exists: {contact.name} ({contact.email})")
        contact_id = str(contact.id)
    else:
        company_id = await _ensure_company(crm, "Komplektant", region=None)
        contact = await crm.create_contact(
            name="Vladimir Kilunin",
            email=email,
            company_id=company_id,
            source="24_WebSite_Leads",
            role=None,
        )
        contact_id = str(contact.id)
        print(f"Created contact: {contact.name} ({contact.email})")

    # Deal for PF1-X-2012 sanitary-ware inquiry (we contacted them)
    deals = await crm.list_deals(filters={"contact_id": contact_id})
    title = "PF1-X-2012 sanitary-ware / bathtub thermoforming inquiry"
    deal = next((d for d in deals if d.title and title.lower() in d.title.lower()), None)
    if deal:
        print(f"Deal exists: {deal.title} (stage={deal.stage})")
        deal_id = str(deal.id)
    else:
        deal = await crm.create_deal(
            contact_id=contact_id,
            title=title,
            stage=DealStage.CONTACTED,
            machine_model="PF1-X-2012",
            value=0,
            notes="Engagement email sent 2026-03-09 (specs, references, CTA video call).",
        )
        deal_id = str(deal.id)
        print(f"Created deal: {deal.title} (stage={deal.stage})")

    # Log the outbound email we sent
    subject = "PF1-X-2012 Thermoforming for Komplektant — Sanitary-Ware Specs, Price & References"
    await crm.create_interaction(
        contact_id=contact_id,
        deal_id=deal_id,
        channel=Channel.EMAIL,
        direction=Direction.OUTBOUND,
        subject=subject,
        content="Engagement email sent 2026-03-09 from rushabh@machinecraft.org. Sanitary-ware specs, EUR 280k–380k indicative, Jaguar/Mirsant/RMbathroom references, Netherlands reference, CTA 15–20 min video call.",
    )
    print("Logged interaction: outbound email sent 2026-03-09")

    await crm.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
