"""Skill matrix and public API for the Ira skills subsystem.

Each key in :data:`SKILL_MATRIX` is a snake_case skill name that maps to a
human-readable description.  The corresponding async handler lives in
:mod:`ira.skills.handlers` under the same name.
"""

from __future__ import annotations

SKILL_MATRIX: dict[str, str] = {
    # ── Research & Knowledge ─────────────────────────────────────────────
    "summarize_document": (
        "Condense a long document into a concise executive summary."
    ),
    "extract_key_facts": (
        "Pull structured facts, figures, and dates from unstructured text."
    ),
    "compare_documents": (
        "Highlight differences and similarities between two or more documents."
    ),
    "search_knowledge_base": (
        "Query the internal knowledge base for relevant information."
    ),
    # ── Sales & CRM ──────────────────────────────────────────────────────
    "draft_outreach_email": (
        "Compose a personalised cold-outreach or follow-up email for a lead."
    ),
    "qualify_lead": (
        "Score and qualify an inbound lead based on firmographic data."
    ),
    "generate_deal_summary": (
        "Produce a one-page summary of a deal's status, history, and next steps."
    ),
    "update_crm_record": (
        "Push structured updates (stage changes, notes) to a CRM record."
    ),
    # ── Finance & Pricing ────────────────────────────────────────────────
    "calculate_quote": (
        "Build a line-item quote from product specs and pricing rules."
    ),
    "analyze_revenue": (
        "Aggregate and break down revenue figures by period, product, or region."
    ),
    "forecast_pipeline": (
        "Project future revenue from the current sales pipeline."
    ),
    "generate_invoice": (
        "Create a formatted invoice from a confirmed quote or order."
    ),
    # ── Marketing & Campaigns ────────────────────────────────────────────
    "create_drip_sequence": (
        "Design a multi-step email drip campaign for a target segment."
    ),
    "generate_social_post": (
        "Draft a social-media post tailored to a specific platform and audience."
    ),
    "build_lead_report": (
        "Compile a lead-intelligence report with firmographic and intent data."
    ),
    "schedule_campaign": (
        "Set timing and delivery parameters for a marketing campaign."
    ),
    # ── Writing & Communication ──────────────────────────────────────────
    "draft_proposal": (
        "Write a structured business proposal from a brief or template."
    ),
    "polish_text": (
        "Improve grammar, tone, and clarity of a given piece of text."
    ),
    "translate_text": (
        "Translate text between supported languages while preserving tone."
    ),
    "generate_meeting_notes": (
        "Produce structured meeting minutes from a transcript or summary."
    ),
    # ── Production & HR ──────────────────────────────────────────────────
    "lookup_machine_spec": (
        "Retrieve technical specifications for a given machine or part number."
    ),
    "estimate_production_time": (
        "Calculate estimated production lead time for a given order."
    ),
    "lookup_employee": (
        "Retrieve employee profile, role, and contact information."
    ),
    "generate_org_chart": (
        "Build an organisational chart from current HR data."
    ),
}
