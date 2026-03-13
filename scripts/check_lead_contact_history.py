#!/usr/bin/env python3
"""Check if we've contacted a lead before — CRM interactions + optional Gmail search.

Run this **before** drafting any lead engagement email. Output tells you:
- Whether we have sent them an email before (CRM or Gmail)
- When we last contacted them and what about
- Whether they replied (from CRM interaction content or Gmail thread)
- So you can reference their reply or note "no reply to our last touch" in the new draft.

Usage:
  poetry run python scripts/check_lead_contact_history.py --email pinto@forma3d.pt
  poetry run python scripts/check_lead_contact_history.py --lead-id 3

Requires: PostgreSQL for CRM. Optional: Ira API running for Gmail search (--email-search).
"""
from __future__ import annotations

import argparse
import asyncio
import json
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


def _load_enriched_leads() -> list[dict]:
    path = PROJECT_ROOT / "data/imports/24_WebSite_Leads/ira-drip-campaign/data/enriched_leads.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Check prior contact history for a lead")
    parser.add_argument("--email", type=str, help="Contact email")
    parser.add_argument("--lead-id", type=int, help="Lead id from enriched_leads.json (resolves to email)")
    parser.add_argument("--email-search", action="store_true", help="Call Ira API to search Gmail for sent to this address")
    args = parser.parse_args()

    email = args.email
    if not email and args.lead_id is not None:
        leads = _load_enriched_leads()
        for L in leads:
            if L.get("id") == args.lead_id:
                email = L.get("email")
                print(f"Lead {args.lead_id}: {L.get('client_name')} @ {L.get('company_name')} → {email}")
                break
        if not email:
            print(f"No lead with id {args.lead_id} in enriched_leads.json", file=sys.stderr)
            sys.exit(1)

    if not email:
        parser.print_help()
        sys.exit(1)

    email = email.strip().lower()
    out: list[str] = []

    # 1) CRM: contact + interactions
    try:
        from ira.data.crm import CRMDatabase

        crm = CRMDatabase()
        await crm.create_tables()
        contact = await crm.get_contact_by_email(email)
        if not contact:
            out.append("CRM: No contact found — we have not logged any interaction for this email.")
        else:
            out.append(f"CRM: Contact found — {contact.name} ({contact.email})")
            interactions = await crm.list_interactions(filters={"contact_id": str(contact.id)})
            outbound = [i for i in interactions if getattr(i, "direction", None) == "OUTBOUND"]
            inbound = [i for i in interactions if getattr(i, "direction", None) == "INBOUND"]
            if not outbound and not inbound:
                out.append("CRM: No interactions logged for this contact.")
            else:
                if outbound:
                    out.append(f"CRM: Last OUTBOUND — {outbound[0].created_at.date() if outbound[0].created_at else '?'} | Subject: {outbound[0].subject or '(none)'}")
                    out.append(f"       Content preview: {(outbound[0].content or '')[:200]}...")
                if inbound:
                    out.append(f"CRM: Last INBOUND (their reply) — {inbound[0].created_at.date() if inbound[0].created_at else '?'} | Subject: {inbound[0].subject or '(none)'}")
                    out.append(f"       They replied: Yes. Preview: {(inbound[0].content or '')[:200]}...")
                elif outbound:
                    out.append("CRM: No inbound logged — they did not reply (or reply not logged).")
        await crm.close()
    except Exception as e:
        out.append(f"CRM: Error — {e}. (Is PostgreSQL running?)")

    # 2) Optional: Gmail search via Ira API
    if args.email_search:
        try:
            import httpx
            r = httpx.post(
                "http://localhost:8000/api/email/search",
                json={"to_address": email},
                timeout=10.0,
            )
            if r.status_code != 200:
                out.append(f"Email search: API returned {r.status_code}")
            else:
                data = r.json()
                threads = data.get("threads", data.get("results", []))
                if not threads:
                    out.append("Email search: No threads found to/from this address.")
                else:
                    out.append(f"Email search: Found {len(threads)} thread(s). Latest: {threads[0].get('subject', threads[0].get('snippet', ''))[:60]}...")
        except Exception as e:
            out.append(f"Email search: Error — {e}. (Is Ira API running? Use --email-search only if API is up.)")

    for line in out:
        print(line)
    print("\n→ Use this to decide: reference their reply in the new email, or note 'no reply to our last touch', or treat as first contact.")


if __name__ == "__main__":
    asyncio.run(main())
