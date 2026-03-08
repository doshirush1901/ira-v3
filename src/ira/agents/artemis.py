"""Artemis — Mailbox Intelligence & Lead Hunter agent.

Scans historical email at scale, extracts sales intelligence, and
produces structured reports across four categories:

1. Customer journeys (how they became customers, conversation map)
2. Delivered machines (specs, price, delivery, open issues)
3. Hot leads (quotes sent, last interaction, days since contact)
4. Missed leads (inbound emails that never got a reply)

Artemis works with:
- **Alexandros** — seeds the scan with known accounts from inquiry forms,
  lead lists, customer spreadsheets, and exhibition data in data/imports/
- **Delphi** — classifies individual high-value emails (Artemis only
  delegates emails that pass batch triage, not all 40k)
- **Clio** — enriches analysis with KB context (machine specs, order history)
- **Prometheus** — receives enriched lead/deal data for pipeline updates

Key innovation: batch triage.  Instead of running a full ReAct loop per
email, Artemis classifies emails in batches of 20 with a single
lightweight LLM call, reducing 40k Delphi calls to ~2k batch calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ira.agents.base_agent import AgentTool, BaseAgent
from ira.prompt_loader import load_prompt
from ira.service_keys import ServiceKey as SK

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("artemis_system")

_BATCH_TRIAGE_PROMPT = """You are a fast email triage classifier for Machinecraft, an industrial machinery company.

Given a batch of email summaries (subject + sender + snippet), classify each as:
- BUSINESS_HIGH: Quote, proposal, pricing, machine inquiry, order, delivery, support issue, complaint — MUST be processed
- BUSINESS_LOW: General business correspondence, meeting scheduling, internal updates — process if time permits
- NOISE: Newsletter, notification, marketing, social media, automated, personal — skip entirely

Return ONLY valid JSON — an array of objects with "id" and "category":
[{"id": "msg_001", "category": "BUSINESS_HIGH"}, ...]

Be aggressive about filtering noise. Machinecraft sells thermoforming machines (PF1, PF2, ATF, AM, IMG, FCS, SAM models).
Any email mentioning these models, "quote", "proposal", "pricing", "order", "delivery", "thermoform", or "vacuum form" is BUSINESS_HIGH.
"""


class Artemis(BaseAgent):
    name = "artemis"
    role = "Mailbox Intelligence & Lead Hunter"
    description = (
        "Scans historical email at scale, extracts sales intelligence, "
        "builds customer journey maps, detects missed leads, and produces "
        "structured CRM reports. Works with Alexandros for seed data."
    )
    knowledge_categories = [
        "sales_and_crm",
        "leads_and_contacts",
        "quotes_and_proposals",
        "orders_and_pos",
    ]

    @property
    def _crm(self) -> Any | None:
        return self._services.get(SK.CRM)

    @property
    def _email_processor(self) -> Any | None:
        return self._services.get(SK.EMAIL_PROCESSOR)

    def _register_default_tools(self) -> None:
        super()._register_default_tools()

        self.register_tool(AgentTool(
            name="batch_triage_emails",
            description=(
                "Classify a batch of email summaries (up to 20) as "
                "BUSINESS_HIGH, BUSINESS_LOW, or NOISE in a single LLM call. "
                "Input: JSON array of {id, subject, from, snippet}."
            ),
            parameters={"batch_json": "JSON array of email summaries"},
            handler=self._tool_batch_triage,
        ))

        self.register_tool(AgentTool(
            name="get_seed_accounts",
            description=(
                "Ask Alexandros to extract company names, contact emails, and "
                "machine models from inquiry forms, lead lists, customer "
                "spreadsheets, and exhibition data in data/imports/. Returns "
                "a list of known accounts to search for in the mailbox."
            ),
            parameters={"query": "What kind of accounts to look for"},
            handler=self._tool_get_seed_accounts,
        ))

        self.register_tool(AgentTool(
            name="search_mailbox",
            description=(
                "Search Gmail for emails matching a query (from address, "
                "subject keywords, date range). Returns parsed email summaries."
            ),
            parameters={
                "query": "Gmail search query or keywords",
                "after": "Start date YYYY/MM/DD (optional)",
                "before": "End date YYYY/MM/DD (optional)",
                "max_results": "Max results to return (default 20)",
            },
            handler=self._tool_search_mailbox,
        ))

        self.register_tool(AgentTool(
            name="analyze_thread",
            description=(
                "Fetch and analyze a full email thread by thread_id. Returns "
                "the conversation arc: participants, timeline, key decisions, "
                "machine models mentioned, pricing, and current status."
            ),
            parameters={"thread_id": "Gmail thread ID"},
            handler=self._tool_analyze_thread,
        ))

        if self._crm:
            self.register_tool(AgentTool(
                name="get_crm_contacts",
                description=(
                    "List CRM contacts filtered by type (LIVE_CUSTOMER, "
                    "PAST_CUSTOMER, LEAD_WITH_INTERACTIONS, LEAD_NO_INTERACTIONS)."
                ),
                parameters={"contact_type": "Contact type filter (optional)"},
                handler=self._tool_get_crm_contacts,
            ))

            self.register_tool(AgentTool(
                name="get_contact_history",
                description=(
                    "Get full interaction history for a contact by email address: "
                    "deals, interactions, company info."
                ),
                parameters={"email": "Contact email address"},
                handler=self._tool_get_contact_history,
            ))

            self.register_tool(AgentTool(
                name="get_pipeline_deals",
                description=(
                    "Get all deals at a specific stage or all stages. Returns "
                    "deal title, value, machine model, stage, and dates."
                ),
                parameters={"stage": "Deal stage filter (optional, e.g. PROPOSAL)"},
                handler=self._tool_get_pipeline_deals,
            ))

            self.register_tool(AgentTool(
                name="get_stale_leads",
                description="Get leads with no interaction in the last N days.",
                parameters={"days": "Days of inactivity (default 30)"},
                handler=self._tool_get_stale_leads,
            ))

        self.register_tool(AgentTool(
            name="ask_alexandros",
            description=(
                "Ask Alexandros to search the document archive for customer "
                "data, inquiry forms, order books, quote documents, or lead "
                "lists. Alexandros has 700+ catalogued files."
            ),
            parameters={"question": "What to search for in the archive"},
            handler=self._tool_ask_alexandros,
        ))

        self.register_tool(AgentTool(
            name="ask_delphi",
            description=(
                "Ask Delphi to classify a single email's intent, urgency, "
                "and suggested agent. Use only for high-value emails that "
                "need deep classification."
            ),
            parameters={"email_body": "Email body text", "subject": "Email subject"},
            handler=self._tool_ask_delphi,
        ))

        self.register_tool(AgentTool(
            name="ask_prometheus",
            description=(
                "Ask Prometheus about the sales pipeline, deal status, "
                "revenue data, or lead qualification."
            ),
            parameters={"question": "Sales/pipeline question"},
            handler=self._tool_ask_prometheus,
        ))

    # ── Tool implementations ─────────────────────────────────────────────

    async def _tool_batch_triage(self, batch_json: str) -> str:
        """Classify a batch of email summaries in a single LLM call."""
        try:
            batch = json.loads(batch_json) if isinstance(batch_json, str) else batch_json
        except (json.JSONDecodeError, TypeError):
            return '{"error": "Invalid JSON input"}'

        summaries = []
        for item in batch[:20]:
            summaries.append(
                f"ID: {item.get('id', '?')} | "
                f"From: {item.get('from', '?')} | "
                f"Subject: {item.get('subject', '?')} | "
                f"Snippet: {item.get('snippet', '')[:150]}"
            )

        prompt = _BATCH_TRIAGE_PROMPT + "\n\nEMAILS:\n" + "\n".join(summaries)

        result = await self._llm.generate_text(
            prompt=prompt,
            system="You are a fast email classifier. Return only valid JSON.",
            temperature=0.0,
            max_tokens=1000,
        )
        return result

    async def _tool_get_seed_accounts(self, query: str) -> str:
        """Ask Alexandros for known accounts from the document archive."""
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available — cannot reach Alexandros."

        alexandros = pantheon.get_agent("alexandros")
        if not alexandros:
            return "Alexandros agent not available."

        result = await alexandros.handle(
            f"Search the archive for {query}. Focus on folders: "
            "07_Leads_and_Contacts, 01_Quotes_and_Proposals, 02_Orders_and_POs, "
            "08_Sales_and_CRM. Extract company names, contact emails, machine "
            "models mentioned, and any inquiry/lead details. Return as a "
            "structured list.",
            {"task": "search", "doc_types": ["lead_list", "customer_data", "quote", "order"]},
        )
        return result

    async def _tool_search_mailbox(
        self,
        query: str,
        after: str = "",
        before: str = "",
        max_results: str = "20",
    ) -> str:
        """Search Gmail via the EmailProcessor."""
        ep = self._email_processor
        if not ep:
            return "EmailProcessor not available."

        try:
            limit = int(max_results)
        except (ValueError, TypeError):
            limit = 20

        emails = await ep.search_emails(
            query=query,
            after=after,
            before=before,
            max_results=min(limit, 50),
        )

        if not emails:
            return "No emails found."

        lines = []
        for e in emails:
            lines.append(
                f"- [{e.received_at.strftime('%Y-%m-%d')}] "
                f"From: {e.from_address} | "
                f"Subject: {e.subject} | "
                f"Thread: {e.thread_id or 'N/A'} | "
                f"Snippet: {e.body[:120].replace(chr(10), ' ')}"
            )
        return "\n".join(lines)

    async def _tool_analyze_thread(self, thread_id: str) -> str:
        """Fetch a thread and produce a conversation arc summary."""
        ep = self._email_processor
        if not ep:
            return "EmailProcessor not available."

        emails = await ep.get_thread(thread_id)
        if not emails:
            return f"No messages found in thread {thread_id}."

        messages = []
        for e in emails:
            messages.append(
                f"[{e.received_at.strftime('%Y-%m-%d %H:%M')}] "
                f"From: {e.from_address} → To: {e.to_address}\n"
                f"Subject: {e.subject}\n"
                f"Body: {e.body[:500]}\n"
            )

        thread_text = "\n---\n".join(messages)

        summary = await self._llm.generate_text(
            prompt=(
                f"Analyze this email thread from Machinecraft (industrial machinery).\n\n"
                f"{thread_text}\n\n"
                "Return a structured summary:\n"
                "1. Participants (names, companies, roles)\n"
                "2. Timeline (key dates and what happened)\n"
                "3. Machine models mentioned (PF1, PF2, ATF, AM, IMG, FCS, SAM)\n"
                "4. Pricing/value discussed\n"
                "5. Current status (won, lost, pending, no response)\n"
                "6. Next action recommended"
            ),
            system="You are a sales intelligence analyst for Machinecraft.",
            temperature=0.1,
            max_tokens=1500,
        )
        return summary

    async def _tool_get_crm_contacts(self, contact_type: str = "") -> str:
        """List CRM contacts, optionally filtered by type."""
        if not self._crm:
            return "CRM not available."

        filters = {}
        if contact_type:
            filters["contact_type"] = contact_type

        contacts = await self._crm.list_contacts(filters or None)
        if not contacts:
            return "No contacts found."

        lines = []
        for c in contacts[:50]:
            ct = c.contact_type.value if c.contact_type else "?"
            lines.append(
                f"- {c.name} <{c.email}> | Type: {ct} | "
                f"Score: {c.lead_score:.0f} | Source: {c.source or '?'}"
            )
        return f"{len(contacts)} contacts total (showing first {min(len(contacts), 50)}):\n" + "\n".join(lines)

    async def _tool_get_contact_history(self, email: str) -> str:
        """Get full history for a contact."""
        if not self._crm:
            return "CRM not available."

        contact = await self._crm.get_contact_by_email(email.strip().lower())
        if not contact:
            return f"No contact found for {email}."

        parts = [
            f"Name: {contact.name}",
            f"Email: {contact.email}",
            f"Type: {contact.contact_type.value if contact.contact_type else '?'}",
            f"Score: {contact.lead_score:.0f}",
            f"Source: {contact.source or '?'}",
        ]

        deals = await self._crm.get_deals_for_contact(str(contact.id))
        if deals:
            parts.append(f"\nDeals ({len(deals)}):")
            for d in deals:
                parts.append(
                    f"  - {d.get('title', '?')} | Stage: {d.get('stage', '?')} | "
                    f"Value: {d.get('currency', 'USD')} {d.get('value', 0):,.0f} | "
                    f"Machine: {d.get('machine_model', '?')}"
                )

        interactions = await self._crm.get_interactions_for_contact(str(contact.id))
        if interactions:
            parts.append(f"\nInteractions ({len(interactions)}, showing last 10):")
            for ix in interactions[:10]:
                parts.append(
                    f"  - [{ix.get('created_at', '?')[:10]}] "
                    f"{ix.get('channel', '?')} {ix.get('direction', '?')} | "
                    f"{ix.get('subject', '?')}"
                )

        return "\n".join(parts)

    async def _tool_get_pipeline_deals(self, stage: str = "") -> str:
        """Get deals, optionally filtered by stage."""
        if not self._crm:
            return "CRM not available."

        filters = {}
        if stage:
            filters["stage"] = stage

        deals = await self._crm.list_deals(filters or None)
        if not deals:
            return "No deals found."

        lines = []
        for d in deals[:50]:
            lines.append(
                f"- {d.title} | Stage: {d.stage.value if d.stage else '?'} | "
                f"Value: {d.currency} {float(d.value):,.0f} | "
                f"Machine: {d.machine_model or '?'} | "
                f"Created: {d.created_at.strftime('%Y-%m-%d') if d.created_at else '?'}"
            )
        return f"{len(deals)} deals total:\n" + "\n".join(lines)

    async def _tool_get_stale_leads(self, days: str = "30") -> str:
        """Get leads with no recent interaction."""
        if not self._crm:
            return "CRM not available."

        try:
            d = int(days)
        except (ValueError, TypeError):
            d = 30

        stale = await self._crm.get_stale_leads(days=d)
        if not stale:
            return f"No stale leads (>{d} days)."

        lines = []
        for s in stale[:30]:
            lines.append(f"- {s.get('name', '?')} <{s.get('email', '?')}>")
        return f"{len(stale)} stale leads (>{d} days):\n" + "\n".join(lines)

    async def _tool_ask_alexandros(self, question: str) -> str:
        """Delegate to Alexandros for archive search."""
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available."

        alexandros = pantheon.get_agent("alexandros")
        if not alexandros:
            return "Alexandros not available."

        return await alexandros.handle(question)

    async def _tool_ask_delphi(self, email_body: str, subject: str = "") -> str:
        """Delegate to Delphi for deep email classification."""
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available."

        delphi = pantheon.get_agent("delphi")
        if not delphi:
            return "Delphi not available."

        return await delphi.handle(
            email_body[:2000],
            {"subject": subject, "task": "classify_email"},
        )

    async def _tool_ask_prometheus(self, question: str) -> str:
        """Delegate to Prometheus for pipeline/sales data."""
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon not available."

        prometheus = pantheon.get_agent("prometheus")
        if not prometheus:
            return "Prometheus not available."

        return await prometheus.handle(question)

    # ── Handle ───────────────────────────────────────────────────────────

    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        task = ctx.get("task", "")

        if task == "batch_triage":
            return await self._tool_batch_triage(ctx.get("batch", "[]"))

        return await self.run(query, ctx, system_prompt=_SYSTEM_PROMPT)
