#!/usr/bin/env python3
"""Print CRM list (deals with contact and company) from Postgres. Run from repo root."""
from __future__ import annotations

import asyncio
import os
import sys

# Run from repo root so ira is importable
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from ira.data.crm import CRMDatabase


async def main() -> None:
    crm = CRMDatabase()
    try:
        deals = await crm.list_deals_with_details(limit=500)
    except Exception as e:
        print("Error loading CRM (is Postgres up? DATABASE_URL set?):", e)
        return
    if not deals:
        print("No deals in CRM.")
        return
    print(f"CRM list ({len(deals)} deals) — customers / leads / companies we have sent quotes to\n")
    print(f"{'Company':<30} {'Contact':<25} {'Email':<35} {'Stage':<14} {'Value':>12} {'Updated'}")
    print("-" * 130)
    for d in deals:
        company = (d.get("company_name") or "")[:28]
        contact = (d.get("contact_name") or "")[:23]
        email = (d.get("contact_email") or "")[:33]
        stage = (d.get("stage") or "")[:12]
        value = d.get("value") or 0
        updated = (d.get("updated_at") or "")[:10]
        print(f"{company:<30} {contact:<25} {email:<35} {stage:<14} {value:>12,.0f} {updated}")
    print("-" * 130)
    print(f"Total: {len(deals)} deals.")


if __name__ == "__main__":
    asyncio.run(main())
