#!/usr/bin/env python3
"""Ensure Naffco has main contact Emad, engineer Ahmed (manhole), Saudi contact (KSA), 2 projects, and account summaries.

Run from repo root: poetry run python scripts/naffco_crm_update.py

- Company: NAFFCO FZCO (or existing Naffco)
- Contacts: Emad (main), Ahmed (engineer, manhole), Saudi/KSA contact
- Deals (on Emad): (1) Manhole — PF1-X-3535, (2) KSA — PF1-X-5028 or PF1-X-4525
- Account summaries reflect all three people and proposal-sent status.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ira.data.crm import CRMDatabase
from ira.data.models import ContactType, DealStage


NAFFCO_COMPANY_NAMES = ("NAFFCO FZCO", "NAFFCO", "Naffco")

# Main contact
EMAD_EMAIL = os.environ.get("NAFFCO_EMAD_EMAIL", "emad@naffco.com")
EMAD_NAME = "Emad"
EMAD_ROLE = "Purchase Director / Main contact"

# Engineer — manhole project
AHMED_EMAIL = os.environ.get("NAFFCO_AHMED_EMAIL", "ahmed@naffco.com")
AHMED_NAME = "Ahmed"
AHMED_ROLE = "Engineer (manhole project)"

# Saudi / KSA project contact (update name when known)
SAUDI_EMAIL = os.environ.get("NAFFCO_SAUDI_EMAIL", "ksa@naffco.com")
SAUDI_NAME = os.environ.get("NAFFCO_SAUDI_NAME", "Saudi contact")
SAUDI_ROLE = "KSA project"

EMAD_ACCOUNT_SUMMARY = (
    "We have sent our proposal to Naffco and are awaiting replies. Main contact: Emad. "
    "Engineer Ahmed leads the manhole project (PF1-X-3535, no autoloader); "
    "the KSA project (PF1-X-5028 or PF1-X-4525, no autoloader) is with the Saudi contact. "
    "Latest quotes reflect both streams."
)
AHMED_ACCOUNT_SUMMARY = (
    "Engineer at Naffco; technical contact for manhole covers project. "
    "PF1-X-3535 quoted (no autoloader). Proposal sent; awaiting reply."
)
SAUDI_ACCOUNT_SUMMARY = (
    "Naffco contact for KSA project. PF1-X-5028 or PF1-X-4525 quoted (no autoloader). "
    "Proposal sent; awaiting reply."
)

DEALS_TO_ENSURE = [
    {
        "title": "Manhole covers — PF1-X-3535",
        "machine_model": "PF1-X-3535",
        "match_models": ["PF1-X-3535"],
        "notes": "Manhole covers. No autoloader. Engineer: Ahmed. Proposal sent; awaiting reply.",
    },
    {
        "title": "KSA — PF1-X-5028 or PF1-X-4525",
        "machine_model": "PF1-X-5028",
        "match_models": ["PF1-X-5028", "PF1-X-4525"],
        "notes": "KSA project. PF1-X-5028 or PF1-X-4525, no autoloader. Saudi contact. Proposal sent; awaiting reply.",
    },
]


async def main() -> None:
    crm = CRMDatabase()
    await crm.create_tables()

    # Company
    companies = await crm.list_companies()
    company = None
    for c in companies:
        if c.name and c.name.upper().strip() in {n.upper() for n in NAFFCO_COMPANY_NAMES}:
            company = c
            break
    if not company:
        company = await crm.create_company(
            name="NAFFCO FZCO",
            region="UAE",
            industry="Fire Safety Equipment",
        )
        print("Created company: NAFFCO FZCO")
    else:
        print(f"Using company: {company.name}")

    company_id = str(company.id)

    # Contacts: Emad (main), Ahmed, Saudi
    contacts_to_ensure = [
        (EMAD_EMAIL, EMAD_NAME, EMAD_ROLE, EMAD_ACCOUNT_SUMMARY, "Emad"),
        (AHMED_EMAIL, AHMED_NAME, AHMED_ROLE, AHMED_ACCOUNT_SUMMARY, "Ahmed"),
        (SAUDI_EMAIL, SAUDI_NAME, SAUDI_ROLE, SAUDI_ACCOUNT_SUMMARY, "Saudi"),
    ]
    emad_contact_id = None
    for email, name, role, summary, label in contacts_to_ensure:
        contact = await crm.get_contact_by_email(email)
        if not contact:
            contact = await crm.create_contact(
                name=name,
                email=email,
                company_id=company_id,
                role=role,
                source="naffco_crm_update",
                contact_type=ContactType.LEAD_WITH_INTERACTIONS,
            )
            print(f"Created contact: {name} <{email}> ({label})")
        else:
            print(f"Using contact: {contact.name} <{contact.email}> ({label})")
        contact_id = str(contact.id)
        if label == "Emad":
            emad_contact_id = contact_id
        await crm.update_contact(contact_id, account_summary=summary)

    if not emad_contact_id:
        emad_contact = await crm.get_contact_by_email(EMAD_EMAIL)
        emad_contact_id = str(emad_contact.id) if emad_contact else None
    if not emad_contact_id:
        print("Could not resolve Emad contact; skipping deals.")
        return

    # Deals on main contact (Emad)
    existing = await crm.get_deals_for_contact(emad_contact_id)
    existing_models = {d.get("machine_model", "").strip().upper() for d in existing}

    for spec in DEALS_TO_ENSURE:
        match_models = [m.strip().upper() for m in spec.get("match_models", [spec["machine_model"]]) if m]
        if any(m in existing_models for m in match_models):
            print(f"Deal already exists: {spec['title']}")
            continue
        await crm.create_deal(
            contact_id=emad_contact_id,
            title=spec["title"],
            value=0,
            stage=DealStage.PROPOSAL,
            machine_model=spec["machine_model"],
            notes=spec.get("notes"),
        )
        print(f"Created deal: {spec['title']}")
        for m in match_models:
            existing_models.add(m)

    print("Done. Naffco: Emad (main), Ahmed (engineer, manhole), Saudi (KSA); 2 deals; summaries set.")


if __name__ == "__main__":
    asyncio.run(main())
