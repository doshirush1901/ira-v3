"""Async handler functions for every skill in the SKILL_MATRIX.

Each function accepts arbitrary keyword arguments and returns a status
string.  The :func:`use_skill` dispatcher at the bottom of this module
is the single entry-point used by agents.

Services (CRM, PricingEngine, retriever, etc.) are injected at startup
via :func:`bind_services`.  Handlers that need a service gracefully
degrade when it isn't available.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.skills import SKILL_MATRIX

logger = logging.getLogger(__name__)

_SERVICES: dict[str, Any] = {}


def bind_services(services: dict[str, Any]) -> None:
    """Called once at startup to make shared services available to handlers."""
    _SERVICES.update(services)
    logger.info("Skill handlers bound to services: %s", sorted(services))


def _svc(name: str) -> Any | None:
    return _SERVICES.get(name)


async def _llm_call(system: str, user: str, *, temperature: float = 0.3) -> str:
    """Shared LLM helper with automatic Anthropic fallback."""
    import httpx
    from ira.config import get_settings

    settings = get_settings()
    openai_key = settings.llm.openai_api_key.get_secret_value()
    anthropic_key = settings.llm.anthropic_api_key.get_secret_value()

    if openai_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": settings.llm.openai_model,
                        "temperature": temperature,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user[:12_000]},
                        ],
                    },
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            logger.warning("OpenAI call failed in skill handler — trying Anthropic fallback")

    if anthropic_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": settings.llm.anthropic_model,
                        "max_tokens": 4096,
                        "system": system,
                        "messages": [{"role": "user", "content": user[:12_000]}],
                        "temperature": temperature,
                    },
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]
        except Exception:
            logger.exception("Anthropic fallback also failed in skill handler")

    return "(LLM call failed — no provider available)"


# ── Research & Knowledge ─────────────────────────────────────────────────


async def summarize_document(**kwargs: Any) -> str:
    text = kwargs.get("text", "")
    if not text:
        return "Error: 'text' argument required"

    retriever = _svc("retriever")
    context = ""
    if retriever:
        results = await retriever.search(text[:500], limit=3)
        context = "\n".join(r.get("content", "")[:300] for r in results)

    return await _llm_call(
        "You are a document summarization specialist. Produce a concise executive "
        "summary capturing the key points, decisions, and action items.",
        f"Document to summarize ({len(text)} chars):\n\n{text[:8000]}"
        + (f"\n\nRelated context from knowledge base:\n{context}" if context else ""),
    )


async def extract_key_facts(**kwargs: Any) -> str:
    text = kwargs.get("text", "")
    if not text:
        return "Error: 'text' argument required"

    return await _llm_call(
        "Extract structured facts from the text. Return a JSON object with keys: "
        "companies (list), people (list of {name, role, email}), machines (list), "
        "prices (list of {item, amount, currency}), dates (list of {event, date}), "
        "key_decisions (list of strings).",
        f"Text to extract from:\n\n{text[:8000]}",
        temperature=0.1,
    )


async def compare_documents(**kwargs: Any) -> str:
    docs = kwargs.get("documents", [])
    if len(docs) < 2:
        return "Error: at least 2 documents required in 'documents' list"

    formatted = "\n\n---\n\n".join(
        f"DOCUMENT {i+1}:\n{d[:4000]}" for i, d in enumerate(docs)
    )

    return await _llm_call(
        "Compare the provided documents. Identify: (1) key differences, "
        "(2) common elements, (3) contradictions if any, (4) which is more "
        "recent or authoritative. Use a structured format.",
        formatted,
    )


async def search_knowledge_base(**kwargs: Any) -> str:
    retriever = _svc("retriever")
    query = kwargs.get("query", "")
    if not query:
        return "Error: 'query' argument required"
    if not retriever:
        return "Knowledge base not available"

    limit = kwargs.get("limit", 10)
    category = kwargs.get("category")

    if category:
        results = await retriever.search_by_category(query, category, limit=limit)
    else:
        results = await retriever.search(query, limit=limit)

    if not results:
        return f"No results found for: {query}"

    lines = [f"Found {len(results)} results for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. [{r.get('source', 'unknown')}] "
            f"{r.get('content', '')[:300]}"
        )
    return "\n".join(lines)


# ── Sales & CRM ──────────────────────────────────────────────────────────


async def draft_outreach_email(**kwargs: Any) -> str:
    contact_email = kwargs.get("email", "")
    company = kwargs.get("company", "")
    stage = kwargs.get("stage", "INTRO")
    region = kwargs.get("region", "")
    context_notes = kwargs.get("context", "")

    retriever = _svc("retriever")
    crm = _svc("crm")

    crm_context = ""
    if crm and contact_email:
        contact = await crm.get_contact_by_email(contact_email)
        if contact:
            deals = await crm.get_deals_for_contact(str(contact.id))
            interactions = await crm.get_interactions_for_contact(str(contact.id))
            crm_context = (
                f"Contact: {contact.name} ({contact.email})\n"
                f"Company: {contact.company_id or 'N/A'}\n"
                f"Deals: {len(deals)} | Interactions: {len(interactions)}\n"
                f"Lead score: {contact.lead_score}"
            )

    kb_context = ""
    if retriever:
        search_term = company or contact_email or "Machinecraft outreach"
        results = await retriever.search(
            f"customer reference {search_term} thermoforming", limit=5,
        )
        kb_context = "\n".join(r.get("content", "")[:300] for r in results)

    regional_tones = {
        "germany": "formal, precise, engineering-focused",
        "india": "warm, relationship-first",
        "middle_east": "respectful, relationship-building",
        "usa": "professional, results-oriented",
        "europe": "professional, consultative",
    }
    tone = regional_tones.get(region.lower(), "professional, consultative")

    return await _llm_call(
        "You are a B2B sales email specialist for Machinecraft, an industrial "
        "thermoforming machine manufacturer. Write compelling, personalised "
        "outreach emails that demonstrate domain expertise.",
        f"Draft a {stage} stage outreach email.\n\n"
        f"Recipient: {contact_email or 'unknown'}\n"
        f"Company: {company or 'unknown'}\n"
        f"Regional tone: {tone}\n"
        f"Additional context: {context_notes}\n\n"
        f"CRM data:\n{crm_context or '(none)'}\n\n"
        f"Reference material:\n{kb_context or '(none)'}",
        temperature=0.5,
    )


async def qualify_lead(**kwargs: Any) -> str:
    crm = _svc("crm")
    email = kwargs.get("email", "")
    if not email:
        return "Error: 'email' argument required"
    if not crm:
        return "CRM not available for lead qualification"

    contact = await crm.get_contact_by_email(email)
    if not contact:
        return f"No contact found for {email}"

    deals = await crm.get_deals_for_contact(str(contact.id))
    interactions = await crm.get_interactions_for_contact(str(contact.id))

    return json.dumps({
        "contact": contact.to_dict(),
        "deal_count": len(deals),
        "interaction_count": len(interactions),
        "lead_score": contact.lead_score,
        "warmth": contact.warmth_level.value if contact.warmth_level else "unknown",
    }, default=str, indent=2)


async def generate_deal_summary(**kwargs: Any) -> str:
    crm = _svc("crm")
    deal_id = kwargs.get("deal_id", "")
    contact_email = kwargs.get("email", "")

    if not crm:
        return "CRM not available"

    if deal_id:
        deal = await crm.get_deal(deal_id)
        if not deal:
            return f"Deal {deal_id} not found"
        return json.dumps(deal.to_dict(), default=str, indent=2)

    if contact_email:
        contact = await crm.get_contact_by_email(contact_email)
        if not contact:
            return f"No contact found for {contact_email}"
        deals = await crm.get_deals_for_contact(str(contact.id))
        if not deals:
            return f"No deals found for {contact_email}"
        return json.dumps(deals, default=str, indent=2)

    return "Error: 'deal_id' or 'email' argument required"


async def update_crm_record(**kwargs: Any) -> str:
    crm = _svc("crm")
    if not crm:
        return "CRM not available"

    record_type = kwargs.get("type", "")
    record_id = kwargs.get("id", "")
    updates = kwargs.get("updates", {})

    if not record_type or not record_id or not updates:
        return "Error: 'type', 'id', and 'updates' arguments required"

    if record_type == "deal":
        result = await crm.update_deal(record_id, **updates)
    elif record_type == "contact":
        result = await crm.update_contact(record_id, **updates)
    elif record_type == "company":
        result = await crm.update_company(record_id, **updates)
    else:
        return f"Unknown record type: {record_type}"

    if result is None:
        return f"{record_type} {record_id} not found"
    return f"Updated {record_type} {record_id} successfully"


# ── Finance & Pricing ────────────────────────────────────────────────────


async def calculate_quote(**kwargs: Any) -> str:
    pricing = _svc("pricing_engine")
    if not pricing:
        return "Pricing engine not available"

    machine_model = kwargs.get("machine_model", "")
    configuration = kwargs.get("configuration", {})

    if not machine_model:
        return "Error: 'machine_model' argument required"

    estimate = await pricing.estimate_price(machine_model, configuration)
    return json.dumps(estimate, default=str, indent=2)


async def analyze_revenue(**kwargs: Any) -> str:
    crm = _svc("crm")
    if not crm:
        return "CRM not available for revenue analysis"

    summary = await crm.get_pipeline_summary(kwargs.get("filters"))
    velocity = await crm.get_deal_velocity()
    return json.dumps({"pipeline": summary, "velocity": velocity}, default=str, indent=2)


async def forecast_pipeline(**kwargs: Any) -> str:
    crm = _svc("crm")
    if not crm:
        return "CRM not available for pipeline forecasting"

    summary = await crm.get_pipeline_summary()
    quotes_mgr = _svc("quotes")
    analytics = {}
    if quotes_mgr:
        analytics = await quotes_mgr.get_quote_analytics()

    return json.dumps({
        "pipeline_summary": summary,
        "quote_analytics": analytics,
    }, default=str, indent=2)


async def generate_invoice(**kwargs: Any) -> str:
    customer = kwargs.get("customer", "")
    quote_id = kwargs.get("quote_id", "")
    items = kwargs.get("items", [])

    if not customer:
        return "Error: 'customer' argument required"

    retriever = _svc("retriever")
    kb_context = ""
    if retriever and quote_id:
        results = await retriever.search(f"quote {quote_id} {customer}", limit=5)
        kb_context = "\n".join(r.get("content", "")[:400] for r in results)

    items_text = ""
    if items:
        items_text = "\n".join(
            f"  - {it.get('description', '?')}: {it.get('amount', '?')} {it.get('currency', 'USD')}"
            for it in items
        )

    return await _llm_call(
        "You are a finance specialist at Machinecraft. Generate a professional "
        "invoice document in markdown format with proper line items, taxes, "
        "payment terms, and bank details placeholder.",
        f"Generate an invoice for:\n"
        f"Customer: {customer}\n"
        f"Quote reference: {quote_id or 'N/A'}\n"
        f"Line items:\n{items_text or '(derive from quote data)'}\n\n"
        f"Quote/order data:\n{kb_context or '(none)'}",
    )


# ── Marketing & Campaigns ────────────────────────────────────────────────


async def create_drip_sequence(**kwargs: Any) -> str:
    contact_email = kwargs.get("email", "")
    company = kwargs.get("company", "")
    region = kwargs.get("region", "")
    machine_interest = kwargs.get("machine", "")
    num_stages = kwargs.get("stages", 6)

    retriever = _svc("retriever")
    kb_context = ""
    if retriever:
        search_term = f"{company} {machine_interest} thermoforming".strip()
        results = await retriever.search(search_term, limit=5)
        kb_context = "\n".join(r.get("content", "")[:300] for r in results)

    return await _llm_call(
        "You are a B2B drip campaign designer for Machinecraft, an industrial "
        "thermoforming machine manufacturer. Design multi-stage email sequences "
        "that nurture leads from awareness to purchase decision.",
        f"Design a {num_stages}-stage drip campaign.\n\n"
        f"Target: {contact_email or 'segment'}\n"
        f"Company: {company or 'unknown'}\n"
        f"Region: {region or 'unknown'}\n"
        f"Machine interest: {machine_interest or 'general'}\n\n"
        f"For each stage provide:\n"
        f"1. Stage name and goal\n"
        f"2. Days after previous email\n"
        f"3. Subject line\n"
        f"4. Email body\n"
        f"5. CTA (call to action)\n\n"
        f"Reference material:\n{kb_context or '(none)'}",
        temperature=0.5,
    )


async def generate_social_post(**kwargs: Any) -> str:
    topic = kwargs.get("topic", "")
    platform = kwargs.get("platform", "linkedin")
    if not topic:
        return "Error: 'topic' argument required"

    retriever = _svc("retriever")
    kb_context = ""
    if retriever:
        results = await retriever.search(topic, limit=5)
        kb_context = "\n".join(r.get("content", "")[:300] for r in results)

    return await _llm_call(
        "You are a social media content specialist for Machinecraft, an industrial "
        "thermoforming machine manufacturer. Create engaging, professional posts "
        "that showcase domain expertise.",
        f"Draft a {platform} post about: {topic}\n\n"
        f"Guidelines:\n"
        f"- Professional but engaging tone\n"
        f"- 150-250 words for LinkedIn, shorter for Twitter\n"
        f"- Hook in the first line\n"
        f"- End with CTA or thought-provoking question\n"
        f"- 3-5 relevant hashtags\n\n"
        f"Reference material:\n{kb_context or '(none)'}",
        temperature=0.6,
    )


async def build_lead_report(**kwargs: Any) -> str:
    crm = _svc("crm")
    if not crm:
        return "CRM not available"

    stale = await crm.get_stale_leads(days=kwargs.get("days", 14))
    return json.dumps({
        "stale_leads": stale[:20],
        "total_stale": len(stale),
    }, default=str, indent=2)


async def schedule_campaign(**kwargs: Any) -> str:
    campaign_name = kwargs.get("name", "")
    target_segment = kwargs.get("segment", {})
    start_date = kwargs.get("start_date", "")

    if not campaign_name:
        return "Error: 'name' argument required"

    crm = _svc("crm")
    if crm:
        campaign = await crm.create_campaign(
            name=campaign_name,
            target_segment=target_segment,
        )
        return json.dumps({
            "status": "scheduled",
            "campaign_id": str(campaign.id),
            "name": campaign_name,
            "start_date": start_date or "immediate",
        }, default=str, indent=2)

    return json.dumps({
        "status": "planned",
        "name": campaign_name,
        "note": "CRM not available — campaign recorded but not persisted",
    })


# ── Writing & Communication ──────────────────────────────────────────────


async def draft_proposal(**kwargs: Any) -> str:
    customer = kwargs.get("customer", "")
    machine_model = kwargs.get("machine_model", "")
    context_notes = kwargs.get("context", "")

    if not customer:
        return "Error: 'customer' argument required"

    retriever = _svc("retriever")
    kb_context = ""
    if retriever:
        search_terms = [customer, machine_model, "proposal"]
        search_q = " ".join(t for t in search_terms if t)
        results = await retriever.search(search_q, limit=8)
        kb_context = "\n".join(r.get("content", "")[:400] for r in results)

    pricing_context = ""
    pricing = _svc("pricing_engine")
    if pricing and machine_model:
        try:
            estimate = await pricing.estimate_price(machine_model, {})
            ep = estimate.get("estimated_price", {})
            if ep:
                pricing_context = (
                    f"Price guidance: {ep.get('currency', 'USD')} "
                    f"{ep.get('low', '?')} – {ep.get('high', '?')} "
                    f"(mid: {ep.get('mid', '?')})"
                )
        except Exception:
            pass

    return await _llm_call(
        "You are a proposal writer for Machinecraft, an industrial thermoforming "
        "machine manufacturer. Write professional, compelling proposals that "
        "highlight technical capabilities and business value.",
        f"Draft a business proposal for:\n"
        f"Customer: {customer}\n"
        f"Machine: {machine_model or 'to be determined'}\n"
        f"Context: {context_notes}\n\n"
        f"Include sections:\n"
        f"1. Executive summary\n"
        f"2. Understanding of requirements\n"
        f"3. Proposed solution\n"
        f"4. Technical specifications\n"
        f"5. Pricing overview (use [TBD] for unconfirmed values)\n"
        f"6. Timeline and delivery\n"
        f"7. Why Machinecraft\n"
        f"8. Next steps\n\n"
        f"Pricing intelligence:\n{pricing_context or '(none)'}\n\n"
        f"Reference material:\n{kb_context or '(none)'}",
    )


async def polish_text(**kwargs: Any) -> str:
    text = kwargs.get("text", "")
    tone = kwargs.get("tone", "professional")
    if not text:
        return "Error: 'text' argument required"

    return await _llm_call(
        "You are a professional editor. Improve the grammar, clarity, tone, and "
        "flow of the text while preserving the original meaning and technical "
        "accuracy. Do not add information that isn't in the original.",
        f"Polish this text (target tone: {tone}):\n\n{text}",
    )


async def translate_text(**kwargs: Any) -> str:
    text = kwargs.get("text", "")
    target_language = kwargs.get("language", "")
    if not text or not target_language:
        return "Error: 'text' and 'language' arguments required"

    return await _llm_call(
        "You are a professional translator specializing in B2B industrial "
        "communication. Translate accurately while preserving technical terms, "
        "tone, and cultural appropriateness for the target audience.",
        f"Translate to {target_language}:\n\n{text}",
    )


async def generate_meeting_notes(**kwargs: Any) -> str:
    transcript = kwargs.get("transcript", kwargs.get("text", ""))
    attendees = kwargs.get("attendees", [])
    if not transcript:
        return "Error: 'transcript' or 'text' argument required"

    attendees_str = ", ".join(attendees) if attendees else "(not specified)"

    return await _llm_call(
        "You are a meeting notes specialist. Produce structured, actionable "
        "meeting minutes from the provided transcript or summary.",
        f"Generate meeting notes.\n\n"
        f"Attendees: {attendees_str}\n\n"
        f"Include:\n"
        f"1. Meeting summary (2-3 sentences)\n"
        f"2. Key discussion points\n"
        f"3. Decisions made\n"
        f"4. Action items (with owner and deadline if mentioned)\n"
        f"5. Open questions\n\n"
        f"Transcript/summary:\n{transcript[:8000]}",
    )


# ── Production & HR ──────────────────────────────────────────────────────


async def lookup_machine_spec(**kwargs: Any) -> str:
    retriever = _svc("retriever")
    machine = kwargs.get("machine_model", kwargs.get("query", ""))
    if not machine:
        return "Error: 'machine_model' or 'query' argument required"

    if retriever:
        results = await retriever.search_by_category(
            f"{machine} specifications technical specs",
            category="machine_manuals_and_specs",
            limit=5,
        )
        if results:
            lines = [f"Specs for {machine}:"]
            for r in results:
                lines.append(f"  - {r.get('content', '')[:400]}")
            return "\n".join(lines)

    try:
        import json as _json
        from pathlib import Path
        mk_path = Path("data/machine_knowledge.json")
        if mk_path.exists():
            data = _json.loads(mk_path.read_text())
            for m in data if isinstance(data, list) else []:
                if machine.upper() in (m.get("model", "")).upper():
                    return _json.dumps(m, indent=2)
    except Exception:
        pass

    return f"No specs found for {machine}"


async def estimate_production_time(**kwargs: Any) -> str:
    machine_model = kwargs.get("machine_model", "")
    configuration = kwargs.get("configuration", {})
    quantity = kwargs.get("quantity", 1)

    if not machine_model:
        return "Error: 'machine_model' argument required"

    retriever = _svc("retriever")
    kb_context = ""
    if retriever:
        results = await retriever.search(
            f"{machine_model} production lead time manufacturing delivery schedule",
            limit=8,
        )
        kb_context = "\n".join(r.get("content", "")[:400] for r in results)

    config_text = ", ".join(f"{k}: {v}" for k, v in configuration.items()) if configuration else "standard"

    return await _llm_call(
        "You are Machinecraft's production planning specialist. Estimate lead "
        "times based on machine complexity, current order book, and historical "
        "production data. Be specific about phases: design, procurement, "
        "fabrication, assembly, testing, shipping.",
        f"Estimate production time for:\n"
        f"Machine: {machine_model}\n"
        f"Configuration: {config_text}\n"
        f"Quantity: {quantity}\n\n"
        f"Production knowledge:\n{kb_context or '(none)'}",
    )


async def lookup_employee(**kwargs: Any) -> str:
    name = kwargs.get("name", kwargs.get("query", ""))
    if not name:
        return "Error: 'name' or 'query' argument required"

    retriever = _svc("retriever")
    if retriever:
        results = await retriever.search(
            f"employee {name} role contact team",
            limit=5,
        )
        if results:
            lines = [f"Employee lookup for '{name}':"]
            for r in results:
                lines.append(f"  - {r.get('content', '')[:300]}")
            return "\n".join(lines)

    return f"No employee data found for '{name}'"


async def generate_org_chart(**kwargs: Any) -> str:
    department = kwargs.get("department", "")

    retriever = _svc("retriever")
    kb_context = ""
    if retriever:
        query = f"organization structure team roles {department}".strip()
        results = await retriever.search(query, limit=10)
        kb_context = "\n".join(r.get("content", "")[:300] for r in results)

    return await _llm_call(
        "You are an HR specialist. Generate an organizational chart in text "
        "format showing reporting lines, roles, and team structure.",
        f"Generate an org chart{f' for {department}' if department else ''}.\n\n"
        f"Available data:\n{kb_context or '(no HR data available)'}",
    )


# ── Dispatcher ───────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    name: func
    for name in SKILL_MATRIX
    if (func := globals().get(name)) is not None and callable(func)
}


async def use_skill(skill_name: str, **kwargs: Any) -> str:
    """Look up *skill_name* in the handler registry and execute it.

    Raises :class:`ValueError` if the skill name is not recognised.
    """
    handler = _HANDLERS.get(skill_name)
    if handler is None:
        raise ValueError(
            f"Unknown skill '{skill_name}'. "
            f"Available skills: {sorted(SKILL_MATRIX)}"
        )
    return await handler(**kwargs)
