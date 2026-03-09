"""
IRA Skills as OpenAI-Compatible Tools (P2 Remediation)

Exposes research_skill, writing_skill, fact_checking_skill as function-calling tools.
Enables LLM-driven orchestration: Athena (LLM) chooses which skills to call and in what order.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ira.tools.skills")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))


def _read_dream_summary() -> str:
    """Read the most recent dream journal and nap results as a grounded summary."""
    from pathlib import Path
    root = Path(_PROJECT_ROOT)
    lines = []

    # 1. Latest nap result JSON (authoritative structured data)
    results_dir = root / "data" / "dream_results"
    nap_files = sorted(results_dir.glob("nap_*.json"), reverse=True) if results_dir.exists() else []
    if nap_files:
        try:
            data = json.loads(nap_files[0].read_text())
            lines.append(f"LAST NAP: {data.get('started', '?')} (duration: {data.get('duration', '?')})")
            phases = data.get("phases", {})

            nem = phases.get("nemesis", {})
            if nem:
                lines.append(f"Nemesis: {nem.get('corrections_processed', 0)} corrections applied, "
                             f"{nem.get('truth_hints_added', 0)} new truth hints, "
                             f"{nem.get('mem0_reinforced', 0)} memories reinforced")

            dream = phases.get("dream", {})
            if dream:
                lines.append(f"Dream: {dream.get('docs', 0)} documents processed, "
                             f"{dream.get('facts', 0)} facts extracted and indexed")

            ep = phases.get("episodic", {})
            if ep:
                lines.append(f"Episodic: {ep.get('patterns', 0)} patterns, "
                             f"{ep.get('memories_created', 0)} memories created")

            gr = phases.get("graph", {})
            if gr:
                lines.append(f"Graph: {gr.get('edges_strengthened', 0)} strengthened, "
                             f"{gr.get('edges_created', 0)} new, "
                             f"{gr.get('edges_weakened', 0)} weakened")

            kd = phases.get("knowledge_decay", {})
            if kd:
                lines.append(f"Knowledge decay: {kd.get('decayed', 0)} decayed, "
                             f"{kd.get('active_patterns', 0)} active (avg conf {kd.get('avg_confidence', 0):.2f})")

            orch = phases.get("orchestrated", {})
            if orch:
                lines.append(f"Deep dream: self-test {orch.get('self_test', '?')}, "
                             f"calibration {orch.get('calibration', '?')}")

            drip = phases.get("drip", {})
            if drip:
                lines.append(f"Drip reflection: {drip.get('ideas', 0)} new ideas")

            errors = data.get("errors", [])
            if errors:
                lines.append(f"Issues: {', '.join(errors[:3])}")
        except Exception as e:
            lines.append(f"(Error reading nap results: {e})")

    # 2. Dream journal entries (human-readable facts)
    journal_file = root / "data" / "dream_journal.json"
    if journal_file.exists():
        try:
            entries = json.loads(journal_file.read_text())
            if isinstance(entries, list) and entries:
                latest = entries[-1]
                facts = latest.get("facts_learned", [])
                if facts:
                    lines.append(f"\nFACTS FROM DREAM JOURNAL ({latest.get('date', '?')}):")
                    for f in facts[:15]:
                        fact_text = f if isinstance(f, str) else str(f)
                        lines.append(f"  - {fact_text[:200]}")
                    if len(facts) > 15:
                        lines.append(f"  ... and {len(facts) - 15} more")

                patterns = latest.get("patterns_discovered", [])
                if patterns:
                    lines.append("PATTERNS:")
                    for p in patterns[:5]:
                        lines.append(f"  - {p if isinstance(p, str) else str(p)[:200]}")

                st = latest.get("self_test_results", {})
                if st:
                    lines.append(f"Self-test: {st.get('score', '?')}/{st.get('total', '?')} "
                                 f"({st.get('percentage', 0):.0%})")
        except Exception as e:
            lines.append(f"(Error reading dream journal: {e})")

    if not lines:
        return "(No dream results found. The nap/dream cycle may not have run recently.)"

    lines.insert(0, "DREAM SUMMARY (authoritative source — do NOT embellish or invent additional facts):")
    return "\n".join(lines)


IRA_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "research_skill",
            "description": "Search Machinecraft's knowledge base (Qdrant, Mem0, Neo4j, machine database). Use for product specs, customer history, order data, pricing, and any internal knowledge. Optional: synthesis_mode 'multi_doc' for per-document sections; citation_only true for structured citations only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or topic to research"},
                    "synthesis_mode": {"type": "string", "description": "Optional: 'narrative' (default) or 'multi_doc' for distinct sections per document"},
                    "citation_only": {"type": "boolean", "description": "Optional: if true, return only structured citations (source, snippet, relevance) for Athena/Vera to cite"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for external information. Use for company research, industry news, competitor analysis, market trends, or any information not in our internal knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "company": {"type": "string", "description": "Company name if researching a specific company"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_lookup",
            "description": "Ask Mnemosyne (CRM agent) to look up a customer, lead, or company. Returns full relationship brief: contact details, email history, deal stage, conversation summary, and Mnemosyne's recommendation for next action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name, company name, or email to look up"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_list_customers",
            "description": "List CONFIRMED Machinecraft customers — companies that actually BOUGHT machines. Pulls from order history (2014-2025), NOT from leads or prospects. Use when asked for 'customers', 'customer list', 'who bought machines', 'latest customers', or 'how many customers'. Do NOT use this for leads/prospects — use crm_pipeline for that.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_pipeline",
            "description": "Ask Mnemosyne for a full sales pipeline overview: leads by stage, by priority, reply rates, drip status, PLUS a list of all active leads (negotiating/proposal/qualified) with company names, countries, machines, and status notes. Use when asked about pipeline health, sales performance, 'latest leads', 'who are we quoting', or 'active deals'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_drip_candidates",
            "description": "Ask Mnemosyne which leads are ready for the next drip email. Returns a prioritized list with her recommendations for each lead.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_outreach",
            "description": "Hermes: Get a preview of the next outreach batch — drafts only, no emails sent. Returns list of up to 5 draft emails (to, company, subject, body snippet) for Rushabh to review. Use when user asks 'who should we email?', 'preview drip emails', 'show me the next batch'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sales_outreach",
            "description": "Hermes: Run the outreach batch — either preview (dry_run=True) or actually send (dry_run=False). When dry_run=True, returns same as preview_outreach. When dry_run=False, sends emails with rate limiting and updates CRM; use only after user explicitly approves. Default is dry_run=True for safety.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "If true (default), only preview drafts; if false, send the batch. Set to false only when user has approved sending."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_overview",
            "description": "Ask Plutus (Chief of Finance) any financial question. Returns a pre-formatted CFO report with KPIs, visual bars, risk register, and recommendations. IMPORTANT: relay the output VERBATIM to the user without summarizing or reformatting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The financial question to answer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "order_book_status",
            "description": "Ask Plutus for the current order book with per-project breakdown. Returns pre-formatted report. RELAY VERBATIM to user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cashflow_forecast",
            "description": "Ask Plutus for week-by-week cashflow projections from payment schedule. Returns pre-formatted report. RELAY VERBATIM to user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revenue_history",
            "description": "Ask Plutus for historical revenue by year and export breakdown. Returns pre-formatted report. RELAY VERBATIM to user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Specific revenue question or period (e.g. 'FY2024', 'last 5 years', 'export revenue')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "net_cashflow",
            "description": "Ask Plutus for a combined inflows + outflows cashflow projection. Shows customer receivables (inflows) alongside vendor payables (outflows) week-by-week, with net position and running balance. Use when asked 'net cashflow', 'inflows vs outflows', 'combined cashflow', 'what is our cash position after paying vendors?'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cash_position",
            "description": "Ask Plutus for a quick cash position snapshot — bank balance, receivables (next 30 days), payables (overdue + due), and net position. Use when asked 'how much cash do we have?', 'cash position', 'bank balance', 'liquidity'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "payment_plan",
            "description": "Ask Plutus for a smart vendor payment plan — ranks vendors by priority (production-critical, aging, relationship, amount) and recommends which to pay now, this month, or defer. Use when asked 'which vendors to pay?', 'payment plan', 'vendor payment priority', 'who should we pay first?'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_summary",
            "description": "Ask Atlas (Project Manager) for a full summary of a specific project/order. Returns machine details, payment status, production stage, documents on file, and key excerpts. Use when asked about a specific customer order or project status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name, project number (e.g. '26002'), or description (e.g. 'Customer-F')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "all_projects_overview",
            "description": "Ask Atlas for a dashboard of ALL active projects — grouped by status (active, stalled, pending payment, completed) with document counts and dispatch dates. RELAY VERBATIM to user.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_documents",
            "description": "Ask Atlas to list and categorize all documents for a specific project (POs, quotes, invoices, specs, floor plans). Returns file names, sizes, categories, and previews.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name or project number"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "risk_register",
            "description": "Ask Atlas for the morning briefing — what needs attention RIGHT NOW. Flags overdue dispatches, stalled projects, payment gaps, customer contact gaps, factory report delays. Use when asked 'what needs my attention?', 'any risks?', 'morning briefing'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "payment_alerts",
            "description": "Ask Atlas for the payment dashboard — order book financials, collection rates per project, blocked projects, critical payment gaps, upcoming milestones. Use when asked about payments, collections, outstanding amounts, who owes money. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "milestone_alerts",
            "description": "Atlas: Overdue and upcoming (next 14 days) milestones — dispatch dates and payment due. Use when user asks 'what milestones are overdue', 'upcoming deadlines', 'what is due soon'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "production_schedule",
            "description": "Ask Atlas for the production schedule from Sandeep — Gantt chart with plan vs actual dates per department (Mechanical, Pneumatic, Electrical), detailed stage-by-stage status, pending items, and blockers. Use when asked about production timeline, factory schedule, what's being built, manufacturing status, Sandeep's report, or 'where is [project] in production?'. Pass a project name/number for a specific project, or leave empty for the full overview. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Project name, number (e.g. '25006'), or customer name. Leave empty for full production overview."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vendor_status",
            "description": "Ask Hera (Vendor/Procurement Manager) for the vendor dashboard — vendor count, top vendors by PO volume, component categories, data collection status from Ketan. Use when asked about vendors, suppliers, procurement, or 'who supplies our PLCs?'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vendor_lead_time",
            "description": "Ask Hera for lead time and vendor info for a specific component. Use when asked 'how long does a PLC take?', 'who supplies servo motors?', 'Festo lead time', or any vendor/component question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Component name, vendor name, or category (e.g. 'Mitsubishi PLC', 'Festo pneumatic', 'heater elements', 'Electrical')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vendor_outstanding",
            "description": "Ask Hera for vendor outstanding/payable data from the Tally ledger. Shows how much Machinecraft owes each vendor. No query = full dashboard with all vendors ranked by pending amount. With query = filter by vendor name. Use when asked 'vendor outstanding', 'how much do we owe Festo?', 'vendor payables', 'creditor balance', 'outstanding payments'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional vendor name to filter (e.g. 'Festo', 'Mitsubishi', 'Vimal'). Leave empty for full dashboard."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vendor_reliability",
            "description": "Ask Hera for vendor delivery reliability — on-time % per vendor from PO history (expected vs actual delivery). Use when asked 'which vendors deliver on time?', 'vendor reliability', 'delivery performance'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "employee_lookup",
            "description": "Ask Themis (HR) to find employees by name or designation. Uses 2026 SALARY SHEET. Returns matching employees with designation and monthly gross. Use when asked 'who is X?', 'employees in Purchase', 'designation of Y', 'who works in production?'. Internal use only. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name (e.g. 'Ketan') or designation (e.g. 'Design Engineer', 'Purchase', 'Manager') to search."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hr_dashboard",
            "description": "Ask Themis (HR) for the HR dashboard — headcount, total monthly payroll, breakdown by designation. Data from 2026 SALARY SHEET. Use when asked 'how many employees?', 'headcount', 'payroll summary', 'HR overview', 'employees by department'. Internal use only. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hr_policies",
            "description": "Ask Themis for HR/leave policies. Returns content from data/themis/policies.md or data/config/themis_policies.json. Use when asked 'what is our leave policy?', 'HR policies', 'attendance policy'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_matrix",
            "description": "Ask Themis (HR) for the skill/role matrix of current employees — designations × names (who is in each role). From 2026 SALARY SHEET; sheet has DESIGNATION only, no separate skills columns. Use when asked 'skill matrix', 'employees by role', 'who does what', 'role matrix', 'export skill matrix'. Optional: set export_csv=true to write data/themis/skill_matrix.csv. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "export_csv": {"type": "boolean", "description": "If true, also write CSV to data/themis/skill_matrix.csv for Excel."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pipeline_forecast",
            "description": "Ask Tyche (Pipeline Forecaster) for pipeline analytics — win/loss analysis, deal velocity, conversion funnel, revenue forecast, engagement metrics. Use when asked about win rates, conversion rates, deal speed, pipeline health, revenue projections, or 'how is our pipeline doing?'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional focus: 'win/loss', 'velocity', 'funnel', 'forecast', 'engagement', or leave empty for full dashboard"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "win_loss_analysis",
            "description": "Ask Tyche for detailed win/loss breakdown — win rates by region and machine type, average deal sizes, lost reasons. Use when asked 'what is our win rate?', 'why are we losing deals?', 'which region converts best?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Optional country/region filter (e.g. 'Germany', 'India', 'Netherlands')"},
                    "machine_type": {"type": "string", "description": "Optional machine type filter (e.g. 'PF1', 'AM', 'IMG')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deal_velocity",
            "description": "Ask Tyche for deal velocity analysis — how long deals spend in each stage, bottleneck detection, average cycle time from new to won/lost. Use when asked 'how fast do deals close?', 'where do deals get stuck?', 'what is our sales cycle?'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_leads",
            "description": "Tyche: Scan sent emails from the past N days and classify each as lead vs prospect. A LEAD is a real sales conversation (they contacted us or we had a call and sent a tailored proposal). A PROSPECT is outreach campaign with no reply yet. Use when asked 'separate leads from prospects', 'classify our sent emails', 'lead vs prospect report'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look back (default 30)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "craft_email_for_lead",
            "description": "Hermes: Draft one personalized outreach email for a specific lead by lead_id (e.g. eu-012). Uses CRM + Iris + case studies. Returns draft only — does NOT send. Use when user says 'draft email for lead X', 'write follow-up for [company]', 'craft email for lead_id'. Call crm_drip_candidates first to get lead_ids if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string", "description": "Lead identifier (e.g. eu-012 from crm_drip_candidates or European campaign)"},
                },
                "required": ["lead_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_export_leads",
            "description": "Mnemosyne: Export leads (and optionally contacts) from CRM to JSON or CSV format for download or analysis. Use when asked 'export leads', 'download CRM', 'export pipeline to CSV', 'backup leads'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "description": "Output format: 'json' or 'csv' (default json)"},
                    "include_contacts": {"type": "boolean", "description": "If true, include contact details; default false (leads only)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discovery_sweep",
            "description": "Prometheus: Run a full discovery sweep across tracked industries (battery, EV, drones, medical, etc.) and return scored opportunities. Use when asked 'full market scan', 'discovery sweep', 'what new industries should we target?', 'run Prometheus sweep'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "industries": {"type": "string", "description": "Optional comma-separated list to limit sweep (e.g. 'battery, EV, drones'). Leave empty for all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_leads_from_discovery",
            "description": "Create CRM leads from the latest Prometheus discovery sweep. Use after discovery_sweep when user wants to add top opportunities to the pipeline. Leads get placeholder emails (discovery-*@placeholder.machinecraft.org); update with real contacts when ready.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_leads": {"type": "integer", "description": "Max number of leads to create from top opportunities (default 10)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "meeting_notes_to_actions",
            "description": "Extract action items from meeting notes. Returns a numbered list of actions with optional owner and due date. Use when user pastes meeting notes or asks to turn meeting notes into tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meeting_notes": {"type": "string", "description": "Raw meeting notes or transcript text."},
                },
                "required": ["meeting_notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "List open tasks from the minimal task store. Filter by status (open/done/all) or assignee.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "open, done, or all. Default open."},
                    "assignee": {"type": "string", "description": "Filter by assignee name."},
                    "limit": {"type": "integer", "description": "Max tasks to return (default 30)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_create",
            "description": "Create a task in the task store. Use for follow-ups, action items, or reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title."},
                    "assignee": {"type": "string", "description": "Optional assignee."},
                    "due": {"type": "string", "description": "Optional due date (e.g. 2026-03-15)."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Mark a task as done in the task store. Use when user says they completed a task or to close an action item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID (from task_list)."},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pipeline_digest",
            "description": "Get a short pipeline digest (win rate, active deals, bottleneck, top regions). Use for weekly summary or 'pipeline digest'. Optionally send to Telegram if chat_id provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "send_to_telegram": {"type": "boolean", "description": "If true and Telegram configured, send digest to Telegram. Default false (return text only)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_next_touch",
            "description": "Suggest next contact date for a lead based on last email sent and drip interval. Use after sending an email or when planning follow-up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_email": {"type": "string", "description": "Lead email address."},
                },
                "required": ["lead_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_quote_to_lead",
            "description": "Link a quote (quote_id) to a CRM lead. Updates the lead's notes with the quote reference so deal and quote are connected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string", "description": "Quote ID (e.g. from build_quote_pdf result)."},
                    "lead_email": {"type": "string", "description": "Lead/contact email in CRM."},
                },
                "required": ["quote_id", "lead_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "punch_list",
            "description": "Ask Asclepius (Quality Tracker) for the punch-list of a specific project or customer. Returns all open/closed items with severity, status, and assigned person. Use when asked about quality issues, open items, FAT status, installation snags, or 'what's still open on [customer]?'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name or project number (e.g. 'Customer-E', 'Customer-F', 'MCT-2026-001')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_punch_item",
            "description": "Ask Asclepius to log a new quality issue on a customer's punch-list. Use when Rushabh reports a new defect, snag, or open item during FAT or installation. Auto-creates the punch-list if none exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name (e.g. 'Customer-E', 'Customer-F')"},
                    "description": {"type": "string", "description": "What the issue is (e.g. 'Trimming blade alignment off 2mm')"},
                    "category": {"type": "string", "description": "Issue category: mechanical, electrical, software, cosmetic, safety, documentation, performance"},
                    "severity": {"type": "string", "description": "Severity: critical, major, minor, observation"},
                    "assigned_to": {"type": "string", "description": "Person responsible for fixing (e.g. 'Ketan', 'Sachin')"},
                    "phase": {"type": "string", "description": "Phase: fat or installation (defaults to fat)"},
                },
                "required": ["customer", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_punch_item",
            "description": "Ask Asclepius to close/resolve a punch-list item. Use when told an issue is fixed, resolved, or done. Auto-closes the punch-list if all critical/major items are resolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name"},
                    "item_description": {"type": "string", "description": "Item number or description to match (e.g. '1', 'trimming blade')"},
                    "resolution_notes": {"type": "string", "description": "How it was fixed (optional)"},
                },
                "required": ["customer", "item_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quality_dashboard",
            "description": "Ask Asclepius for the quality dashboard — all open punch-list items across all projects, aging items, critical blockers. Use when asked 'what quality issues are open?', 'morning quality briefing', or 'punch-list overview'. RELAY VERBATIM.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recurring_quality_patterns",
            "description": "Asclepius: Recurring punch-list patterns by category (e.g. mechanical: trimming blade 3x). Optionally feed patterns to Nemesis for learning. Use when asked 'recurring quality issues', 'quality patterns', 'what keeps coming up on punch-lists?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "feed_to_nemesis": {"type": "boolean", "description": "If true, send recurring patterns (2+ occurrences) to Nemesis for learning."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "actuals_vs_targets",
            "description": "Plutus: Compare order book and collection rate to configured targets. Targets in data/config/finance_targets.json. Use when asked 'actuals vs targets', 'are we on target', 'target vs actual', 'order book target'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_alerts",
            "description": "Plutus: Return budget alert messages when order book, collection rate, or revenue fall below thresholds in finance_targets.json alerts. Use when user asks 'any budget alerts?', 'finance alerts', or 'are we below target'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_export",
            "description": "Plutus: Export order book summary as CSV or JSON for paste into spreadsheet or download. Use when asked 'export finance', 'download order book', 'export to spreadsheet', 'finance CSV'.",
            "parameters": {
                "type": "object",
                "properties": {"format": {"type": "string", "description": "csv or json (default csv)"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_project_status_email",
            "description": "Atlas: Draft a short customer-facing project status email. Pass customer name or project number. Use when asked 'draft status email for [customer]', 'project status email', 'customer update email'.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Customer name or project number"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_content_topics",
            "description": "Cadmus/Iris: Get suggested content topics from current industry/news trends for LinkedIn or newsletter. Use when asked 'content ideas', 'what should we post', 'topic suggestions', 'newsletter topics'.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Optional focus e.g. thermoforming, manufacturing, EV"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "po_draft",
            "description": "Hera: Generate draft PO text from vendor name and line items (description, qty, unit, price). Use when asked 'draft a PO', 'PO for vendor', 'purchase order draft'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string", "description": "Vendor/supplier name"},
                    "line_items": {"type": "string", "description": "Line items as text e.g. 'Item A, 10 pcs, ₹1000; Item B, 5 pcs, ₹500' or JSON array"},
                },
                "required": ["vendor_name", "line_items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "machine_knowledge",
            "description": "Ask Atlas for technical knowledge about Machinecraft machines — operation, maintenance, troubleshooting, specs, components, safety. Atlas has studied the full manuals for PF1, AM, FCS, and IMG series. Use for after-sales support questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Technical question (e.g. 'PF1 heating system zones', 'AM servo battery replacement', 'FCS cycle time', 'how to troubleshoot machine tripping')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_logbook",
            "description": "Ask Atlas for the full CRM-style logbook of a project — contacts, payment history, email timeline, milestones, and upcoming dues. Shared with finance and sales teams. RELAY VERBATIM to user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name or project number"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search Ira's long-term memory (Mem0) for stored facts, preferences, past conversations, and ingested data about customers, orders, or Machinecraft operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in memory"},
                    "user_id": {"type": "string", "description": "Optional: specific user/category to search (e.g. 'machinecraft_customers', 'machinecraft_knowledge')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "writing_skill",
            "description": "Draft a response, email, or document based on research findings. Use after gathering information with other tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The original user query"},
                    "research_summary": {"type": "string", "description": "All research findings to base the draft on"},
                },
                "required": ["query", "research_summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fact_checking_skill",
            "description": "Verify a draft for accuracy against the machine database, AM series thickness rules, and pricing disclaimers. Always use before finalizing a response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft": {"type": "string", "description": "The draft response to verify"},
                    "original_query": {"type": "string", "description": "The original user question"},
                },
                "required": ["draft", "original_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_spreadsheet",
            "description": "Read data from a Google Sheet. Use for order books, pricing lists, lead lists, or any tabular data stored in Google Sheets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "spreadsheet_id": {"type": "string", "description": "The spreadsheet ID from the Google Sheets URL (the long string between /d/ and /edit)"},
                    "range": {"type": "string", "description": "Sheet name and cell range, e.g. 'Sheet1!A1:Z100' or just 'Sheet1'"},
                },
                "required": ["spreadsheet_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_drive",
            "description": "Search Google Drive for files by name or content. Use when asked to find documents, presentations, spreadsheets, or PDFs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (file name, keywords, or content to find)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_calendar",
            "description": "Check upcoming calendar events. Use for scheduling questions, meeting lookups, or availability checks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look ahead (default 7)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_contacts",
            "description": "Search Google Contacts for a person, company, or email address. Returns names, emails, phone numbers, and organizations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name, company, or email to search for"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_inbox",
            "description": "Read Rushabh's Gmail inbox. Returns recent or unread emails with sender, subject, date, and preview. Use when asked about new emails, unread messages, or 'what's in my inbox'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Number of emails to fetch (default 10, max 20)"},
                    "unread_only": {"type": "boolean", "description": "If true, only return unread emails (default true)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_email",
            "description": "Search the founder's Gmail. IMPORTANT: Start with simple keyword searches like 'customer name quote'. Plain keywords work best and match Gmail's natural search. Only use advanced syntax (from:, subject:, after:) if a simple search returns too many results. If the first search returns nothing, try broader keywords before giving up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — use plain keywords first (e.g. 'customer name AM-P'), add Gmail operators only to narrow down"},
                    "max_results": {"type": "integer", "description": "Max results to return (default 10, max 20)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_email_message",
            "description": "Read the full content of a specific email by its message ID. Use after read_inbox or search_email to get the complete email body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The Gmail message ID (from read_inbox or search_email results)"},
                },
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_email_thread",
            "description": "Read a full email conversation thread. Use to see the complete back-and-forth in a conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "The Gmail thread ID"},
                    "max_messages": {"type": "integer", "description": "Max messages to include (default 10)"},
                },
                "required": ["thread_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "ACTUALLY SEND an email from Rushabh's Gmail. Call this after the user approves a draft. Supports HTML for rich formatting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Email body (plain text fallback)"},
                    "body_html": {"type": "string", "description": "Optional: HTML-formatted email body. Use <h2>, <strong>, <ul>, <table> for professional formatting. If provided, recipient sees this; plain text body is the fallback."},
                    "thread_id": {"type": "string", "description": "Optional: thread ID to reply in an existing conversation"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_email",
            "description": "Draft an email using Ira's voice, auto-enriched with real data from CRM, knowledge base, Google Contacts, and Mem0. Returns a draft for review — does NOT send. IMPORTANT: Before calling this, you SHOULD call customer_lookup and/or search_contacts to resolve the recipient's email address if you only have a name. Also call research_skill to gather relevant product/company data, then pass those results as 'context'. The tool also does its own enrichment, but explicit context from prior tool calls produces much better drafts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address (or name if email unknown — tool will try to resolve via Google Contacts)"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "intent": {"type": "string", "description": "What the email should convey (e.g. 'follow up on PF1 quote', 'introduce Machinecraft')"},
                    "context": {"type": "string", "description": "IMPORTANT: Pass results from prior tool calls here (customer_lookup, research_skill, search_contacts results). This grounds the email in real data instead of hallucinating."},
                },
                "required": ["to", "subject", "intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lead_intelligence",
            "description": "Ask Iris (intelligence agent) to gather deep company intelligence: recent news, expansions, acquisitions, industry trends, geopolitical context, and website analysis. Use when researching a specific company before outreach, or when you need real-time external context about a prospect or customer. Returns structured intelligence hooks for sales conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name to research (e.g. 'Acme Corp', 'Example GmbH', 'Sample Industries')"},
                    "context": {"type": "string", "description": "Additional context about why you're researching this company (e.g. 'preparing outreach for PF1-X quote', 'follow-up on trade show meeting')"},
                },
                "required": ["company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "latest_news",
            "description": "Search for the latest real-world news on any topic, company, industry, or region via NewsData.io. Use for ice-breakers in sales emails (e.g. 'congratulations on your expansion'), industry trend hooks, or when you need current events context. Complements lead_intelligence — use lead_intelligence for deep company dossiers, use latest_news for fresh headline-level news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "News search query (e.g. 'thermoforming industry', 'EV battery manufacturing Germany', 'packaging company expansion')"},
                    "country": {"type": "string", "description": "2-letter country code to filter news (e.g. 'de' for Germany, 'nl' for Netherlands, 'in' for India). Leave empty for global."},
                    "category": {"type": "string", "description": "News category filter: business, technology, science, world, environment, politics. Comma-separated for multiple. Leave empty for default business+technology+science."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_website",
            "description": "Scrape a company's actual website to understand what they do, their products, and their capabilities. Uses Tavily with domain filtering to read ONLY pages from the company's own website — this is ground truth, more reliable than generic web search which can match the wrong entity. Use when you need to know what a company actually makes before recommending machines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Company website domain (e.g. 'example-company.com', 'sample-mfg.de'). Can also extract from email — just pass the part after @."},
                    "company": {"type": "string", "description": "Company name for context in the search query"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "discovery_scan",
            "description": "Ask Prometheus (the market discovery agent) to find new products and industries where vacuum forming can be applied. Scans emerging sectors like battery storage, EV, drones, renewable energy, medical devices, modular construction. Can scan a specific industry, evaluate a product idea, or run a full sweep across all tracked industries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Industry to scan (e.g. 'battery storage', 'drone manufacturing'), product idea to evaluate (e.g. 'EV battery enclosures'), or 'sweep' for full multi-industry scan"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_analysis",
            "description": "Ask Hephaestus (the program builder) to forge and execute a Python program. Use when you need to compute, aggregate, count, rank, filter, or transform data from previous tool calls. You can either describe the TASK in plain English (Hephaestus writes the code) OR provide the code directly. Pass data from previous tool calls via the 'data' parameter. The script runs in a sandboxed subprocess with a 60s timeout. If the first attempt fails, Hephaestus auto-retries with a fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Natural-language description of what to compute (e.g. 'group emails by sender domain, count per company, rank top 10'). Hephaestus will write the code."},
                    "code": {"type": "string", "description": "Pre-written Python code to execute directly. Use print() to output results. If both task and code are provided, code takes priority."},
                    "data": {"type": "string", "description": "Data from previous tool calls to make available as the variable DATA in the script"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a clarifying question when you need more information to complete a task. Use this instead of guessing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The clarifying question to ask the user"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correction_report",
            "description": "Ask Nemesis (the correction-hungry learning agent) for a report on logged mistakes and pending corrections. Use when the user asks 'what mistakes have you made?', 'show correction report', 'what have you learned from corrections?', or 'Nemesis report'. Returns total corrections, unapplied count, repeat offenders, and (optionally) recent pending corrections with source and confidence [0-1].",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_pending": {"type": "boolean", "description": "Include pending (unapplied) corrections list. Default true."},
                    "limit_pending": {"type": "integer", "description": "Max pending items to show (default 10)."},
                    "sort_by_confidence": {"type": "boolean", "description": "Sort pending by confidence (highest first). Default false."},
                    "min_confidence": {"type": "number", "description": "Only show pending corrections with confidence >= this (0.0-1.0). Omit for all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dream_summary",
            "description": "Read Ira's dream journal — the authoritative record of what was learned during the last nap/dream cycle. Returns structured facts, patterns, and stats from the most recent dream. MUST be used when the user asks 'what did you learn last night?', 'facts from dream', 'dream report', 'what did you learn overnight'. Do NOT answer dream/learning questions from memory_search or research_skill alone — always call this tool first.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_quote_pdf",
            "description": "Ask Quotebuilder to build a detailed formal quotation (tech specs, terms, optional extras) and export it as a PDF for sending to the customer. Use when the user wants a formal quote document as an attachment (e.g. 'prepare a quote for PF1-C-2015 for Acme Corp', 'build a detailed quote and PDF'). Returns quote ID and path to the generated PDF file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width_mm": {"type": "integer", "description": "Forming area width in mm (e.g. 2000 for 2000mm)"},
                    "height_mm": {"type": "integer", "description": "Forming area height in mm (e.g. 1500 for 1500mm)"},
                    "variant": {"type": "string", "description": "Machine variant: C (pneumatic) or X (servo). Default C."},
                    "customer_name": {"type": "string", "description": "Customer contact name"},
                    "company_name": {"type": "string", "description": "Customer company name"},
                    "customer_email": {"type": "string", "description": "Customer email address"},
                    "country": {"type": "string", "description": "Country for pricing (India = GST; other = Ex-Works). Default India."},
                    "version": {"type": "string", "description": "Quote version (e.g. 1.0); included in filename and result. Default 1.0."},
                },
                "required": ["width_mm", "height_mm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_quote_pdf_multi",
            "description": "Build one PDF with multiple quote sections (one page per machine). Use when the user wants a single quote document for multiple machines (e.g. PF1-C-2015 + PF1-X-1208). line_items: JSON array of objects with width_mm, height_mm, and optional variant, customer_name, company_name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line_items": {"type": "array", "items": {"type": "object", "properties": {"width_mm": {"type": "integer"}, "height_mm": {"type": "integer"}, "variant": {"type": "string"}, "customer_name": {"type": "string"}, "company_name": {"type": "string"}}, "required": ["width_mm", "height_mm"]}, "description": "List of quote line items; each must have width_mm and height_mm."},
                    "customer_name": {"type": "string", "description": "Default customer name for all lines (overridable per line)."},
                    "company_name": {"type": "string", "description": "Default company name for all lines."},
                    "customer_email": {"type": "string", "description": "Default customer email."},
                    "country": {"type": "string", "description": "Country for pricing. Default India."},
                    "version": {"type": "string", "description": "Quote version in filename. Default 1.0."},
                },
                "required": ["line_items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_machine",
            "description": "Get a specific machine recommendation based on customer requirements. Returns exact model, price, reasoning, alternatives, and reference customers. ALWAYS call this before recommending a machine — it uses the full machine database and matches forming area to the correct model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "application": {"type": "string", "description": "What the customer is making (car mats, bathtubs, food trays, enclosures, etc.)"},
                    "material": {"type": "string", "description": "Plastic material (ABS, HDPE, PP, TPO, PET, PMMA, PC, etc.)"},
                    "thickness_mm": {"type": "number", "description": "Material thickness in mm (determines AM vs PF1 routing)"},
                    "sheet_width_mm": {"type": "integer", "description": "Sheet width in mm (determines model number)"},
                    "sheet_length_mm": {"type": "integer", "description": "Sheet length in mm (determines model number)"},
                    "depth_mm": {"type": "integer", "description": "Max draw depth in mm (optional)"},
                    "budget_inr": {"type": "integer", "description": "Customer budget in INR (0 if unknown — ask 'What is your budget? I can work reverse')"},
                    "needs_grain": {"type": "boolean", "description": "True if customer needs grain retention / Class-A surface / TPO texture"},
                    "needs_pressure": {"type": "boolean", "description": "True if customer needs pressure forming for high detail"},
                },
                "required": ["application", "material", "thickness_mm", "sheet_width_mm", "sheet_length_mm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rushabh_voice",
            "description": "Ask Echo (Rushabh's voice agent) how Rushabh would reply to this customer message. Returns a Rushabh-style draft based on his real email patterns. Use when drafting emails, outreach, or customer replies to match Rushabh's tone and style.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_message": {"type": "string", "description": "The customer's message to respond to"},
                    "company": {"type": "string", "description": "Customer company name (helps match per-customer style)"},
                    "context": {"type": "string", "description": "Conversation context or background"},
                },
                "required": ["customer_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_sales_training",
            "description": "Log a new sales strategy or pattern to Ira's sales training log. Use when Rushabh teaches you a new sales technique, when you observe a successful outreach pattern, or when a deal interaction reveals a reusable strategy. This is how you learn and remember sales approaches for future use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short name for the strategy (e.g. 'News-Driven Follow-Up for Stale Deals')"},
                    "trigger": {"type": "string", "description": "When to use this strategy (e.g. 'Hot deal with no reply for 5+ days')"},
                    "wrong_approach": {"type": "string", "description": "What NOT to do (e.g. 'Generic follow-ups like just checking in')"},
                    "right_approach": {"type": "string", "description": "Step-by-step correct approach"},
                    "example": {"type": "string", "description": "Real example from a deal (optional but valuable)"},
                    "tool_chain": {"type": "string", "description": "Which tools to use in sequence (optional)"},
                },
                "required": ["title", "trigger", "wrong_approach", "right_approach"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "training_effectiveness",
            "description": "Chiron: Summary of sales training effectiveness — pattern count from log, last 30d win rate and reply rate from CRM. Use when asked 'how effective is our sales training?', 'training metrics', 'Chiron effectiveness'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_email_subjects",
            "description": "Hermes A/B subject lines: get 3 subject line variants for a lead (one from draft + 2 alternatives). Use when user wants A/B test options or alternative subject lines for outreach.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string", "description": "Lead ID (same as craft_email_for_lead, e.g. eu-012)."},
                },
                "required": ["lead_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_next_training",
            "description": "Chiron: suggest sales training topics from recent lost deals (quote lost_reason + patterns). Use when user asks what to train on next or what we're losing on.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look back days for lost deals (default 90)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_librarian",
            "description": "Ask Alexandros (the Librarian) to find information in the internal document archive (data/imports/ — 636+ files). Use when research_skill or memory_search come up empty. Optional full_text_in_body: when true, filters candidates by query terms appearing in document body (slower but more precise).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you're looking for (e.g. 'Customer-C PO payment terms', 'PF1-3020 quote')"},
                    "full_text_in_body": {"type": "boolean", "description": "Optional: if true, only return documents whose extracted body text contains query terms (may be slower)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_archive",
            "description": "Browse the internal document archive — list files in a folder with summaries. Use when asked 'what documents do we have about X?' or 'show me the order files'. Alexandros returns a structured listing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "Folder name or keyword (e.g. '02_Orders_and_POs', 'quotes', 'presentations', 'contracts')"},
                    "doc_type": {"type": "string", "description": "Filter by document type: quote, order, catalogue, presentation, manual, contract, email, spreadsheet, report, lead_list, invoice, other"},
                },
                "required": ["folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_detail",
            "description": "Read a specific file from the internal document archive by name. Use when you already know which file you need (e.g. from browse_archive results or a previous search). Returns the full extracted text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "File name or partial name (e.g. 'Customer-D PO.pdf', 'MCT Orders 2025.xlsx', 'Customer-C MoM')"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_case_studies",
            "description": "Ask Cadmus (Chief Marketing Officer) to find relevant customer case studies. Returns documented success stories for use in emails, proposals, or conversations. Use when you need social proof, reference stories, or examples of Machinecraft's work in a specific industry/material/application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text search (e.g. 'bedliner', 'automotive HDPE', 'large machine Europe')"},
                    "industry": {"type": "string", "description": "Industry filter (e.g. 'automotive', 'packaging', 'sanitary')"},
                    "material": {"type": "string", "description": "Material filter (e.g. 'HDPE', 'ABS', 'PP', 'TPO')"},
                    "machine_type": {"type": "string", "description": "Machine series filter (e.g. 'PF1', 'PF2', 'IMG', 'AM')"},
                    "application": {"type": "string", "description": "Application filter (e.g. 'bedliner', 'bathtub', 'fridge liner')"},
                    "country": {"type": "string", "description": "Country filter (e.g. 'India', 'Germany', 'Netherlands')"},
                    "format": {"type": "string", "enum": ["one_liner", "paragraph", "full"], "description": "Output format: one_liner for email snippets, paragraph for proposals, full for complete case study"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_case_study",
            "description": "Ask Cadmus to build a new case study from existing project data. Cadmus synthesizes emails, project files, and specs into a structured, publishable case study. Use when Rushabh asks to document a customer project or create marketing material.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer name and project description (e.g. 'Customer-H automotive project for OEM partner')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_linkedin_post",
            "description": "Ask Cadmus to draft a LinkedIn post in Rushabh's voice. Can be based on a case study, a product launch, an event, or any topic. Cadmus writes in Rushabh's proven LinkedIn style — punchy hooks, concrete specs, India pride, CTAs. Use when Rushabh asks for a LinkedIn post or social media content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "What the post is about (e.g. 'automotive project case study', 'K2025 recap', 'new PF1-X-1210 launch')"},
                    "case_study_id": {"type": "string", "description": "Optional: ID of a published case study to base the post on (e.g. 'customer-automotive-project')"},
                    "post_type": {"type": "string", "enum": ["customer_story", "product_launch", "teaser", "announcement", "india_pride", "event", "personal_story"], "description": "Type of post to draft"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_linkedin_post_with_visuals",
            "description": "Ask Cadmus to draft a LinkedIn post WITH professional visuals generated by Manus AI. EXPENSIVE — uses Manus API credits. Creates carousel images, infographics, MBB-style slide decks, or hero images. Use ONLY when Rushabh explicitly asks for visuals/images/slides for a LinkedIn post.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "What the post is about"},
                    "case_study_id": {"type": "string", "description": "Optional: ID of a published case study to base the post on"},
                    "post_type": {"type": "string", "enum": ["customer_story", "product_launch", "teaser", "announcement", "india_pride", "event", "personal_story"], "description": "Type of post to draft"},
                    "visual_style": {"type": "string", "enum": ["carousel", "infographic", "slide_deck", "hero_image"], "description": "Type of visual: carousel (4-6 LinkedIn slides), infographic (single tall image), slide_deck (MBB-style PPTX), hero_image (single 1200x628 image)"},
                },
                "required": ["topic", "visual_style"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "content_calendar",
            "description": "Ask Arachne (content scheduler) to view or manage the content calendar — LinkedIn posts, newsletters, and their schedule. Use when asked 'what's scheduled this month?', 'schedule a LinkedIn post', 'what content is coming up?', or 'populate the content calendar'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["view", "schedule", "approve", "skip", "populate"], "description": "Action: view (show calendar), schedule (add item), approve/skip (by ID), populate (auto-fill LinkedIn slots)"},
                    "channel": {"type": "string", "description": "Filter by channel: 'linkedin' or 'newsletter'"},
                    "scheduled_date": {"type": "string", "description": "Date in YYYY-MM-DD format. For 'view': start date. For 'schedule': target date."},
                    "title": {"type": "string", "description": "Title/topic for the content item (required for 'schedule')"},
                    "content_ref": {"type": "string", "description": "Path to the content draft file (for 'schedule')"},
                    "item_id": {"type": "string", "description": "Calendar item ID (for 'approve' or 'skip')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assemble_newsletter",
            "description": "Ask Arachne to assemble the monthly newsletter from multiple sources (Atlas orders, Cadmus case studies, product spotlights, events, industry news). Use when asked 'prepare the newsletter', 'what goes in this month's newsletter?', or 'build the March newsletter'. By default shows a preview without sending.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Newsletter title. Defaults to 'Machinecraft Newsletter — <Month Year>'"},
                    "sections": {"type": "string", "description": "Comma-separated sections: new_orders, case_study, product_spotlight, event, industry_insight"},
                    "dry_run": {"type": "boolean", "description": "If true (default), assemble and preview without sending. Set false to actually send."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "distribution_status",
            "description": "Ask Arachne for content distribution status — what's been sent, what's pending approval, recent activity. Use when asked 'did the newsletter go out?', 'what's pending?', 'content distribution report'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Filter by channel: 'linkedin' or 'newsletter'. Leave empty for all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_draft",
            "description": "Verify a draft response for accuracy BEFORE sending to the user. Checks prices against machine_specs.json, AM series thickness rules, model numbers, business rules, and hallucination patterns. Call this when your response includes prices, specs, model recommendations, or customer-specific claims. If issues are found, you can fix them and re-verify.",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft": {"type": "string", "description": "The draft response text to verify"},
                    "query": {"type": "string", "description": "The original user question this draft answers"},
                },
                "required": ["draft", "query"],
            },
        },
    },
]


def get_ira_tools_schema() -> List[Dict[str, Any]]:
    """Return OpenAI-compatible tools list for chat.completions.create(tools=...)."""
    return IRA_TOOLS_SCHEMA


def _record_tool_metadata(
    context: Dict[str, Any], tool_name: str,
    source: str = "unknown", confidence: float = 0.5,
    entities: List[str] = None, citations: List[str] = None,
):
    """Record structured metadata about a tool result for downstream use.

    Vera and Sophia can read ``context["_tool_metadata"]`` to know which
    claims came from high-confidence vs low-confidence sources.
    """
    context.setdefault("_tool_metadata", []).append({
        "tool": tool_name,
        "source": source,
        "confidence": confidence,
        "entities": entities or [],
        "citations": citations or [],
    })


async def execute_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    context: Dict[str, Any],
) -> str:
    """Execute an IRA skill by name. Called when LLM returns tool_calls."""
    validation_err = _validate_tool_args(tool_name, arguments)
    if validation_err:
        logger.warning(f"[Security] Tool arg validation failed for {tool_name}: {validation_err}")
        return f"(Error: {validation_err})"

    try:
        from openclaw.agents.ira.src.skills.invocation import (
            invoke_research,
            invoke_verify,
            invoke_write,
        )
    except ImportError:
        return "Error: Skill invocation unavailable."

    # Notify progress callback if available
    progress_fn = context.get("_progress_callback")
    if progress_fn:
        try:
            progress_fn(tool_name)
        except Exception as e:
            logger.debug("Progress callback failed: %s", e)

    # Holistic: track agent invocation in endocrine system
    _tool_agent_map = {
        "research_skill": "clio",
        "writing_skill": "calliope",
        "fact_checking_skill": "vera",
        "web_search": "iris",
        "lead_intelligence": "iris",
        "customer_lookup": "mnemosyne",
        "crm_list_customers": "mnemosyne",
        "crm_pipeline": "mnemosyne",
        "crm_drip_candidates": "mnemosyne",
        "preview_outreach": "hermes",
        "sales_outreach": "hermes",
        "discovery_scan": "prometheus",
        "finance_overview": "plutus",
        "order_book_status": "plutus",
        "cashflow_forecast": "plutus",
        "revenue_history": "plutus",
        "read_inbox": "hermes",
        "search_email": "hermes",
        "read_email_message": "hermes",
        "read_email_thread": "hermes",
        "send_email": "hermes",
        "draft_email": "hermes",
        "run_analysis": "hephaestus",
        "correction_report": "nemesis",
        "log_sales_training": "chiron",
        "training_effectiveness": "chiron",
        "dream_summary": "athena",
        "build_quote_pdf": "quotebuilder",
        "recommend_machine": "athena",
        "rushabh_voice": "delphi",
        "project_summary": "atlas",
        "all_projects_overview": "atlas",
        "project_documents": "atlas",
        "ask_librarian": "alexandros",
        "browse_archive": "alexandros",
        "file_detail": "alexandros",
        "project_logbook": "atlas",
        "machine_knowledge": "atlas",
        "risk_register": "atlas",
        "payment_alerts": "atlas",
        "milestone_alerts": "atlas",
        "production_schedule": "atlas",
        "net_cashflow": "plutus",
        "cash_position": "plutus",
        "payment_plan": "plutus",
        "vendor_status": "hera",
        "vendor_lead_time": "hera",
        "vendor_reliability": "hera",
        "vendor_outstanding": "hera",
        "employee_lookup": "themis",
        "hr_dashboard": "themis",
        "hr_policies": "themis",
        "skill_matrix": "themis",
        "pipeline_forecast": "tyche",
        "win_loss_analysis": "tyche",
        "deal_velocity": "tyche",
        "classify_leads": "tyche",
        "craft_email_for_lead": "hermes",
        "crm_export_leads": "mnemosyne",
        "discovery_sweep": "prometheus",
        "actuals_vs_targets": "plutus",
        "budget_alerts": "plutus",
        "finance_export": "plutus",
        "draft_project_status_email": "atlas",
        "suggest_content_topics": "cadmus",
        "po_draft": "hera",
        "scrape_website": "iris",
        "find_case_studies": "cadmus",
        "build_case_study": "cadmus",
        "draft_linkedin_post": "cadmus",
        "draft_linkedin_post_with_visuals": "cadmus",
        "punch_list": "asclepius",
        "log_punch_item": "asclepius",
        "close_punch_item": "asclepius",
        "quality_dashboard": "asclepius",
        "recurring_quality_patterns": "asclepius",
        "verify_draft": "vera",
        "memory_search": "mnemosyne",
        "latest_news": "iris",
        "build_quote_pdf_multi": "quotebuilder",
        "content_calendar": "arachne",
        "assemble_newsletter": "arachne",
        "distribution_status": "arachne",
        "create_leads_from_discovery": "prometheus",
    }
    _agent_name = _tool_agent_map.get(tool_name)
    if _agent_name:
        try:
            from openclaw.agents.ira.src.holistic.endocrine_system import get_endocrine_system
            get_endocrine_system().signal_invocation(_agent_name)
        except Exception as e:
            logger.debug("Endocrine signal_invocation failed for %s: %s", _agent_name, e)

    if tool_name == "research_skill":
        query = arguments.get("query", "")
        results_parts = []
        research_ctx = dict(context or {})
        if arguments.get("synthesis_mode") is not None:
            research_ctx["synthesis_mode"] = arguments.get("synthesis_mode")
        if arguments.get("citation_only") is not None:
            research_ctx["citation_only"] = bool(arguments.get("citation_only"))

        # Primary search
        result = await invoke_research(query, research_ctx)
        if result:
            results_parts.append(f"[primary] {result}")
        
        # If primary search returned little, try Qdrant directly with the raw query
        if not result or len(result) < 100:
            try:
                from openclaw.agents.ira.src.brain.qdrant_retriever import retrieve as qdrant_retrieve
                rag = qdrant_retrieve(query, top_k=8)
                if hasattr(rag, 'citations') and rag.citations:
                    for c in rag.citations[:5]:
                        results_parts.append(f"[qdrant:{c.filename}] {c.text[:400]}")
            except Exception as e:
                logger.debug("Qdrant fallback retrieval failed: %s", e)
        
        final_result = "\n\n".join(results_parts) if results_parts else "(No results found in knowledge base)"
        _record_tool_metadata(
            context, "research_skill",
            source="qdrant+mem0+neo4j+machine_specs",
            confidence=0.85 if len(results_parts) > 1 else 0.5,
            entities=[arguments.get("query", "")[:100]],
        )
        return final_result

    elif tool_name == "web_search":
        import httpx

        query = arguments.get("query", "")
        company = arguments.get("company", "")
        results_parts = []
        search_query = f"{company} {query}".strip() if company else query

        tavily_key = os.environ.get("TAVILY_API_KEY", "")
        serper_key = os.environ.get("SERPER_API_KEY", "")

        async def _tavily_search(q: str) -> List[str]:
            if not tavily_key:
                return []
            parts = []
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": tavily_key,
                            "query": q,
                            "search_depth": "advanced",
                            "max_results": 5,
                            "include_answer": True,
                        },
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("answer"):
                        parts.append(f"[tavily_answer] {data['answer']}")
                    for r in data.get("results", [])[:5]:
                        title = r.get("title", "")
                        content = r.get("content", "")[:400]
                        url = r.get("url", "")
                        if content:
                            parts.append(f"[tavily] {title}: {content} ({url})")
            except Exception as e:
                logger.debug("Tavily search failed: %s", e)
            return parts

        async def _serper_search(q: str) -> List[str]:
            if not serper_key:
                return []
            parts = []
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        "https://google.serper.dev/search",
                        json={"q": q, "num": 5},
                        headers={"X-API-KEY": serper_key},
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    kg = data.get("knowledgeGraph", {})
                    if kg.get("description"):
                        parts.append(f"[google_kg] {kg.get('title', '')}: {kg['description']}")
                    for r in data.get("organic", [])[:5]:
                        title = r.get("title", "")
                        snippet = r.get("snippet", "")
                        if snippet:
                            parts.append(f"[google] {title}: {snippet}")
                    for paa in data.get("peopleAlsoAsk", [])[:2]:
                        parts.append(f"[google_paa] Q: {paa.get('question', '')} A: {paa.get('snippet', '')}")
            except Exception as e:
                logger.debug("Serper search failed: %s", e)
            return parts

        async def _jina_search(q: str) -> List[str]:
            parts = []
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        f"https://s.jina.ai/{q}",
                        headers={"Accept": "application/json"},
                    )
                if resp.status_code == 200 and len(resp.text.strip()) > 50:
                    parts.append(f"[jina] {resp.text[:3000]}")
            except Exception as e:
                logger.debug("Jina search failed: %s", e)
            return parts

        # Run Tavily + Serper + Jina concurrently
        tavily_res, serper_res, jina_res = await asyncio.gather(
            _tavily_search(search_query),
            _serper_search(search_query),
            _jina_search(search_query),
            return_exceptions=True,
        )
        for batch in (tavily_res, serper_res):
            if isinstance(batch, list):
                results_parts.extend(batch)
        # Jina is a fallback — only use if primary sources returned nothing
        if not results_parts and isinstance(jina_res, list):
            results_parts.extend(jina_res)

        # Iris enrichment (company-specific intelligence)
        if company:
            try:
                from openclaw.agents.ira.src.agents.iris_skill import iris_enrich
                iris_ctx = {"company": company, "query": query}
                iris_result = await iris_enrich(iris_ctx)
                if iris_result:
                    for k, v in iris_result.items():
                        if v and len(str(v)) > 10:
                            results_parts.append(f"[iris:{k}] {v}")
            except Exception as e:
                logger.debug("Iris enrichment failed: %s", e)

        # Website scraping (when company specified and results still thin)
        if company and len(results_parts) < 3:
            try:
                domain = company.lower().replace(" ", "").replace(",", "")
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        f"https://r.jina.ai/https://www.{domain}.com",
                        headers={"Accept": "text/plain"},
                    )
                if resp.status_code == 200 and len(resp.text) > 100:
                    results_parts.append(f"[website:{domain}.com] {resp.text[:2000]}")
            except Exception as e:
                logger.debug("Website scrape failed for %s: %s", company, e)

        web_result = "\n\n".join(results_parts) if results_parts else "(No web results found)"
        _record_tool_metadata(
            context, "web_search",
            source="tavily+serper+jina",
            confidence=0.4,
        )
        return web_result

    elif tool_name == "lead_intelligence":
        company = arguments.get("company", "")
        extra_context = arguments.get("context", "")
        results_parts = []

        # Iris enrichment (primary)
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_iris_enrich
            iris_ctx = {"company": company, "query": extra_context or company}
            iris_result = await invoke_iris_enrich(iris_ctx)
            if iris_result:
                for k, v in iris_result.items():
                    if v and len(str(v)) > 10:
                        results_parts.append(f"[iris:{k}] {v}")
        except Exception as e:
            logger.debug(f"Iris enrichment failed: {e}")

        # NewsData.io for latest headlines
        try:
            from openclaw.agents.ira.src.tools.newsdata_client import search_news
            news_result = await search_news(query=company, max_results=3)
            if news_result and not news_result.startswith("("):
                results_parts.append(f"[newsdata] {news_result}")
        except Exception as e:
            logger.debug("Lead intelligence NewsData search failed: %s", e)

        # Tavily web search fallback
        if len(results_parts) < 3:
            tavily_key = os.environ.get("TAVILY_API_KEY", "")
            if tavily_key:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=20) as client:
                        resp = await client.post(
                            "https://api.tavily.com/search",
                            json={
                                "api_key": tavily_key,
                                "query": f"{company} latest news expansion manufacturing",
                                "search_depth": "advanced",
                                "max_results": 5,
                                "include_answer": True,
                            },
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("answer"):
                            results_parts.append(f"[news_summary] {data['answer']}")
                        for r in data.get("results", [])[:3]:
                            content = r.get("content", "")[:300]
                            if content:
                                results_parts.append(f"[news] {r.get('title', '')}: {content}")
                except Exception as e:
                    logger.debug("Lead intelligence Tavily search failed: %s", e)

        # CRM history for this company
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_crm_lookup
            crm_result = await invoke_crm_lookup(company, context)
            if crm_result and "don't have anyone" not in crm_result:
                results_parts.append(f"[crm_history] {crm_result}")
        except Exception as e:
            logger.debug("CRM lookup failed for %s: %s", company, e)

        return "\n\n".join(results_parts) if results_parts else f"(No intelligence found for '{company}')"

    elif tool_name == "customer_lookup":
        query = arguments.get("query", "")
        results_parts = []

        # 1. Mnemosyne CRM lookup (primary)
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_crm_lookup
            crm_result = await invoke_crm_lookup(query, context)
            if crm_result and "don't have anyone" not in crm_result:
                results_parts.append(f"[CRM]\n{crm_result}")
        except Exception as e:
            logger.debug(f"Mnemosyne lookup failed: {e}")

        # 2. Qdrant ira_customers collection
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Filter, FieldCondition, MatchText
            qdrant = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"))
            qdrant_filter = Filter(
                should=[
                    FieldCondition(key="company", match=MatchText(text=query)),
                    FieldCondition(key="name", match=MatchText(text=query)),
                    FieldCondition(key="country", match=MatchText(text=query)),
                ]
            )
            hits, _ = qdrant.scroll(
                collection_name="ira_customers",
                scroll_filter=qdrant_filter,
                limit=5,
                with_payload=True,
            )
            for hit in hits:
                p = hit.payload or {}
                name = p.get("name", "")
                company = p.get("company", "")
                country = p.get("country", "")
                machines = p.get("machines", [])
                parts = [f"{name} at {company} ({country})"]
                if machines:
                    parts.append(f"Machines: {', '.join(machines)}")
                results_parts.append(f"[qdrant_customers] {' | '.join(parts)}")
        except Exception as e:
            logger.debug(f"Qdrant customer lookup failed: {e}")

        # 3. Mem0 fallback
        if not results_parts:
            try:
                from openclaw.agents.ira.src.memory.mem0_memory import get_mem0_service
                mem0 = get_mem0_service()
                for uid in ["machinecraft_customers", "machinecraft_knowledge"]:
                    memories = mem0.search(query, uid, limit=10)
                    for m in memories:
                        results_parts.append(f"[{uid}] {m.memory}")
            except Exception as e:
                logger.warning(f"Customer lookup Mem0 error: {e}")

        if results_parts:
            _record_tool_metadata(
                context, "customer_lookup",
                source="crm+qdrant+mem0",
                confidence=0.9,
                entities=[query[:100]],
            )
            return "\n\n".join(results_parts)
        return f"(No customer data found for '{query}')"

    elif tool_name == "crm_list_customers":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_crm_list_customers
            return await invoke_crm_list_customers(context)
        except Exception as e:
            return f"(Customer list error: {e})"

    elif tool_name == "crm_pipeline":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_crm_pipeline
            return await invoke_crm_pipeline(context)
        except Exception as e:
            return f"(Mnemosyne pipeline error: {e})"

    elif tool_name == "crm_drip_candidates":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_crm_drip
            return await invoke_crm_drip(context)
        except Exception as e:
            return f"(Mnemosyne drip error: {e})"

    elif tool_name == "finance_overview":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_finance_overview
            return await invoke_finance_overview(query, context)
        except Exception as e:
            return f"(Finance overview error: {e})"

    elif tool_name == "order_book_status":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_order_book_status
            return await invoke_order_book_status(context)
        except Exception as e:
            return f"(Order book error: {e})"

    elif tool_name == "cashflow_forecast":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_cashflow_forecast
            return await invoke_cashflow_forecast(context)
        except Exception as e:
            return f"(Cashflow forecast error: {e})"

    elif tool_name == "revenue_history":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_revenue_history
            return await invoke_revenue_history(query, context)
        except Exception as e:
            return f"(Revenue history error: {e})"

    elif tool_name == "net_cashflow":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_net_cashflow
            return await invoke_net_cashflow(context)
        except Exception as e:
            return f"(Net cashflow error: {e})"

    elif tool_name == "cash_position":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_cash_position
            return await invoke_cash_position(context)
        except Exception as e:
            return f"(Cash position error: {e})"

    elif tool_name == "payment_plan":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_payment_plan
            return await invoke_payment_plan(context)
        except Exception as e:
            return f"(Payment plan error: {e})"

    elif tool_name == "project_summary":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_project_summary
            return await invoke_project_summary(query, context)
        except Exception as e:
            return f"(Project summary error: {e})"

    elif tool_name == "all_projects_overview":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_all_projects_overview
            return await invoke_all_projects_overview(context)
        except Exception as e:
            return f"(Projects overview error: {e})"

    elif tool_name == "project_documents":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_project_documents
            return await invoke_project_documents(query, context)
        except Exception as e:
            return f"(Project documents error: {e})"

    elif tool_name == "project_logbook":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_project_logbook
            return await invoke_project_logbook(query, context)
        except Exception as e:
            return f"(Project logbook error: {e})"

    elif tool_name == "machine_knowledge":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_machine_knowledge
            return await invoke_machine_knowledge(query, context)
        except Exception as e:
            return f"(Machine knowledge error: {e})"

    elif tool_name == "risk_register":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_risk_register
            return await invoke_risk_register(context)
        except Exception as e:
            return f"(Risk register error: {e})"

    elif tool_name == "payment_alerts":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_payment_alerts
            return await invoke_payment_alerts(context)
        except Exception as e:
            return f"(Payment alerts error: {e})"
    elif tool_name == "milestone_alerts":
        try:
            from openclaw.agents.ira.src.agents.atlas.agent import milestone_alerts
            return await milestone_alerts(context)
        except Exception as e:
            return f"(Milestone alerts error: {e})"

    elif tool_name == "production_schedule":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_production_schedule
            return await invoke_production_schedule(query, context)
        except Exception as e:
            return f"(Production schedule error: {e})"

    elif tool_name == "vendor_status":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_vendor_status
            return await invoke_vendor_status(context)
        except Exception as e:
            return f"(Vendor status error: {e})"

    elif tool_name == "vendor_lead_time":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_vendor_lead_time
            return await invoke_vendor_lead_time(query, context)
        except Exception as e:
            return f"(Vendor lead time error: {e})"

    elif tool_name == "vendor_reliability":
        try:
            from openclaw.agents.ira.src.agents.hera.agent import get_vendor_reliability
            rows = get_vendor_reliability(grace_days=3)
            if not rows:
                return "HERA — Vendor reliability: No PO records with both expected and actual delivery dates. Data improves as actual_delivery is filled in hera_vendors.db."
            lines = ["# HERA — Vendor Delivery Reliability", ""]
            for r in rows[:20]:
                lines.append(f"- **{r['vendor_name']}** — {r['on_time_pct']}% on-time ({r['total_pos']} POs, {r['late_count']} late)")
            return "\n".join(lines)
        except Exception as e:
            return f"(Vendor reliability error: {e})"

    elif tool_name == "vendor_outstanding":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_vendor_outstanding
            return await invoke_vendor_outstanding(query, context)
        except Exception as e:
            return f"(Vendor outstanding error: {e})"

    elif tool_name == "employee_lookup":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_employee_lookup
            return await invoke_employee_lookup(query, context)
        except Exception as e:
            return f"(Employee lookup error: {e})"

    elif tool_name == "hr_dashboard":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_hr_dashboard
            return await invoke_hr_dashboard(context)
        except Exception as e:
            return f"(HR dashboard error: {e})"

    elif tool_name == "hr_policies":
        try:
            from openclaw.agents.ira.src.agents.themis.agent import get_hr_policies
            return get_hr_policies()
        except Exception as e:
            return f"(HR policies error: {e})"

    elif tool_name == "skill_matrix":
        export_csv = bool(arguments.get("export_csv", False))
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_skill_matrix
            return await invoke_skill_matrix(context=context, export_csv=export_csv)
        except Exception as e:
            return f"(Skill matrix error: {e})"

    elif tool_name == "punch_list":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_punch_list
            return await invoke_punch_list(query, context)
        except Exception as e:
            return f"(Punch list error: {e})"

    elif tool_name == "log_punch_item":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_log_punch_item
            return await invoke_log_punch_item(arguments, context)
        except Exception as e:
            return f"(Log punch item error: {e})"

    elif tool_name == "close_punch_item":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_close_punch_item
            return await invoke_close_punch_item(arguments, context)
        except Exception as e:
            return f"(Close punch item error: {e})"

    elif tool_name == "quality_dashboard":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_quality_dashboard
            return await invoke_quality_dashboard(context)
        except Exception as e:
            return f"(Quality dashboard error: {e})"

    elif tool_name == "recurring_quality_patterns":
        try:
            from openclaw.agents.ira.src.agents.asclepius.agent import recurring_quality_patterns as _recurring
            return await _recurring(context=context, feed_to_nemesis=bool(arguments.get("feed_to_nemesis", False)))
        except Exception as e:
            return f"(Recurring quality patterns error: {e})"

    elif tool_name == "actuals_vs_targets":
        try:
            from openclaw.agents.ira.src.agents.finance_agent.agent import actuals_vs_targets
            return await actuals_vs_targets(context)
        except Exception as e:
            return f"(Actuals vs targets error: {e})"
    elif tool_name == "budget_alerts":
        try:
            from openclaw.agents.ira.src.agents.finance_agent.agent import budget_alerts
            return await budget_alerts(context)
        except Exception as e:
            return f"(Budget alerts error: {e})"

    elif tool_name == "finance_export":
        fmt = (arguments.get("format") or "csv").strip().lower() or "csv"
        try:
            from openclaw.agents.ira.src.agents.finance_agent.agent import finance_export
            return await finance_export(format=fmt, context=context)
        except Exception as e:
            return f"(Finance export error: {e})"

    elif tool_name == "draft_project_status_email":
        query = (arguments.get("query") or "").strip()
        if not query:
            return "(Error: query (customer or project number) is required for draft_project_status_email)"
        try:
            from openclaw.agents.ira.src.agents.atlas.agent import draft_project_status_email
            return await draft_project_status_email(query, context)
        except Exception as e:
            return f"(Draft project status email error: {e})"

    elif tool_name == "suggest_content_topics":
        topic_query = (arguments.get("query") or "thermoforming manufacturing industry").strip()
        try:
            from openclaw.agents.ira.src.tools.newsdata_client import search_news
            news = await search_news(query=topic_query, max_results=8)
            if not news:
                return "No trend data returned. Try with query e.g. 'vacuum forming', 'EV manufacturing'."
            lines = ["Suggested content topics (from current trends):", ""]
            for i, line in enumerate(news.strip().split("\n")[:12], 1):
                line = line.strip()
                if line and not line.startswith("---"):
                    lines.append(f"  {i}. {line[:120]}")
            return "\n".join(lines) if len(lines) > 2 else news
        except Exception as e:
            return f"(Suggest content topics error: {e})"

    elif tool_name == "po_draft":
        vendor_name = (arguments.get("vendor_name") or "").strip()
        line_items = (arguments.get("line_items") or "").strip()
        if not vendor_name or not line_items:
            return "(Error: vendor_name and line_items are required for po_draft)"
        try:
            from openclaw.agents.ira.src.agents.hera.agent import po_draft
            return await po_draft(vendor_name, line_items)
        except Exception as e:
            return f"(PO draft error: {e})"

    elif tool_name == "pipeline_forecast":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_pipeline_forecast
            return await invoke_pipeline_forecast(query, context)
        except Exception as e:
            return f"(Pipeline forecast error: {e})"

    elif tool_name == "win_loss_analysis":
        region = arguments.get("region", "")
        machine_type = arguments.get("machine_type", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_win_loss_analysis
            return await invoke_win_loss_analysis(region, machine_type, context)
        except Exception as e:
            return f"(Win/loss analysis error: {e})"

    elif tool_name == "deal_velocity":
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_deal_velocity
            return await invoke_deal_velocity(context)
        except Exception as e:
            return f"(Deal velocity error: {e})"

    elif tool_name == "classify_leads":
        days = arguments.get("days")
        if days is not None:
            try:
                days = int(days)
            except (TypeError, ValueError):
                days = 30
        else:
            days = 30
        try:
            from openclaw.agents.ira.src.agents.tyche.agent import classify_leads as tyche_classify_leads
            return await tyche_classify_leads(days=days, context=context)
        except Exception as e:
            return f"(Classify leads error: {e})"

    elif tool_name == "craft_email_for_lead":
        lead_id = (arguments.get("lead_id") or "").strip()
        if not lead_id:
            return "(Error: lead_id is required for craft_email_for_lead)"
        try:
            from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
            hermes = get_hermes()
            draft = await hermes.craft_email(lead_id)
            if not draft:
                return f"(No draft produced for lead {lead_id})"
            lines = [
                f"Draft for lead {lead_id} — {draft.get('company', '?')} ({draft.get('country', '?')})",
                f"To: {draft.get('to_email', '')}",
                f"Subject: {draft.get('subject', '')}",
                "",
                draft.get("body", ""),
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"(Craft email error: {e})"

    elif tool_name == "suggest_email_subjects":
        lead_id = (arguments.get("lead_id") or "").strip()
        if not lead_id:
            return "(Error: lead_id is required)"
        try:
            from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
            hermes = get_hermes()
            draft = await hermes.craft_email(lead_id)
            if not draft:
                return f"(No draft for lead {lead_id}. Check lead_id or run craft_email_for_lead first.)"
            subj = (draft.get("subject") or "").strip() or "Follow-up"
            company = draft.get("company", "")
            try:
                import openai
                client = openai.AsyncOpenAI()
                r = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Suggest 2 alternative email subject lines for the same outreach. Short, professional, different from the original. Return only 2 lines, one per line, no numbering."},
                        {"role": "user", "content": f"Company: {company}. Original subject: {subj}. Give 2 alternative subject lines."},
                    ],
                    max_tokens=120,
                    temperature=0.7,
                )
                alts = (r.choices[0].message.content or "").strip().split("\n")[:2]
                alts = [a.strip().lstrip("012.-) ") for a in alts if a.strip()]
            except Exception:
                alts = []
            lines = [f"A/B subject options for {lead_id} ({company}):", "", f"1. {subj}"]
            for i, a in enumerate(alts, 2):
                if a:
                    lines.append(f"{i}. {a}")
            return "\n".join(lines)
        except Exception as e:
            return f"(Suggest email subjects error: {e})"

    elif tool_name == "suggest_next_training":
        days = int(arguments.get("days") or 90)
        try:
            from openclaw.agents.ira.src.agents.chiron.agent import get_chiron
            return get_chiron().suggest_next_training(days=days)
        except Exception as e:
            return f"(Suggest next training error: {e})"

    elif tool_name == "crm_export_leads":
        fmt = (arguments.get("format") or "json").strip().lower()
        if fmt not in ("json", "csv"):
            fmt = "json"
        include_contacts = bool(arguments.get("include_contacts", False))
        try:
            from openclaw.agents.ira.src.crm.ira_crm import get_crm
            import json as _json
            crm = get_crm()
            leads = crm.get_all_leads()
            def _csv_escape(v):
                s = str(v) if v is not None else ""
                if "," in s or "\n" in s or '"' in s:
                    return '"' + s.replace('"', '""') + '"'
                return s

            rows = []
            for lead in leads:
                row = {
                    "email": getattr(lead, "email", None),
                    "company": getattr(lead, "company", None),
                    "country": getattr(lead, "country", None),
                    "deal_stage": getattr(lead, "deal_stage", None),
                    "priority": getattr(lead, "priority", None),
                    "last_email_sent": getattr(lead, "last_email_sent", None),
                    "drip_stage": getattr(lead, "drip_stage", None),
                }
                if include_contacts:
                    row["name"] = getattr(lead, "name", None)
                    row["first_name"] = getattr(lead, "first_name", None)
                    row["title"] = getattr(lead, "title", None)
                    row["industry"] = getattr(lead, "industry", None)
                rows.append(row)
            if fmt == "csv":
                import io
                out = io.StringIO()
                if rows:
                    keys = list(rows[0].keys())
                    out.write(",".join(keys) + "\n")
                    for r in rows:
                        out.write(",".join(_csv_escape(r.get(k, "")) for k in keys) + "\n")
                return out.getvalue()
            return _json.dumps(rows, indent=2, default=str)
        except Exception as e:
            return f"(CRM export error: {e})"

    elif tool_name == "discovery_sweep":
        industries_arg = (arguments.get("industries") or "").strip()
        industries = [s.strip() for s in industries_arg.split(",") if s.strip()] if industries_arg else None
        try:
            from openclaw.agents.ira.src.agents.prometheus.agent import discovery_sweep as prometheus_discovery_sweep
            return await prometheus_discovery_sweep(industries=industries)
        except Exception as e:
            return f"(Discovery sweep error: {e})"

    elif tool_name == "create_leads_from_discovery":
        max_leads = int(arguments.get("max_leads") or 10)
        try:
            from openclaw.agents.ira.src.agents.prometheus.crm_handoff import create_leads_from_discovery as do_create
            return do_create(max_leads=max_leads)
        except Exception as e:
            return f"(Create leads from discovery error: {e})"

    elif tool_name == "meeting_notes_to_actions":
        notes = arguments.get("meeting_notes", "") or ""
        try:
            from openclaw.agents.ira.src.tools.meeting_actions import meeting_notes_to_actions as do_meeting
            return await do_meeting(notes)
        except Exception as e:
            return f"(Meeting notes to actions error: {e})"

    elif tool_name == "task_list":
        status = (arguments.get("status") or "open").strip()
        assignee = (arguments.get("assignee") or "").strip()
        limit = int(arguments.get("limit") or 30)
        try:
            from openclaw.agents.ira.src.tools.task_store import task_list as do_task_list
            return do_task_list(status=status, assignee=assignee, limit=limit)
        except Exception as e:
            return f"(Task list error: {e})"

    elif tool_name == "task_create":
        title = (arguments.get("title") or "").strip()
        if not title:
            return "(Error: title is required)"
        assignee = (arguments.get("assignee") or "").strip()
        due = (arguments.get("due") or "").strip()
        notes = (arguments.get("notes") or "").strip()
        try:
            from openclaw.agents.ira.src.tools.task_store import task_create as do_task_create
            return do_task_create(title=title, assignee=assignee, due=due, notes=notes)
        except Exception as e:
            return f"(Task create error: {e})"

    elif tool_name == "task_complete":
        try:
            task_id = int(arguments.get("task_id"))
        except (TypeError, ValueError):
            return "(Error: task_id must be an integer)"
        try:
            from openclaw.agents.ira.src.tools.task_store import task_complete as do_task_complete
            return do_task_complete(task_id)
        except Exception as e:
            return f"(Task complete error: {e})"

    elif tool_name == "pipeline_digest":
        send_to_telegram = bool(arguments.get("send_to_telegram"))
        try:
            from openclaw.agents.ira.src.agents.tyche.agent import pipeline_forecast
            digest = await pipeline_forecast("", context=context or {})
            if send_to_telegram:
                try:
                    from openclaw.agents.ira.src.core.telegram_helpers import send_telegram_async
                    text = f"📊 Pipeline digest\n\n{digest[:3500]}"
                    await send_telegram_async(text)
                except Exception:
                    pass
            return digest
        except Exception as e:
            return f"(Pipeline digest error: {e})"

    elif tool_name == "suggest_next_touch":
        lead_email = (arguments.get("lead_email") or "").strip().lower()
        if not lead_email or "@" not in lead_email:
            return "(Error: lead_email is required)"
        try:
            from openclaw.agents.ira.src.crm.ira_crm import get_crm, DRIP_INTERVALS_DAYS
            from datetime import datetime, timedelta
            crm = get_crm()
            lead = crm.get_lead(lead_email)
            if not lead:
                return f"No lead found for {lead_email}. Add them to CRM first."
            last_sent = getattr(lead, "last_email_sent", None) or ""
            priority = getattr(lead, "priority", "medium") or "medium"
            intervals = DRIP_INTERVALS_DAYS.get(priority, DRIP_INTERVALS_DAYS.get("medium", [0, 7, 14, 28]))
            days = int(intervals[1]) if len(intervals) > 1 else 7
            if last_sent:
                try:
                    dt = datetime.strptime(last_sent[:10], "%Y-%m-%d")
                    next_dt = dt + timedelta(days=days)
                    return f"Suggested next touch: {next_dt.strftime('%Y-%m-%d')} (+{days} days from last email {last_sent[:10]})."
                except ValueError:
                    pass
            next_dt = datetime.now() + timedelta(days=days)
            return f"Suggested next touch: {next_dt.strftime('%Y-%m-%d')} (+{days} days from today; no last_email_sent on record)."
        except Exception as e:
            return f"(Suggest next touch error: {e})"

    elif tool_name == "link_quote_to_lead":
        quote_id = (arguments.get("quote_id") or "").strip()
        lead_email = (arguments.get("lead_email") or "").strip().lower()
        if not quote_id or not lead_email or "@" not in lead_email:
            return "(Error: quote_id and lead_email are required)"
        try:
            from openclaw.agents.ira.src.crm.ira_crm import get_crm
            crm = get_crm()
            lead = crm.get_lead(lead_email)
            if not lead:
                crm.upsert_lead(lead_email, notes=f"Quote: {quote_id}")
                return f"Created lead {lead_email} with note Quote: {quote_id}."
            existing_notes = (getattr(lead, "notes", "") or "").strip()
            new_note = f"Quote: {quote_id}" if not existing_notes else f"{existing_notes}; Quote: {quote_id}"
            crm.upsert_lead(lead_email, notes=new_note)
            # Optional: move to proposal when quote is linked (crm_automation)
            try:
                cfg_path = Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "config" / "crm_automation.json"
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text())
                    if cfg.get("on_quote_linked_move_to_proposal"):
                        stage = getattr(lead, "deal_stage", "") or "new"
                        if stage in ("qualified", "contacted"):
                            crm.update_deal_stage(lead_email, "proposal", notes="Quote linked (crm_automation)")
                            return f"Linked quote {quote_id} to lead {lead_email}. Notes updated. Deal stage moved to proposal (crm_automation)."
            except Exception:
                pass
            return f"Linked quote {quote_id} to lead {lead_email}. Notes updated."
        except Exception as e:
            return f"(Link quote to lead error: {e})"

    elif tool_name == "scrape_website":
        domain = arguments.get("domain", "")
        company = arguments.get("company", domain)
        try:
            from openclaw.agents.ira.src.agents.hermes.board_meeting import BoardMeetingResearcher
            researcher = BoardMeetingResearcher()
            result = researcher._scrape_website(f"info@{domain}", company)
            return result if result else f"(No content found on {domain}. Site may block scrapers or domain may be incorrect.)"
        except Exception as e:
            return f"(Website scrape error: {e})"

    elif tool_name == "memory_search":
        query = arguments.get("query", "")
        user_id = arguments.get("user_id", "")
        results = []
        try:
            from openclaw.agents.ira.src.memory.mem0_memory import get_mem0_service
            mem0 = get_mem0_service()
            search_ids = [user_id] if user_id else [
                "machinecraft_knowledge", "machinecraft_customers",
                "machinecraft_pricing", "machinecraft_processes",
                "machinecraft_general",
            ]
            for uid in search_ids:
                memories = mem0.search(query, uid, limit=10)
                for m in memories:
                    results.append(f"[{uid}] {m.memory}")
        except Exception as e:
            logger.warning(f"Memory search error: {e}")
        return "\n".join(results) if results else f"(No memories found for '{query}')"

    elif tool_name == "writing_skill":
        query = arguments.get("query", "")
        research_summary = arguments.get("research_summary", "")
        ctx = dict(context)
        ctx["research_output"] = research_summary
        result = await invoke_write(query, ctx)
        return result or "(Draft empty)"

    elif tool_name == "fact_checking_skill":
        draft = arguments.get("draft", "")
        original_query = arguments.get("original_query", "")
        result = await invoke_verify(draft, original_query, context)
        return result or draft

    elif tool_name == "verify_draft":
        draft = arguments.get("draft", "")
        query = arguments.get("query", "")
        issues = []
        try:
            from openclaw.agents.ira.src.brain.knowledge_health import validate_response
            _safe, _warnings = validate_response(query, draft)
            if _warnings:
                issues.extend(_warnings)
        except Exception as e:
            logger.warning("[verify_draft] knowledge_health check failed: %s", e)
        try:
            from openclaw.agents.ira.src.agents.fact_checker.agent import _verify_prices, _check_am_series_rule
            price_issues = _verify_prices(draft)
            if price_issues:
                issues.extend(price_issues)
            am_result = _check_am_series_rule(draft, query)
            if isinstance(am_result, dict) and am_result.get("violation"):
                issues.append(f"AM SERIES RULE: {am_result.get('issue', 'AM series only for ≤1.5mm')}")
            elif isinstance(am_result, str) and am_result:
                issues.append(am_result)
        except Exception as e:
            logger.debug("[verify_draft] price/AM check failed: %s", e)
        _record_tool_metadata(
            context, "verify_draft",
            source="knowledge_health+machine_specs",
            confidence=1.0 if not issues else 0.3,
        )
        if issues:
            return "VERIFICATION ISSUES FOUND — fix these before responding:\n" + "\n".join(f"- {i}" for i in issues)
        return "VERIFIED: No issues found. Draft looks accurate."

    elif tool_name == "read_spreadsheet":
        spreadsheet_id = arguments.get("spreadsheet_id", "")
        range_name = arguments.get("range", "Sheet1")
        try:
            from openclaw.agents.ira.src.tools.google_tools import sheets_read
            return sheets_read(spreadsheet_id, range_name)
        except ImportError:
            return "(Google Sheets not available. Install: pip install google-api-python-client)"
        except Exception as e:
            return f"(Spreadsheet error: {e})"

    elif tool_name == "search_drive":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.tools.google_tools import drive_list
            return drive_list(query)
        except ImportError:
            return "(Google Drive not available.)"
        except Exception as e:
            return f"(Drive error: {e})"

    elif tool_name == "check_calendar":
        days = arguments.get("days", 7)
        try:
            from openclaw.agents.ira.src.tools.google_tools import calendar_upcoming
            return calendar_upcoming(days)
        except ImportError:
            return "(Google Calendar not available.)"
        except Exception as e:
            return f"(Calendar error: {e})"

    elif tool_name == "search_contacts":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.tools.google_tools import contacts_search
            return contacts_search(query)
        except ImportError:
            return "(Google Contacts not available.)"
        except Exception as e:
            return f"(Contacts error: {e})"

    elif tool_name == "read_inbox":
        max_results = arguments.get("max_results", 10)
        unread_only = arguments.get("unread_only", True)
        try:
            from openclaw.agents.ira.src.tools.google_tools import gmail_read_inbox
            return gmail_read_inbox(max_results=max_results, unread_only=unread_only)
        except ImportError:
            return "(Gmail not available. Install: pip install google-api-python-client google-auth-oauthlib)"
        except Exception as e:
            return f"(Inbox error: {e})"

    elif tool_name == "search_email":
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 10)
        try:
            from openclaw.agents.ira.src.tools.google_tools import gmail_search
            return gmail_search(query=query, max_results=max_results)
        except ImportError:
            return "(Gmail not available.)"
        except Exception as e:
            return f"(Email search error: {e})"

    elif tool_name == "read_email_message":
        message_id = arguments.get("message_id", "")
        if not message_id:
            return "(Error: message_id is required)"
        try:
            from openclaw.agents.ira.src.tools.google_tools import gmail_read_message
            return gmail_read_message(message_id=message_id)
        except ImportError:
            return "(Gmail not available.)"
        except Exception as e:
            return f"(Read message error: {e})"

    elif tool_name == "read_email_thread":
        thread_id = arguments.get("thread_id", "")
        max_messages = arguments.get("max_messages", 10)
        if not thread_id:
            return "(Error: thread_id is required)"
        try:
            from openclaw.agents.ira.src.tools.google_tools import gmail_get_thread
            return gmail_get_thread(thread_id=thread_id, max_messages=max_messages)
        except ImportError:
            return "(Gmail not available.)"
        except Exception as e:
            return f"(Thread read error: {e})"

    elif tool_name == "send_email":
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        body_html = arguments.get("body_html", "")
        thread_id = arguments.get("thread_id", "")
        if not to or not subject or not body:
            return "(Error: to, subject, and body are all required)"
        try:
            from openclaw.agents.ira.src.tools.google_tools import gmail_send
            result = gmail_send(to=to, subject=subject, body=body, body_html=body_html, thread_id=thread_id)
            try:
                from openclaw.agents.ira.src.agents.atlas.agent import try_log_sent_email_to_atlas
                try_log_sent_email_to_atlas(to, subject, (body or "")[:300])
            except Exception:
                pass
            return result
        except ImportError:
            return "(Gmail not available.)"
        except Exception as e:
            return f"(Send email error: {e})"

    elif tool_name == "draft_email":
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")
        intent = arguments.get("intent", "")
        email_context = arguments.get("context", "")
        if not to or not subject or not intent:
            return "(Error: to, subject, and intent are all required)"
        try:
            from openclaw.agents.ira.tools.email import ira_email_draft
            draft = ira_email_draft(to=to, subject=subject, intent=intent, context=email_context)
            sources_note = ""
            if draft.context_used:
                sources_note = f"\n[Data sources used: {', '.join(draft.context_used)}]"
            return (
                f"DRAFT EMAIL (not sent — needs Rushabh's approval):\n\n"
                f"To: {draft.to}\n"
                f"Subject: {draft.subject}\n\n"
                f"{draft.body}"
                f"{sources_note}"
            )
        except ImportError:
            return "(Email drafting not available.)"
        except Exception as e:
            return f"(Draft email error: {e})"

    elif tool_name == "preview_outreach":
        try:
            from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
            emails = await get_hermes().preview_batch()
        except Exception as e:
            logger.warning("preview_outreach failed: %s", e)
            return f"(Preview outreach failed: {e})"
        if not emails:
            return "No leads ready for outreach right now (timezone filter or daily limit may apply). Check crm_drip_candidates for who is in the queue."
        lines = ["PREVIEW OUTREACH (drafts only — not sent):", ""]
        for i, e in enumerate(emails[:5], 1):
            lines.append(f"{i}. To: {e.get('to_email', '?')} | {e.get('company', '?')} ({e.get('country', '?')})")
            lines.append(f"   Subject: {e.get('subject', '')[:60]}")
            lines.append(f"   Body snippet: {(e.get('body', '') or '')[:200]}...")
            lines.append("")
        return "\n".join(lines)

    elif tool_name == "sales_outreach":
        dry_run = arguments.get("dry_run", True)
        try:
            from openclaw.agents.ira.src.agents.hermes.agent import get_hermes
            result = await get_hermes().run_outreach_batch(dry_run=dry_run)
        except Exception as e:
            logger.warning("sales_outreach failed: %s", e)
            return f"(Sales outreach failed: {e})"
        status = result.get("status", "unknown")
        batch_size = result.get("batch_size", 0)
        sent = result.get("sent", 0)
        drafts = result.get("drafts", 0)
        failed = result.get("failed", 0)
        if dry_run:
            emails = result.get("emails", [])
            lines = [f"PREVIEW OUTREACH (dry_run=True — nothing sent). Status: {status}. Drafts: {batch_size}.", ""]
            for i, e in enumerate(emails[:5], 1):
                lines.append(f"{i}. {e.get('company', '?')} ({e.get('country', '?')}) — {e.get('subject', '')[:50]}")
            return "\n".join(lines)
        return (
            f"OUTREACH BATCH COMPLETE. Sent: {sent}/{batch_size}. Failed: {failed}. "
            f"CRM and campaign state updated. Rushabh notified via Telegram."
        )

    elif tool_name == "discovery_scan":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_discovery_scan
            return await invoke_discovery_scan(query, context)
        except Exception as e:
            return f"(Discovery scan error: {e})"

    elif tool_name == "run_analysis":
        task = arguments.get("task", "")
        code = arguments.get("code", "")
        data = arguments.get("data", "")
        if not task and not code:
            return "(Error: provide either a 'task' description or 'code' to execute)"
        is_internal = context.get("is_internal", False)
        if not is_internal:
            return "(Hephaestus is only available for internal users.)"
        try:
            from openclaw.agents.ira.src.skills.invocation import invoke_hephaestus
            return await invoke_hephaestus(task=task, code=code, data=data, context=context)
        except ImportError:
            return "(Hephaestus not available.)"
        except Exception as e:
            return f"(Hephaestus error: {e})"

    elif tool_name == "ask_user":
        question = arguments.get("question", "")
        return f"ASK_USER:{question}"

    elif tool_name == "correction_report":
        include_pending = arguments.get("include_pending", True)
        if isinstance(include_pending, str):
            include_pending = include_pending.strip().lower() not in ("false", "0", "no")
        limit_pending = int(arguments.get("limit_pending") or 10)
        sort_by_confidence = bool(arguments.get("sort_by_confidence", False))
        min_confidence = arguments.get("min_confidence")
        if min_confidence is not None:
            try:
                min_confidence = float(min_confidence)
            except (TypeError, ValueError):
                min_confidence = None
        try:
            from openclaw.agents.ira.src.agents.nemesis.agent import get_nemesis
            return get_nemesis().get_hungry_report(
                include_pending=include_pending,
                limit_pending=limit_pending,
                sort_by_confidence=sort_by_confidence,
                min_confidence=min_confidence,
            )
        except Exception as e:
            logger.warning(f"correction_report failed: {e}")
            return f"(Nemesis report unavailable: {e})"

    elif tool_name == "dream_summary":
        return _read_dream_summary()

    elif tool_name == "build_quote_pdf":
        width_mm = arguments.get("width_mm")
        height_mm = arguments.get("height_mm")
        if width_mm is None or height_mm is None:
            return "(Error: width_mm and height_mm are required for build_quote_pdf)"
        try:
            width_mm = int(width_mm) if width_mm is not None else None
            height_mm = int(height_mm) if height_mm is not None else None
        except (TypeError, ValueError):
            return "(Error: width_mm and height_mm must be numbers)"
        if width_mm is None or height_mm is None:
            return "(Error: width_mm and height_mm are required for build_quote_pdf)"
        try:
            from openclaw.agents.ira.src.agents.quotebuilder import build_quote_pdf as quotebuilder_build
            result = quotebuilder_build(
                width_mm=width_mm,
                height_mm=height_mm,
                variant=str(arguments.get("variant", "C")).strip() or "C",
                customer_name=str(arguments.get("customer_name", "")),
                company_name=str(arguments.get("company_name", "")),
                customer_email=str(arguments.get("customer_email", "")),
                country=str(arguments.get("country", "India")),
                version=str(arguments.get("version", "1.0")).strip() or "1.0",
            )
            if context is not None:
                context.setdefault("_quote_files", [])
                context["_quote_files"].append({
                    "pdf_path": result.pdf_path,
                    "quote_id": result.quote_id,
                    "model": result.model,
                })
            return (
                f"Quote generated successfully.\n"
                f"Quote ID: {result.quote_id}\n"
                f"Model: {result.model}\n"
                f"Total: ₹{result.total_inr:,} INR (approx. ${result.total_usd:,} USD)\n"
                f"PDF: {result.pdf_path}\n"
                f"PDF is ready to attach and send to the customer."
            )
        except ImportError as e:
            return f"(Quotebuilder not available: {e})"
        except Exception as e:
            logger.warning(f"build_quote_pdf failed: {e}")
            return f"(Quotebuilder error: {e})"

    elif tool_name == "build_quote_pdf_multi":
        line_items = arguments.get("line_items")
        if not line_items or not isinstance(line_items, list):
            return "(Error: line_items (array of {width_mm, height_mm, ...}) is required for build_quote_pdf_multi)"
        try:
            from openclaw.agents.ira.src.agents.quotebuilder.agent import build_quote_pdf_multi as quotebuilder_multi
            result = quotebuilder_multi(
                line_items=line_items,
                customer_name=str(arguments.get("customer_name", "")),
                company_name=str(arguments.get("company_name", "")),
                customer_email=str(arguments.get("customer_email", "")),
                country=str(arguments.get("country", "India")),
                version=str(arguments.get("version", "1.0")).strip() or "1.0",
            )
            if context is not None:
                context.setdefault("_quote_files", [])
                context["_quote_files"].append({
                    "pdf_path": result.pdf_path,
                    "quote_id": result.quote_id,
                    "model": result.model,
                })
            return (
                f"Multi-machine quote generated successfully.\n"
                f"Quote ID: {result.quote_id}\n"
                f"Models: {result.model}\n"
                f"Total: ₹{result.total_inr:,} INR (approx. ${result.total_usd:,} USD)\n"
                f"PDF: {result.pdf_path}\n"
                f"PDF is ready to attach and send to the customer."
            )
        except ImportError as e:
            return f"(Quotebuilder not available: {e})"
        except Exception as e:
            logger.warning(f"build_quote_pdf_multi failed: {e}")
            return f"(Quotebuilder error: {e})"

    elif tool_name == "recommend_machine":
        try:
            from openclaw.agents.ira.src.brain.machine_recommender import recommend_machine as _recommend
            rec = _recommend(
                application=arguments.get("application", ""),
                material=arguments.get("material", ""),
                thickness_mm=float(arguments.get("thickness_mm", 0)),
                sheet_width_mm=int(arguments.get("sheet_width_mm", 0)),
                sheet_length_mm=int(arguments.get("sheet_length_mm", 0)),
                depth_mm=int(arguments.get("depth_mm", 0)),
                budget_inr=int(arguments.get("budget_inr", 0)),
                needs_grain=bool(arguments.get("needs_grain", False)),
                needs_pressure=bool(arguments.get("needs_pressure", False)),
            )
            return rec.to_text_brief()
        except Exception as e:
            logger.warning("recommend_machine failed: %s", e)
            return f"(Machine recommender error: {e})"

    elif tool_name == "latest_news":
        query = arguments.get("query", "")
        country = arguments.get("country", "")
        category = arguments.get("category", "")
        try:
            from openclaw.agents.ira.src.tools.newsdata_client import search_news
            return await search_news(
                query=query,
                country=country,
                category=category,
                max_results=5,
            )
        except Exception as e:
            logger.warning("latest_news failed: %s", e)
            return f"(News search error: {e})"

    elif tool_name == "log_sales_training":
        try:
            from openclaw.agents.ira.src.agents.chiron import get_chiron
            return get_chiron().log_pattern(
                title=arguments.get("title", ""),
                trigger=arguments.get("trigger", ""),
                wrong_approach=arguments.get("wrong_approach", ""),
                right_approach=arguments.get("right_approach", ""),
                example=arguments.get("example", ""),
                tool_chain=arguments.get("tool_chain", ""),
            )
        except Exception as e:
            logger.warning("log_sales_training failed: %s", e)
            return f"(Sales training log error: {e})"

    elif tool_name == "training_effectiveness":
        try:
            from openclaw.agents.ira.src.agents.chiron.agent import get_training_effectiveness_summary
            return get_training_effectiveness_summary()
        except Exception as e:
            return f"(Training effectiveness error: {e})"

    elif tool_name == "ask_librarian":
        query = arguments.get("query", "")
        lib_ctx = dict(context or {})
        if arguments.get("full_text_in_body") is not None:
            lib_ctx["full_text_in_body"] = bool(arguments.get("full_text_in_body"))
        try:
            from openclaw.agents.ira.src.agents.alexandros import ask_librarian as _ask_lib
            result = await _ask_lib(query, lib_ctx)
            # File-based ingestion: Alexandros queues returned filepaths to data/brain/deferred_ingestion_queue.jsonl;
            # nap (dream_mode._process_deferred_ingestion_queue) consumes that queue. No separate ingest_queue.jsonl needed.
            return result
        except Exception as e:
            logger.warning("ask_librarian failed: %s", e)
            return f"(Librarian error: {e})"

    elif tool_name == "browse_archive":
        folder = arguments.get("folder", "")
        doc_type = arguments.get("doc_type", "")
        try:
            from openclaw.agents.ira.src.agents.alexandros import browse_archive as _browse
            return await _browse(folder, doc_type, context)
        except Exception as e:
            logger.warning("browse_archive failed: %s", e)
            return f"(Archive browse error: {e})"

    elif tool_name == "file_detail":
        filename = arguments.get("filename", "")
        try:
            from openclaw.agents.ira.src.agents.alexandros import file_detail as _fdetail
            return await _fdetail(filename, context)
        except Exception as e:
            logger.warning("file_detail failed: %s", e)
            return f"(File detail error: {e})"

    elif tool_name == "rushabh_voice":
        customer_message = arguments.get("customer_message", "")
        company = arguments.get("company", "")
        voice_context = arguments.get("context", "")
        try:
            from openclaw.agents.ira.src.agents.delphi import consult_rushabh_voice
            result = await consult_rushabh_voice(customer_message, company, voice_context)
            if result:
                return f"[Echo — Rushabh's voice] {result}"
            return "(Echo is not trained yet. Run: python -m openclaw.agents.ira.src.agents.echo.agent build)"
        except ImportError as e:
            return f"(Echo agent not available: {e})"
        except Exception as e:
            logger.warning("rushabh_voice failed: %s", e)
            return f"(Echo error: {e})"

    elif tool_name == "find_case_studies":
        try:
            from openclaw.agents.ira.src.agents.cadmus import find_case_studies as _find_cs
            return await _find_cs(
                query=arguments.get("query", ""),
                industry=arguments.get("industry", ""),
                material=arguments.get("material", ""),
                machine_type=arguments.get("machine_type", ""),
                application=arguments.get("application", ""),
                country=arguments.get("country", ""),
                format=arguments.get("format", "paragraph"),
                context=context,
            )
        except Exception as e:
            logger.warning("find_case_studies failed: %s", e)
            return f"(Case study search error: {e})"

    elif tool_name == "build_case_study":
        query = arguments.get("query", "")
        try:
            from openclaw.agents.ira.src.agents.cadmus import build_case_study as _build_cs
            return await _build_cs(query, context)
        except Exception as e:
            logger.warning("build_case_study failed: %s", e)
            return f"(Case study build error: {e})"

    elif tool_name == "draft_linkedin_post":
        try:
            from openclaw.agents.ira.src.agents.cadmus import draft_linkedin_post as _draft_li
            return await _draft_li(
                topic=arguments.get("topic", ""),
                case_study_id=arguments.get("case_study_id", ""),
                post_type=arguments.get("post_type", "customer_story"),
                context=context,
            )
        except Exception as e:
            logger.warning("draft_linkedin_post failed: %s", e)
            return f"(LinkedIn post draft error: {e})"

    elif tool_name == "draft_linkedin_post_with_visuals":
        try:
            from openclaw.agents.ira.src.agents.cadmus import draft_linkedin_post_with_visuals as _draft_li_vis
            return await _draft_li_vis(
                topic=arguments.get("topic", ""),
                case_study_id=arguments.get("case_study_id", ""),
                post_type=arguments.get("post_type", "customer_story"),
                visual_style=arguments.get("visual_style", "carousel"),
                context=context,
            )
        except Exception as e:
            logger.warning("draft_linkedin_post_with_visuals failed: %s", e)
            return f"(LinkedIn post with visuals error: {e})"

    elif tool_name == "content_calendar":
        try:
            from openclaw.agents.ira.src.agents.arachne import content_calendar as _content_cal
            return await _content_cal(
                action=arguments.get("action", "view"),
                channel=arguments.get("channel", ""),
                scheduled_date=arguments.get("scheduled_date", ""),
                title=arguments.get("title", ""),
                content_ref=arguments.get("content_ref", ""),
                item_id=arguments.get("item_id", ""),
                context=context,
            )
        except Exception as e:
            logger.warning("content_calendar failed: %s", e)
            return f"(Content calendar error: {e})"

    elif tool_name == "assemble_newsletter":
        try:
            from openclaw.agents.ira.src.agents.arachne import assemble_newsletter_tool as _assemble_nl
            return await _assemble_nl(
                title=arguments.get("title", ""),
                sections=arguments.get("sections", ""),
                dry_run=arguments.get("dry_run", True),
                context=context,
            )
        except Exception as e:
            logger.warning("assemble_newsletter failed: %s", e)
            return f"(Newsletter assembly error: {e})"

    elif tool_name == "distribution_status":
        try:
            from openclaw.agents.ira.src.agents.arachne import distribution_status as _dist_status
            return await _dist_status(
                channel=arguments.get("channel", ""),
                context=context,
            )
        except Exception as e:
            logger.warning("distribution_status failed: %s", e)
            return f"(Distribution status error: {e})"

    return f"Error: Unknown tool '{tool_name}'"


_TOOL_SCHEMAS: Dict[str, Dict[str, type]] = {
    "send_email": {"to": str, "subject": str, "body": str, "thread_id": str},
    "draft_email": {"to": str, "subject": str, "intent": str, "context": str},
    "run_analysis": {"task": str, "code": str, "data": str},
    "read_spreadsheet": {"spreadsheet_id": str, "range": str},
    "search_email": {"query": str, "max_results": int},
    "customer_lookup": {"query": str},
    "search_contacts": {"query": str},
    "lead_intelligence": {"company": str, "context": str},
    "build_quote_pdf": {"width_mm": int, "height_mm": int, "variant": str, "customer_name": str, "company_name": str, "customer_email": str, "country": str},
    "build_quote_pdf_multi": {"line_items": list, "customer_name": str, "company_name": str, "customer_email": str, "country": str, "version": str},
    "recommend_machine": {"application": str, "material": str, "thickness_mm": float, "sheet_width_mm": int, "sheet_length_mm": int, "depth_mm": int, "budget_inr": int, "needs_grain": bool, "needs_pressure": bool},
    "rushabh_voice": {"customer_message": str, "company": str, "context": str},
    "latest_news": {"query": str, "country": str, "category": str},
    "log_sales_training": {"title": str, "trigger": str, "wrong_approach": str, "right_approach": str, "example": str, "tool_chain": str},
    "training_effectiveness": {},
    "ask_librarian": {"query": str, "full_text_in_body": bool},
    "browse_archive": {"folder": str, "doc_type": str},
    "file_detail": {"filename": str},
    "find_case_studies": {"query": str, "industry": str, "material": str, "machine_type": str, "application": str, "country": str, "format": str},
    "build_case_study": {"query": str},
    "draft_linkedin_post": {"topic": str, "case_study_id": str, "post_type": str},
    "draft_linkedin_post_with_visuals": {"topic": str, "case_study_id": str, "post_type": str, "visual_style": str},
    "content_calendar": {"action": str, "channel": str, "scheduled_date": str, "title": str, "content_ref": str, "item_id": str},
    "assemble_newsletter": {"title": str, "sections": str, "dry_run": bool},
    "distribution_status": {"channel": str},
    "preview_outreach": {},
    "sales_outreach": {"dry_run": bool},
    "classify_leads": {"days": int},
    "craft_email_for_lead": {"lead_id": str},
    "crm_export_leads": {"format": str, "include_contacts": bool},
    "discovery_sweep": {"industries": str},
    "actuals_vs_targets": {},
    "budget_alerts": {},
    "finance_export": {"format": str},
    "draft_project_status_email": {"query": str},
    "milestone_alerts": {},
    "suggest_content_topics": {"query": str},
    "po_draft": {"vendor_name": str, "line_items": str},
    "vendor_reliability": {},
    "employee_lookup": {"query": str},
    "hr_dashboard": {},
    "hr_policies": {},
    "skill_matrix": {"export_csv": bool},
    "recurring_quality_patterns": {"feed_to_nemesis": bool},
}

_MAX_ARG_LENGTH = 16000


def _validate_tool_args(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Validate tool arguments against schemas. Returns error string or None."""
    schema = _TOOL_SCHEMAS.get(tool_name)
    if not schema:
        return None
    for key, val in args.items():
        if key not in schema:
            continue
        expected = schema[key]
        if not isinstance(val, expected):
            return f"Argument '{key}' must be {expected.__name__}, got {type(val).__name__}"
        if isinstance(val, str) and len(val) > _MAX_ARG_LENGTH:
            return f"Argument '{key}' exceeds max length ({len(val)} > {_MAX_ARG_LENGTH})"
    return None


def parse_tool_arguments(arguments: str) -> Dict[str, Any]:
    """Parse tool arguments from LLM response (JSON string)."""
    if not arguments or not arguments.strip():
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse tool arguments (len=%d): %s — raw: %.200s", len(arguments), e, arguments)
        return {"_parse_error": str(e)}
