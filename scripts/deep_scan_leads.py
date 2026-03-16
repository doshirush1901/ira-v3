#!/usr/bin/env python3
"""Deep scan of leads: Mem0, Neo4j, Qdrant, Alexandros, email history, and web intel.

For each lead we:
1. Mem0 — recall long-term memories (contact + global; customer facts often under global)
2. CRM — customer/deal check (Won deals = customer; machine_model, stage, title)
3. Neo4j + Qdrant — knowledge base and graph (via Ira query)
4. Alexandros — document archive (via Ira query)
5. Email — double-check interaction via Gmail API + pull_contact_email_history for relationship summary
6. Web — Iris/web search + optional scrape for company intel to inform next-step email

Requires: Ira API running (for Mem0, email search, query). Optional: run
  poetry run python scripts/top50_hot_leads_excluding_customers.py --output data/reports/top50_good_leads.csv
first to get a list of good leads (communicated only).

Usage:
  poetry run python scripts/deep_scan_leads.py --input data/reports/top50_good_leads.csv --limit 5
  poetry run python scripts/deep_scan_leads.py --input data/reports/top50_good_leads.csv --limit 10 --output data/reports/deep_scan_report.md

Note: Use --input (with two dashes). The CSV is written by top50 script to data/reports/top50_good_leads.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    httpx = None

API_BASE = os.environ.get("IRA_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SECRET_KEY", "")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def load_leads_from_csv(path: Path, limit: int) -> list[dict[str, str]]:
    """Load leads from top50 good leads CSV (email, name, company, source, emails_from_them, genuine_replies)."""
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r):
            if limit > 0 and i >= limit:
                break
            if row.get("email") and "@" in row.get("email", ""):
                rows.append(row)
    return rows


def recall_memory(query: str, user_id: str = "global", limit: int = 5) -> list[str]:
    """Mem0 recall via API. Use user_id=email for contact-specific, user_id=global for company/customer facts."""
    if not httpx:
        return []
    try:
        r = httpx.get(
            f"{API_BASE}/api/memory/recall",
            params={"query": query, "user_id": user_id, "limit": limit},
            headers=_headers(),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return list(data.get("memories", []))
    except Exception:
        return []


def recall_memory_for_lead(company: str, email: str, limit_per_id: int = 5) -> list[str]:
    """Recall from Mem0 for both contact (user_id=email) and global (company/customer facts).
    Customer facts like 'DEZET took K2025 PF1-X-1210' are often stored under user_id=global."""
    seen: set[str] = set()
    merged: list[str] = []
    query = f"{company} {email}"
    for uid in (email, "global"):
        for m in recall_memory(query, user_id=uid, limit=limit_per_id):
            key = m[:500]
            if key not in seen:
                seen.add(key)
                merged.append(m)
    # Also try a customer/machine-oriented query under global (catches "X is our customer", "took machine Y")
    if company and company != "—":
        customer_query = f"{company} customer machine order K2025 PF1"
        for m in recall_memory(customer_query, user_id="global", limit=3):
            key = m[:500]
            if key not in seen:
                seen.add(key)
                merged.append(m)
    return merged


def fetch_all_deals(limit: int = 500) -> list[dict]:
    """Fetch deals from CRM API (contact_email, stage, title, machine_model, company_name)."""
    if not httpx:
        return []
    try:
        r = httpx.get(
            f"{API_BASE}/api/deals",
            params={"limit": limit},
            headers=_headers(),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return list(data.get("deals", []))
    except Exception:
        return []


def get_deals_for_contact(email: str, all_deals: list[dict]) -> list[dict]:
    """Filter deals by contact email (normalized)."""
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return []
    return [
        d for d in all_deals
        if (d.get("contact_email") or "").strip().lower() == email_lower
    ]


def format_crm_section(deals: list[dict]) -> str:
    """Format 'Customer / deal (CRM)' section: Won = customer, else list stage + title/machine."""
    if not deals:
        return "(no CRM deal for this contact)"
    won = [d for d in deals if (d.get("stage") or "").upper() == "WON"]
    lines = []
    if won:
        lines.append("**Customer.** Won deal(s):")
        for d in won:
            title = (d.get("title") or "").strip() or "—"
            machine = (d.get("machine_model") or "").strip()
            if machine:
                lines.append(f"- {title} — machine: {machine}")
            else:
                lines.append(f"- {title}")
    rest = [d for d in deals if (d.get("stage") or "").upper() != "WON"]
    if rest:
        if lines:
            lines.append("")
        lines.append("Other deal(s):")
        for d in rest:
            stage = (d.get("stage") or "—")
            title = (d.get("title") or "").strip() or "—"
            machine = (d.get("machine_model") or "").strip()
            if machine:
                lines.append(f"- [{stage}] {title} — {machine}")
            else:
                lines.append(f"- [{stage}] {title}")
    return "\n".join(lines)


def email_search(from_address: str, max_results: int = 30) -> dict:
    """Gmail search: emails from this address (they wrote to us)."""
    if not httpx:
        return {"count": 0, "emails": []}
    try:
        r = httpx.post(
            f"{API_BASE}/api/email/search",
            json={"from_address": from_address.strip(), "max_results": max_results},
            headers=_headers(),
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"count": 0, "emails": []}


def ira_query(query: str, user_id: str = "deep_scan") -> str:
    """Single full pipeline query (uses retriever, agents, etc.)."""
    if not httpx:
        return ""
    try:
        r = httpx.post(
            f"{API_BASE}/api/query",
            json={"query": query, "user_id": user_id},
            headers=_headers(),
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or data.get("answer") or "").strip()
    except Exception as e:
        return f"(Query failed: {e})"


def ask_agent(agent_name: str, question: str) -> str:
    """Call a single agent (e.g. alexandros, iris) via /api/query/agent."""
    if not httpx:
        return ""
    try:
        r = httpx.post(
            f"{API_BASE}/api/query/agent",
            json={"agent_name": agent_name, "query": question},
            headers=_headers(),
            timeout=90,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()
    except Exception as e:
        return f"(Agent {agent_name} failed: {e})"


def pull_contact_email_history(email: str, out_path: Path) -> tuple[int, str]:
    """Run pull_contact_email_history.py; return (thread_count, path). Summarize from file if exists."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "pull_contact_email_history.py"),
                "--email", email,
                "--output", str(out_path),
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception:
        return 0, ""
    if not out_path.exists():
        return 0, ""
    text = out_path.read_text(encoding="utf-8", errors="replace")
    # Parse "Total threads found: N"
    total = 0
    for line in text.splitlines():
        if "Total threads found:" in line:
            try:
                total = int(line.split(":")[-1].strip())
            except ValueError:
                pass
            break
    # Build short summary from "Proposals we sent" and "Their feedback" sections
    summary_parts = []
    in_proposals = in_feedback = False
    for line in text.splitlines():
        if "### Proposals we sent" in line:
            in_proposals = True
            in_feedback = False
            continue
        if "### Their feedback (snippets)" in line:
            in_feedback = True
            in_proposals = False
            continue
        if in_proposals and line.strip().startswith("- **") and ":" in line:
            summary_parts.append("Proposal: " + line.strip()[:120])
        if in_feedback and line.strip().startswith("- [") and "]" in line:
            summary_parts.append("Them: " + line.strip()[:120])
    summary = "\n".join(summary_parts[:8]) if summary_parts else "(no proposals/feedback parsed)"
    return total, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Deep scan leads: Mem0, Neo4j, Qdrant, Alexandros, email, web.")
    parser.add_argument("--input", "-i", type=Path, default=PROJECT_ROOT / "data" / "reports" / "top50_good_leads.csv",
                        help="Input CSV: email, name, company, source (from top50 script).")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Max leads to scan (default 5).")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output Markdown report path (default: data/reports/deep_scan_leads_<timestamp>.md).")
    parser.add_argument("--no-web", action="store_true", help="Skip web search (faster).")
    args = parser.parse_args()

    if not httpx:
        print("Install httpx: poetry add httpx", file=sys.stderr)
        sys.exit(1)

    leads = load_leads_from_csv(args.input, args.limit)
    if not leads:
        print(f"No leads in {args.input}. Run top50 script first:", file=sys.stderr)
        print("  CSV should be from: .../top50_hot_leads_excluding_customers.py --output data/reports/top50_good_leads.csv", file=sys.stderr)
        print("  poetry run python scripts/top50_hot_leads_excluding_customers.py --output data/reports/top50_good_leads.csv", file=sys.stderr)
        sys.exit(1)

    out_path = args.output or (PROJECT_ROOT / "data" / "reports" / f"deep_scan_leads_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = PROJECT_ROOT / "data" / "reports" / "deep_scan_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    print(f"Deep scan: {len(leads)} leads. Can take 2–5 min per lead (CRM, Mem0, email, Gmail history, Alexandros, KB, Iris).", flush=True)
    print("", flush=True)

    print("  Fetching CRM deals...", end=" ", flush=True)
    all_deals = fetch_all_deals(limit=500)
    print(f"done ({len(all_deals)} deals)", flush=True)

    report_lines = [
        "# Deep scan: leads (CRM, Mem0, Neo4j, Qdrant, Alexandros, email, web)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Leads scanned: {len(leads)}",
        "",
        "---",
        "",
    ]

    for i, lead in enumerate(leads, 1):
        email = (lead.get("email") or "").strip().lower()
        name = (lead.get("name") or "").strip() or "—"
        company = (lead.get("company") or "").strip() or "—"
        source = (lead.get("source") or "").strip()
        genuine = lead.get("genuine_replies", "")
        from_them = lead.get("emails_from_them", "")

        print(f"[{i}/{len(leads)}] Scanning: {company[:35]} ({email})...", flush=True)

        report_lines.append(f"## {i}. {company} — {name} ({email})")
        report_lines.append("")
        report_lines.append(f"- **Source:** {source} | Genuine replies: {genuine} | Emails from them: {from_them}")
        report_lines.append("")

        # 1. Mem0 (contact + global: customer facts like "DEZET took K2025 PF1" are often under user_id=global)
        print("  Mem0...", end=" ", flush=True)
        report_lines.append("### Mem0 (long-term memory)")
        memories = recall_memory_for_lead(company, email, limit_per_id=5)
        print(f"done ({len(memories)} memories)", flush=True)
        if memories:
            for m in memories:
                report_lines.append(f"- {m[:400]}{'…' if len(m) > 400 else ''}")
        else:
            report_lines.append("- (none)")
        report_lines.append("")

        # 1b. CRM customer/deal (so DEZET, Joplast, Naffco show as customers with machine/deal)
        print("  CRM...", end=" ", flush=True)
        report_lines.append("### Customer / deal (CRM)")
        contact_deals = get_deals_for_contact(email, all_deals)
        report_lines.append(format_crm_section(contact_deals))
        report_lines.append("")
        print(f"done ({len(contact_deals)} deal(s))", flush=True)

        # 2. Email interaction
        print("  Email search...", end=" ", flush=True)
        report_lines.append("### Email (double-check + relationship summary)")
        es = email_search(email, max_results=30)
        print("done", flush=True)
        count = es.get("count", len(es.get("emails", [])))
        report_lines.append(f"- **Gmail: {count} email(s) from them.**")
        if es.get("emails"):
            for e in es.get("emails", [])[:5]:
                subj = (e.get("subject") or "")[:60]
                date = (e.get("date") or "")[:10]
                report_lines.append(f"  - {date} | {subj}")
        # Full history and summary
        print("  pull_contact_email_history...", end=" ", flush=True)
        history_path = scratch_dir / f"history_{email.replace('@', '_').replace('.', '_')}.md"
        thread_count, rel_summary = pull_contact_email_history(email, history_path)
        print(f"done ({thread_count} threads)", flush=True)
        report_lines.append(f"- **pull_contact_email_history:** {thread_count} thread(s).")
        report_lines.append("")
        report_lines.append("**Relationship summary:**")
        report_lines.append(rel_summary if rel_summary else "(no threads or parse failed)")
        report_lines.append("")

        # 3a. Alexandros (document archive / gatekeeper)
        print("  Alexandros...", end=" ", flush=True)
        report_lines.append("### Alexandros (document archive)")
        alex_query = (
            f"Search the document archive for anything mentioning company '{company}' or contact '{email}'. "
            f"List file names and a one-line summary of what each contains. If nothing found, say so."
        )
        alex_answer = ask_agent("alexandros", alex_query)
        print("done", flush=True)
        report_lines.append(alex_answer[:1500] + ("…" if len(alex_answer) > 1500 else ""))
        report_lines.append("")

        # 3b. KB + Neo4j (unified retriever via pipeline)
        print("  KB (Qdrant + Neo4j)...", end=" ", flush=True)
        report_lines.append("### Knowledge base (Qdrant + Neo4j)")
        kb_query = (
            f"From the knowledge base and graph only: what do we know about company '{company}' and contact '{email}'? "
            f"List any quotes, machines, deals, interactions. If nothing found, say so."
        )
        kb_answer = ira_query(kb_query)
        print("done", flush=True)
        report_lines.append(kb_answer[:2000] + ("…" if len(kb_answer) > 2000 else ""))
        report_lines.append("")

        # 4. Web (Iris / web scraper)
        if not args.no_web:
            print("  Iris (web)...", end=" ", flush=True)
            report_lines.append("### Web (Iris) — company intel for next-step email")
            web_query = (
                f"Use web search to find information about company '{company}': what they do, industry, "
                f"and any recent news. Summarize in one short paragraph for a sales follow-up email."
            )
            web_answer = ask_agent("iris", web_query)
            print("done", flush=True)
            report_lines.append(web_answer[:1500] + ("…" if len(web_answer) > 1500 else ""))
        else:
            report_lines.append("### Web — (skipped, use --no-web to skip)")
        report_lines.append("")

        report_lines.append("### Suggested next step")
        report_lines.append("- *(Draft next email using: relationship summary above, proposals sent, their feedback, and web intel.)*")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Wrote report: {out_path}")
    print(f"Scanned {len(leads)} leads.")


if __name__ == "__main__":
    main()
