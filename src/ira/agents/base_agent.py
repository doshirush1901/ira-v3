"""Abstract base class for all Pantheon agents.

Every specialist agent inherits from :class:`BaseAgent`, which provides
LLM access (OpenAI and Anthropic) via the centralised
:class:`~ira.services.llm_client.LLMClient`, knowledge-base search via
the :class:`~ira.brain.retriever.UnifiedRetriever`, a reference to the
:class:`~ira.message_bus.MessageBus` for inter-agent communication,
and an opt-in ReAct (Reason-Act-Observe) loop for agentic tool use.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

import httpx
from langfuse.decorators import observe

from ira.brain.retriever import UnifiedRetriever
from ira.config import get_settings
from ira.exceptions import IraError, ToolExecutionError
from ira.message_bus import MessageBus
from ira.prompt_loader import load_prompt, load_soul_preamble
from ira.schemas.llm_outputs import ReActDecision
from ira.services.llm_client import LLMClient, get_llm_client
from ira.skills import SKILL_MATRIX
from ira.service_keys import ServiceKey as SK
from ira.skills.handlers import use_skill as _use_skill

logger = logging.getLogger(__name__)


# ── ReAct infrastructure ─────────────────────────────────────────────────


class AgentState(Enum):
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    RESPONDING = "responding"


@dataclass
class AgentTool:
    """A tool that an agent can invoke during its ReAct loop."""

    name: str
    description: str
    parameters: dict[str, str]  # param_name -> description
    handler: Callable[..., Awaitable[str]]


class BaseAgent(ABC):
    """Abstract base for every agent in the Pantheon."""

    name: str = "base"
    role: str = ""
    description: str = ""
    model_provider: str = "openai"  # "openai" or "anthropic"
    knowledge_categories: list[str] = []
    timeout: int | None = None
    created_at: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc)

    @property
    def age_in_days(self) -> int:
        """Days since this agent's creation (identity continuity)."""
        delta = datetime.now(timezone.utc) - self.created_at
        return max(0, delta.days)

    async def _compose_system_prompt(
        self,
        system_prompt: str = "",
        *,
        allow_default: bool = True,
    ) -> str:
        """Build a system prompt with SOUL preamble, identity (age), and latest journal."""
        prompt = system_prompt.strip()
        if not prompt and allow_default:
            prompt = (
                f"You are {self.name}, the {self.role} of the Machinecraft AI Pantheon. "
                f"{self.description}"
            )

        identity = f"You are {self.name}, the {self.role}. You are {self.age_in_days} days old."
        prompt = f"{identity}\n\n{prompt}"

        journal = None
        journal_svc = self._services.get(SK.AGENT_JOURNAL)
        if journal_svc is not None:
            try:
                journal = await journal_svc.get_latest_journal_entry(self.name)
            except Exception:
                logger.debug("Failed to get latest journal for %s", self.name, exc_info=True)
        if journal and journal.strip():
            prompt = f"{prompt}\n\nYour most recent journal entry:\n{journal.strip()}"

        sense_lost = {}
        immune = self._services.get(SK.IMMUNE)
        if immune is not None and hasattr(immune, "get_sense_lost"):
            try:
                sense_lost = immune.get_sense_lost()
            except Exception:
                pass
        if sense_lost:
            lost = [k for k, v in sense_lost.items() if v]
            if lost:
                warnings = []
                if "qdrant" in lost:
                    warnings.append(
                        "WARNING: Your semantic memory (Qdrant) is currently severed. "
                        "You cannot search past documents. Rely on immediate context and ask the user for clarification or documents if needed."
                    )
                if "neo4j" in lost:
                    warnings.append(
                        "WARNING: Your knowledge graph (Neo4j) is currently unavailable. "
                        "You cannot traverse relationships. Rely on other sources."
                    )
                if "openai" in lost or "voyage" in lost:
                    warnings.append(
                        "WARNING: Some model/embedding services are degraded. "
                        "Be explicit about limitations if you cannot fulfill a request."
                    )
                if warnings:
                    prompt = f"{prompt}\n\n" + "\n\n".join(warnings)

        tracker = self._services.get(SK.POWER_LEVEL_TRACKER)
        if tracker is not None and hasattr(tracker, "get_trust_matrix"):
            try:
                trust_matrix = tracker.get_trust_matrix(self.name)
                if trust_matrix:
                    lines = []
                    for other, score in sorted(trust_matrix.items()):
                        if score >= 0.6:
                            lines.append(f"You trust {other}'s outputs (Trust: {score:.1f}).")
                        else:
                            lines.append(f"You do not trust {other}'s outputs (Trust: {score:.1f}); verify before relying.")
                    if lines:
                        prompt = f"{prompt}\n\n" + " ".join(lines)
            except Exception:
                logger.debug("Trust matrix injection failed for %s", self.name, exc_info=True)

        soul = load_soul_preamble()
        if soul and not prompt.startswith(soul):
            return f"{soul}\n\n{prompt}" if prompt else soul
        return prompt

    def __init__(
        self,
        retriever: UnifiedRetriever,
        bus: MessageBus,
        *,
        services: dict[str, Any] | None = None,
    ) -> None:
        self._retriever = retriever
        self._bus = bus
        self._services: dict[str, Any] = services or {}

        self._llm = get_llm_client()

        self.tools: list[AgentTool] = []
        self.max_iterations: int = get_settings().app.react_max_iterations
        self.state: AgentState = AgentState.THINKING
        self._default_tools_registered: bool = False
        self._last_grounding_score: float = 0.0
        self._tools_lock = asyncio.Lock()

    def inject_services(self, services: dict[str, Any]) -> None:
        """Late-bind shared services after construction.

        Resets the default-tool flag so the next ``run()`` call will
        re-register tools with the newly available services.
        """
        from ira.service_keys import ALL_SERVICE_KEYS

        for key in services:
            if key not in ALL_SERVICE_KEYS:
                logger.warning("Unknown service key injected: %r", key)
        self._services.update(services)
        self._default_tools_registered = False

    # ── tool registration ────────────────────────────────────────────────

    def register_tool(self, tool: AgentTool) -> None:
        """Register a tool for use in the ReAct loop.

        Silently replaces an existing tool with the same name.
        """
        self.tools = [t for t in self.tools if t.name != tool.name]
        self.tools.append(tool)

    def _register_default_tools(self) -> None:
        """Register the standard tools available to every agent.

        Only registers tools whose backing service is present in
        ``self._services``.  Called lazily at the start of ``run()``.
        """
        if self._default_tools_registered:
            return
        self._default_tools_registered = True

        self.register_tool(AgentTool(
            name="search_knowledge",
            description="Search the internal knowledge base (Qdrant + Neo4j + Mem0).",
            parameters={"query": "Search query string", "limit": "Max results (default 10)"},
            handler=self._tool_search_knowledge,
        ))

        if self._services.get(SK.LONG_TERM_MEMORY):
            self.register_tool(AgentTool(
                name="recall_memory",
                description="Search long-term semantic memory (Mem0) for past facts and context.",
                parameters={"query": "What to recall", "user_id": "User ID (default 'global')"},
                handler=self._tool_recall_memory,
            ))
            self.register_tool(AgentTool(
                name="store_memory",
                description="Store an important fact or insight in long-term memory.",
                parameters={"content": "Fact to remember", "user_id": "User ID (default 'global')"},
                handler=self._tool_store_memory,
            ))

        if self._services.get(SK.CONVERSATION_MEMORY):
            self.register_tool(AgentTool(
                name="get_conversation_history",
                description="Retrieve recent conversation history for a user. Returns the last 5 messages by default. Use recall_episodes for older context.",
                parameters={
                    "user_id": "User ID",
                    "channel": "Channel (default 'CLI')",
                    "limit": "Max messages (default 5)",
                },
                handler=self._tool_get_conversation_history,
            ))

        if self._services.get(SK.RELATIONSHIP_MEMORY):
            self.register_tool(AgentTool(
                name="check_relationship",
                description="Look up the relationship profile for a contact (warmth, history, preferences).",
                parameters={"contact_id": "Contact identifier"},
                handler=self._tool_check_relationship,
            ))

        if self._services.get(SK.GOAL_MANAGER):
            self.register_tool(AgentTool(
                name="check_goals",
                description="Get the active goal for a contact (slot-filling progress, type).",
                parameters={"contact_id": "Contact identifier"},
                handler=self._tool_check_goals,
            ))

        if self._services.get(SK.EPISODIC_MEMORY):
            self.register_tool(AgentTool(
                name="recall_episodes",
                description="Search episodic memory for past interaction narratives and key events.",
                parameters={"query": "What to search for", "user_id": "User/contact ID", "limit": "Max results (default 5)"},
                handler=self._tool_recall_episodes,
            ))

        if self._services.get(SK.PANTHEON):
            self.register_tool(AgentTool(
                name="ask_agent",
                description="Delegate a question to another specialist agent in the Pantheon.",
                parameters={"agent_name": "Name of the agent (e.g. 'clio', 'prometheus')", "question": "The question to ask"},
                handler=self._tool_ask_agent,
            ))

        if self._services.get(SK.AGENT_JOURNAL):
            self.register_tool(AgentTool(
                name="read_my_journal",
                description="Look up your own past journal entries (nightly reflections written during Dream Mode).",
                parameters={"query": "Optional search query to filter entries; leave empty for recent entries"},
                handler=self._tool_read_journal,
            ))

        self.register_tool(AgentTool(
            name="web_search",
            description=(
                "Search the web for real-time information. Returns titles, URLs, and snippets. "
                "Requires at least one search API key (Tavily, Serper, or SearchAPI)."
            ),
            parameters={"query": "Web search query"},
            handler=self._tool_web_search_default,
        ))

        self.register_tool(AgentTool(
            name="scrape_url",
            description=(
                "Fetch a web page and return its content as clean markdown. "
                "Use after web_search to read the full content of a result URL."
            ),
            parameters={"url": "The full URL to scrape"},
            handler=self._tool_scrape_url,
        ))

        self.register_tool(AgentTool(
            name="check_known_entities",
            description=(
                "Check if a company or contact is a known entity (existing customer, "
                "vendor, sales agent, defunct company, or sister company). Use this "
                "BEFORE classifying any contact as a lead to avoid misclassification."
            ),
            parameters={"query": "Company name, contact name, or email to look up"},
            handler=self._tool_check_known_entities,
        ))

        if self._services.get(SK.EMAIL_PROCESSOR):
            self.register_tool(AgentTool(
                name="search_emails",
                description=(
                    "Search Gmail for emails matching filters. Use this when the user asks "
                    "to find, show, or pull up emails from a person, company, or about a topic."
                ),
                parameters={
                    "from_address": "Sender email or partial match (e.g. 'contact@acme-corp.com' or 'acme-corp')",
                    "to_address": "Recipient email (optional)",
                    "subject": "Subject keyword (optional)",
                    "label": "Gmail label/folder (optional, e.g. 'HR' or 'Recruitment CVs')",
                    "query": "Free-form Gmail search query (optional, e.g. 'has:attachment')",
                    "after": "Date filter YYYY/MM/DD (optional)",
                    "before": "Date filter YYYY/MM/DD (optional)",
                    "max_results": "Max emails to return (default 10)",
                },
                handler=self._tool_search_emails,
            ))
            self.register_tool(AgentTool(
                name="read_email_thread",
                description=(
                    "Fetch the full email thread by thread ID. Use this after search_emails "
                    "to read the complete conversation history of a thread."
                ),
                parameters={"thread_id": "Gmail thread ID from a search result"},
                handler=self._tool_read_email_thread,
            ))

        if get_settings().apollo.api_key.get_secret_value():
            self.register_tool(AgentTool(
                name="enrich_contact_apollo",
                description=(
                    "Enrich a contact using Apollo.io (title, company, LinkedIn). "
                    "Pass email and optionally name or company/domain. Uses Apollo credits."
                ),
                parameters={
                    "email": "Contact email (best for matching)",
                    "name": "Full name (optional)",
                    "company_or_domain": "Company name or domain e.g. acme.com (optional)",
                },
                handler=self._tool_enrich_contact_apollo,
            ))
            self.register_tool(AgentTool(
                name="sync_crm_apollo",
                description=(
                    "Sync CRM with Apollo.io: enrich contacts (role, LinkedIn) and companies "
                    "(industry, website, employee count, region). Use when the user asks to sync or "
                    "refresh CRM data with Apollo, or to enrich all contacts/companies from Apollo."
                ),
                parameters={
                    "dry_run": "If true, only report what would be updated (default false)",
                    "limit": "Max contacts to process (default 20 for agent; use 0 or omit for no limit)",
                    "contacts_only": "If true, only enrich contacts, not companies (default false)",
                },
                handler=self._tool_sync_crm_apollo,
            ))

        gdocs = self._services.get(SK.GOOGLE_DOCS)
        if gdocs is not None and getattr(gdocs, "calendar_available", False):
            self.register_tool(AgentTool(
                name="check_calendar",
                description=(
                    "List upcoming calendar events (primary Google Calendar). "
                    "Use when the user asks about schedule, availability, meetings, or what's coming up."
                ),
                parameters={
                    "days": "Number of days ahead to show (default 7)",
                    "max_results": "Max events to return (default 20)",
                },
                handler=self._tool_check_calendar,
            ))

    # ── default tool handlers ─────────────────────────────────────────────

    async def _tool_search_knowledge(self, query: str, limit: str = "10") -> str:
        results = await self._retriever.search(query, limit=int(limit))
        if not results:
            return "No results found."
        lines = []
        for r in results:
            chunk_id = r.get("id", "?")
            source = r.get("source", "?")
            lines.append(f"- [Source: {source}, Chunk: {chunk_id}] {r.get('content', '')[:400]}")
        return "\n".join(lines)

    async def _tool_recall_memory(self, query: str, user_id: str = "global") -> str:
        mem = self._services[SK.LONG_TERM_MEMORY]
        results = await mem.search(query, user_id=user_id)
        if not results:
            return "No memories found."
        lines = []
        for m in results:
            lines.append(f"- {m.get('memory', m.get('content', ''))}")
        return "\n".join(lines)

    async def _tool_store_memory(self, content: str, user_id: str = "global") -> str:
        mem = self._services[SK.LONG_TERM_MEMORY]
        result = await mem.store(content, user_id=user_id)
        return f"Stored. ({len(result)} memory entries affected)"

    async def _tool_get_conversation_history(
        self, user_id: str, channel: str = "CLI", limit: str = "5",
    ) -> str:
        conv = self._services[SK.CONVERSATION_MEMORY]
        history = await conv.get_history(user_id, channel, limit=int(limit))
        if not history:
            return "No conversation history found."
        lines = []
        for msg in history:
            lines.append(f"[{msg.get('role', '?')}] {msg.get('content', '')[:300]}")
        return "\n".join(lines)

    async def _tool_check_relationship(self, contact_id: str) -> str:
        rel_mem = self._services[SK.RELATIONSHIP_MEMORY]
        rel = await rel_mem.get_relationship(contact_id)
        return json.dumps({
            "contact_id": rel.contact_id,
            "warmth_level": rel.warmth_level.value if hasattr(rel.warmth_level, "value") else str(rel.warmth_level),
            "interaction_count": rel.interaction_count,
            "memorable_moments": rel.memorable_moments[:5],
            "learned_preferences": rel.learned_preferences,
        }, default=str)

    async def _tool_check_goals(self, contact_id: str) -> str:
        gm = self._services[SK.GOAL_MANAGER]
        goal = await gm.get_active_goal(contact_id)
        if goal is None:
            return f"No active goal for contact '{contact_id}'."
        return json.dumps({
            "id": str(goal.id),
            "type": goal.goal_type.value,
            "status": goal.status.value,
            "progress": goal.progress,
            "slots": goal.required_slots,
        }, default=str)

    async def _tool_recall_episodes(self, query: str, user_id: str = "global", limit: str = "5") -> str:
        ep = self._services[SK.EPISODIC_MEMORY]
        results = await ep.surface_relevant_episodes(query, user_id)
        if not results:
            return "No episodic memories found."
        lines = []
        for e in results[:int(limit)]:
            ts = e.get("created_at", "?")
            narrative = e.get("narrative", e.get("content", ""))[:400]
            lines.append(f"- [{ts}] {narrative}")
        return "\n".join(lines)

    @property
    def _max_delegation_depth(self) -> int:
        try:
            from ira.config import get_settings
            return get_settings().app.max_delegation_depth
        except Exception:
            return 5

    async def _tool_read_journal(self, query: str = "") -> str:
        """Return this agent's past journal entries (from Dream Mode reflections)."""
        journal = self._services.get(SK.AGENT_JOURNAL)
        if not journal:
            return "Journal service not available."
        try:
            entries = await journal.search_past_journals(
                agent_name=self.name,
                query=query.strip(),
                limit=10,
            )
        except Exception as exc:
            logger.warning("read_my_journal failed in %s: %s", self.name, exc)
            return f"Journal lookup error: {exc}"
        if not entries:
            return "No journal entries found."
        lines = []
        for e in entries:
            lines.append(f"[{e.get('date', '?')}] {e.get('reflection_text', '')[:500]}")
        return "\n\n".join(lines)

    async def _tool_ask_agent(self, agent_name: str, question: str) -> str:
        depth = self._services.get("_delegation_depth", 0)
        limit = self._max_delegation_depth
        if depth >= limit:
            return (
                "Delegation depth limit reached. "
                "Please synthesize your answer from the information already gathered."
            )
        pantheon = self._services.get(SK.PANTHEON)
        if not pantheon:
            return "Pantheon service unavailable."
        agent = pantheon.get_agent(agent_name.lower())
        if agent is None:
            return f"Agent '{agent_name}' not found."
        try:
            return await agent.handle(question, {
                "services": {"_delegation_depth": depth + 1},
                "_delegation_depth": depth + 1,
            })
        except (ToolExecutionError, Exception) as exc:
            logger.warning("Delegation to '%s' failed in %s: %s", agent_name, self.name, exc)
            return f"Agent '{agent_name}' error: {exc}"

    async def _tool_search_emails(
        self,
        from_address: str = "",
        to_address: str = "",
        subject: str = "",
        label: str = "",
        query: str = "",
        after: str = "",
        before: str = "",
        max_results: str = "10",
    ) -> str:
        _email_scope = self._context.get("email_scope", "both") if self._context else "both"
        if _email_scope == "no_email":
            return "Email search skipped (query does not require email data). Use search_knowledge for KB results."
        if _email_scope == "imported_email":
            return "Live email search skipped (using imported/indexed email via KB). Use search_knowledge for faster results from Qdrant."
        ep = self._services[SK.EMAIL_PROCESSOR]
        try:
            emails = await ep.search_emails(
                from_address=from_address,
                to_address=to_address,
                subject=subject,
                label=label,
                query=query,
                after=after,
                before=before,
                max_results=int(max_results),
            )
        except (ToolExecutionError, Exception) as exc:
            logger.warning("search_emails failed in %s: %s", self.name, exc)
            return f"Email search error: {exc}"
        if not emails:
            return "No emails found matching the search criteria."
        lines = []
        for e in emails:
            lines.append(
                f"- [{e.received_at.strftime('%Y-%m-%d %H:%M')}] "
                f"From: {e.from_address} | To: {e.to_address} | "
                f"Subject: {e.subject} | Thread: {e.thread_id}\n"
                f"  Body preview: {e.body[:500]}"
            )
        return "\n".join(lines)

    async def _tool_read_email_thread(self, thread_id: str) -> str:
        ep = self._services[SK.EMAIL_PROCESSOR]
        try:
            emails = await ep.get_thread(thread_id)
        except (ToolExecutionError, Exception) as exc:
            logger.warning("read_email_thread failed in %s: %s", self.name, exc)
            return f"Thread read error: {exc}"
        if not emails:
            return "Thread is empty or not found."
        lines = []
        for e in emails:
            lines.append(
                f"--- [{e.received_at.strftime('%Y-%m-%d %H:%M')}] "
                f"From: {e.from_address} → To: {e.to_address} ---\n"
                f"Subject: {e.subject}\n{e.body}\n"
            )
        return "\n".join(lines)

    async def _tool_enrich_contact_apollo(
        self,
        email: str = "",
        name: str = "",
        company_or_domain: str = "",
    ) -> str:
        from ira.systems.apollo_client import enrich_person_async

        if not email and not name and not company_or_domain:
            return "Provide at least one of: email, name, or company_or_domain."
        domain = None
        org = None
        if company_or_domain:
            s = company_or_domain.strip()
            if "." in s and " " not in s:
                domain = s.replace("www.", "")
            else:
                org = s
        try:
            result = await enrich_person_async(
                email=email.strip() or None,
                name=name.strip() or None,
                domain=domain,
                organization_name=org,
            )
        except Exception as exc:
            logger.warning("enrich_contact_apollo failed in %s: %s", self.name, exc)
            return f"Apollo enrichment error: {exc}"
        if not result:
            return "No Apollo match found for that contact."
        parts = [f"**{result.get('name') or 'Unknown'}**"]
        if result.get("title"):
            parts.append(f"Title: {result['title']}")
        if result.get("organization_name"):
            parts.append(f"Company: {result['organization_name']}")
        if result.get("email"):
            parts.append(f"Email: {result['email']}")
        if result.get("linkedin_url"):
            parts.append(f"LinkedIn: {result['linkedin_url']}")
        return "\n".join(parts)

    async def _tool_sync_crm_apollo(
        self,
        dry_run: str = "false",
        limit: str = "20",
        contacts_only: str = "false",
    ) -> str:
        """Run Apollo sync for CRM; returns a short summary of contacts/companies updated."""
        crm = self._services.get(SK.CRM)
        if not crm:
            return "CRM is not available; cannot run Apollo sync."
        from ira.systems.apollo_crm_sync import sync_crm_with_apollo

        try:
            limit_val: int | None = int(limit) if limit and limit.strip() else 20
            if limit_val <= 0:
                limit_val = None
            result = await sync_crm_with_apollo(
                crm,
                dry_run=dry_run.strip().lower() in ("true", "1", "yes"),
                limit=limit_val,
                contact_type=None,
                contacts_only=contacts_only.strip().lower() in ("true", "1", "yes"),
            )
        except Exception as exc:
            logger.warning("sync_crm_apollo failed in %s: %s", self.name, exc)
            return f"Apollo sync error: {exc}"

        if result.get("contact_type_error"):
            return result["contact_type_error"]
        return (
            f"Apollo sync done. Contacts updated: {result['contacts_updated']}, "
            f"companies updated: {result['companies_updated']}, "
            f"skipped (no email): {result['skipped_no_email']}, no match: {result['no_match']}, errors: {result['errors']}."
        )

    async def _tool_check_calendar(
        self, days: str = "7", max_results: str = "20",
    ) -> str:
        gdocs = self._services.get(SK.GOOGLE_DOCS)
        if not gdocs or not getattr(gdocs, "calendar_available", False):
            return "Calendar is not available."
        try:
            d = int(days) if days else 7
            m = int(max_results) if max_results else 20
            d = max(1, min(d, 31))
            m = max(1, min(m, 50))
        except ValueError:
            d, m = 7, 20
        try:
            events = await gdocs.list_upcoming_events(days=d, max_results=m)
        except Exception as exc:
            logger.warning("check_calendar failed in %s: %s", self.name, exc)
            return f"Calendar error: {exc}"
        if not events:
            return f"No events in the next {d} days."
        lines = [f"Upcoming events (next {d} days):"]
        for ev in events:
            start = ev.get("start", "") or ""
            summary = ev.get("summary", "(No title)")
            loc = ev.get("location", "")
            line = f"- {start}: {summary}"
            if loc:
                line += f" @ {loc}"
            lines.append(line)
        return "\n".join(lines)

    async def _tool_web_search_default(self, query: str) -> str:
        results = await self.web_search(query, max_results=5)
        if not results:
            return "No web search results found."
        lines = []
        for r in results:
            lines.append(f"- [{r['title']}]({r['url']}): {r['snippet'][:200]}")
        return "\n".join(lines)

    async def _tool_scrape_url(self, url: str) -> str:
        return await self.scrape_url(url)

    _KNOWN_ENTITIES_PATH = Path("data/brain/known_entities.json")

    async def _tool_check_known_entities(self, query: str) -> str:
        """Check if a company/contact matches a known entity."""
        try:
            if not self._KNOWN_ENTITIES_PATH.exists():
                return "Known entities registry not found."
            raw = await asyncio.to_thread(self._KNOWN_ENTITIES_PATH.read_text)
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            return f"Error reading known entities: {exc}"

        query_lower = query.lower()
        matches: list[str] = []

        for agent in data.get("agents", []):
            if query_lower in agent.get("name", "").lower() or query_lower in agent.get("email", "").lower():
                matches.append(
                    f"AGENT: {agent['name']} ({agent.get('email', '')}) — "
                    f"Region: {agent.get('region', '?')}. {agent.get('note', '')}"
                )

        for cust in data.get("existing_customers", []):
            if query_lower in cust.get("name", "").lower() or query_lower in cust.get("email", "").lower():
                matches.append(
                    f"EXISTING CUSTOMER: {cust['name']} — "
                    f"Machine: {cust.get('machine', '?')}. {cust.get('note', '')}"
                )

        for vendor in data.get("vendors", []):
            if query_lower in vendor.get("name", "").lower() or query_lower in vendor.get("email", "").lower():
                matches.append(
                    f"VENDOR: {vendor['name']} — "
                    f"Service: {vendor.get('service', '?')}. {vendor.get('note', '')}"
                )

        for defunct in data.get("defunct_companies", []):
            if query_lower in defunct.get("name", "").lower():
                matches.append(
                    f"DEFUNCT COMPANY: {defunct['name']} — {defunct.get('note', '')}"
                )

        for sister in data.get("sister_companies", []):
            if query_lower in sister.get("name", "").lower() or query_lower in sister.get("domain", "").lower():
                matches.append(
                    f"SISTER COMPANY: {sister['name']} — {sister.get('note', '')}"
                )

        for excluded in data.get("not_machinecraft", []):
            if query_lower in excluded.get("name", "").lower():
                matches.append(
                    f"NOT MACHINECRAFT: {excluded['name']} — {excluded.get('note', '')}"
                )

        if not matches:
            return f"No known entity match for '{query}'. Proceed with normal classification."
        return "\n".join(matches)

    async def _log_journal_action(self, query: str, outcome: str) -> None:
        """Log this agent's action to the journal when the service is available."""
        journal = self._services.get(SK.AGENT_JOURNAL)
        if journal is None:
            return
        try:
            await journal.log_action(
                agent_name=self.name,
                action_text=f"Handled query: {query[:100]}",
                outcome=outcome,
            )
        except Exception:
            logger.debug("AgentJournal.log_action failed for %s", self.name, exc_info=True)

    # ── grounding score ────────────────────────────────────────────────────

    _RETRIEVAL_TOOLS: frozenset[str] = frozenset({
        "search_knowledge", "recall_memory", "recall_episodes",
        "search_emails", "read_email_thread", "ask_agent", "web_search", "scrape_url",
    })
    # Agents that may answer without retrieval: gatekeeper (clarify only), gap resolver (synthesis).
    _GROUNDING_EXEMPT_AGENTS: frozenset[str] = frozenset({"sphinx", "gapper"})

    @staticmethod
    def _compute_grounding_score(scratchpad: list[dict[str, str]]) -> float:
        """Score how well the answer is grounded in tool outputs.

        Returns 1.0 if retrieval tools were used, 0.5 if only
        non-retrieval tools, 0.0 if no tools were called.
        """
        if not scratchpad:
            return 0.0
        tool_names = set()
        for entry in scratchpad:
            action = entry.get("action", "")
            paren = action.find("(")
            if paren > 0:
                tool_names.add(action[:paren])
        if not tool_names:
            return 0.0
        if tool_names & BaseAgent._RETRIEVAL_TOOLS:
            return 1.0
        return 0.5

    # ── ReAct loop ────────────────────────────────────────────────────────

    def _build_tool_descriptions(self) -> str:
        """Format registered tools into a description block for the LLM."""
        if not self.tools:
            return "(No tools available)"
        lines = []
        for t in self.tools:
            params = ", ".join(f"{k}: {v}" for k, v in t.parameters.items())
            lines.append(f"  - {t.name}({params}): {t.description}")
        return "\n".join(lines)

    async def _reason(
        self,
        agent_system_prompt: str,
        query: str,
        context: dict[str, Any] | None,
        scratchpad: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Ask the LLM to decide the next action (tool call or final answer)."""
        react_prompt = load_prompt("react_system")

        tool_block = self._build_tool_descriptions()
        system = (
            f"{agent_system_prompt}\n\n"
            f"--- TOOLS ---\n{tool_block}\n\n"
            f"--- REASONING PROTOCOL ---\n{react_prompt}"
        )

        scratchpad_text = ""
        if scratchpad:
            parts = []
            for entry in scratchpad:
                parts.append(
                    f"Thought: {entry.get('thought', '')}\n"
                    f"Action: {entry.get('action', '')}\n"
                    f"Observation: {entry.get('observation', '')}"
                )
            scratchpad_text = "\n---\n".join(parts)

        ctx_text = ""
        if context:
            ctx_text = f"\n\nAdditional context: {json.dumps(context, default=str)[:2000]}"

        delimited_query = f"<<<USER INPUT>>>\n{query}\n<<<END INPUT>>>"
        user_msg = f"Query: {delimited_query}{ctx_text}"
        if scratchpad_text:
            user_msg += f"\n\nPrevious reasoning steps:\n{scratchpad_text}\n\nContinue reasoning."

        primary = "anthropic" if self.model_provider == "anthropic" else "openai"
        try:
            raw = await self._llm.generate_text_with_fallback(
                system, user_msg,
                primary=primary, temperature=0.2,
                name=f"{self.name}.reason",
            )
        except Exception as exc:
            logger.warning("ReAct LLM call failed in %s: %s", self.name, exc)
            return {"thought": "LLM unavailable.", "final_answer": "(LLM call failed)"}

        try:
            parsed = self._parse_json_response(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse ReAct JSON in %s", self.name, exc_info=True)

        return {"thought": "Could not parse structured response.", "final_answer": raw}

    async def _execute_tool(self, name: str, inputs: dict[str, Any]) -> str:
        """Find and execute a registered tool by name.

        Strips unexpected keyword arguments that the LLM may hallucinate
        (e.g. ``limit``, ``max_results``) so tool handlers don't crash
        with ``got an unexpected keyword argument``.
        """
        tracker = self._services.get("tool_stats_tracker")
        for tool in self.tools:
            if tool.name == name:
                declared_params = set(tool.parameters.keys())
                safe_inputs = {k: v for k, v in inputs.items() if k in declared_params}
                if len(safe_inputs) < len(inputs):
                    _dropped = set(inputs) - declared_params
                    logger.debug("Tool '%s': dropped undeclared params %s", name, _dropped)
                try:
                    result = await tool.handler(**safe_inputs)
                    if tracker is not None:
                        await tracker.record_tool_call(self.name, name, success=True)
                    return str(result)[:4000]
                except ToolExecutionError:
                    if tracker is not None:
                        await tracker.record_tool_call(self.name, name, success=False)
                    raise
                except (IraError, Exception) as exc:
                    logger.warning("Tool '%s' failed in %s: %s", name, self.name, exc)
                    if tracker is not None:
                        await tracker.record_tool_call(self.name, name, success=False)
                    return (
                        f"Tool execution failed with error: {exc}. "
                        "Please check your parameters and try again, or use a different tool to find this information."
                    )
        if tracker is not None:
            await tracker.record_tool_call(self.name, name, success=False)
        return f"Unknown tool: {name}"

    async def _force_final_answer(
        self,
        agent_system_prompt: str,
        query: str,
        scratchpad: list[dict[str, str]],
    ) -> str:
        """Synthesise a final answer when max iterations are reached."""
        observations = "\n".join(
            f"- {e.get('thought', '')}: {e.get('observation', '')[:300]}"
            for e in scratchpad if e.get("observation")
        )
        user_msg = (
            f"Original query: {query}\n\n"
            f"Research gathered so far:\n{observations}\n\n"
            "You have reached the maximum number of reasoning steps. "
            "Synthesise the best possible answer from the information above."
        )
        return await self.call_llm(agent_system_prompt, user_msg)

    @observe(name="agent.run")
    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        *,
        system_prompt: str = "",
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> str:
        """Execute the ReAct (Reason-Act-Observe) loop.

        Subclasses that want agentic behaviour should call this method
        (typically from their ``handle()`` override) instead of doing a
        single-pass LLM call.

        Parameters
        ----------
        query:
            The user/caller query.
        context:
            Optional context dict forwarded from the caller.  May contain
            a ``"services"`` key with live service references from the
            pipeline, which are merged into ``self._services`` so that
            ReAct tools can query memory dynamically.
        system_prompt:
            The agent-specific system prompt to prepend to the ReAct
            protocol.  If empty, a minimal default is used.
        on_progress:
            Optional async callback for streaming progress events.
        """
        _progress = on_progress or (context or {}).get("_on_progress")

        self._context = context or {}
        self.state = AgentState.THINKING
        self._last_grounding_score = 0.0
        self._services.pop("_delegation_depth", None)

        if context and "services" in context:
            for key, svc in context["services"].items():
                if svc is not None and key not in self._services:
                    self._services[key] = svc
            self._default_tools_registered = False

        async with self._tools_lock:
            self._register_default_tools()

        agent_prompt = await self._compose_system_prompt(system_prompt)

        scratchpad: list[dict[str, str]] = []
        self.state = AgentState.THINKING

        for iteration in range(self.max_iterations):
            self.state = AgentState.THINKING
            if _progress:
                await _progress({"type": "agent_thinking", "agent": self.name, "iteration": iteration + 1})

            decision = await self._reason(agent_prompt, query, context, scratchpad)

            thought = decision.get("thought", "")

            if "final_answer" in decision:
                self.state = AgentState.RESPONDING
                self._last_grounding_score = self._compute_grounding_score(scratchpad)
                if (
                    self._last_grounding_score == 0.0
                    and len(decision["final_answer"]) > 100
                    and self.name not in BaseAgent._GROUNDING_EXEMPT_AGENTS
                ):
                    logger.warning(
                        "GROUNDING | %s answered without retrieval tools — hallucination risk",
                        self.name,
                    )
                logger.info(
                    "%s reached final answer after %d iterations (grounding=%.1f)",
                    self.name, iteration + 1, self._last_grounding_score,
                )
                await self._log_journal_action(query, "success")
                return decision["final_answer"]

            tool_call = decision.get("tool_to_use")
            if not isinstance(tool_call, dict) or "name" not in tool_call:
                self.state = AgentState.RESPONDING
                self._last_grounding_score = self._compute_grounding_score(scratchpad)
                await self._log_journal_action(query, "success")
                return decision.get("final_answer", thought or "(No response)")

            tool_name = tool_call["name"]
            tool_input = tool_call.get("input", {})

            self.state = AgentState.ACTING
            logger.info(
                "%s [iter %d] calling tool '%s'",
                self.name, iteration + 1, tool_name,
            )
            if _progress:
                await _progress({
                    "type": "tool_called",
                    "agent": self.name,
                    "tool": tool_name,
                    "iteration": iteration + 1,
                })
            observation = await self._execute_tool(tool_name, tool_input)

            self.state = AgentState.OBSERVING
            scratchpad.append({
                "thought": thought,
                "action": f"{tool_name}({json.dumps(tool_input, default=str)})",
                "observation": observation,
            })

        logger.warning(
            "%s hit max iterations (%d) — forcing final answer",
            self.name, self.max_iterations,
        )
        self._last_grounding_score = self._compute_grounding_score(scratchpad)
        await self._log_journal_action(query, "success")
        return await self._force_final_answer(agent_prompt, query, scratchpad)

    # ── abstract interface ───────────────────────────────────────────────

    @abstractmethod
    async def handle(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Process a query and return a response string.

        Existing agents implement this as a single-pass function.
        To opt into the ReAct loop, an agent's ``handle()`` can call
        ``await self.run(query, context, system_prompt=...)`` instead.
        """

    # ── LLM access ───────────────────────────────────────────────────────

    _LLM_CACHE_TTL = 3600

    def _llm_cache_key(self, system_prompt: str, user_message: str, temperature: float) -> str:
        """Deterministic hash for caching LLM responses."""
        raw = f"{self.name}:{temperature:.2f}:{system_prompt[:500]}:{user_message[:2000]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def call_llm(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
    ) -> str:
        """Call the primary LLM provider; fall back to the other on failure."""
        redis = self._services.get(SK.REDIS)
        resolved_system_prompt = await self._compose_system_prompt(system_prompt)
        cache_key = self._llm_cache_key(resolved_system_prompt, user_message, temperature)

        if redis is not None and temperature <= 0.3:
            try:
                cached = await redis.get_llm_cache(cache_key)
                if cached is not None:
                    logger.debug("LLM cache hit for %s (key=%s)", self.name, cache_key[:8])
                    return cached
            except Exception:
                pass

        primary = "anthropic" if self.model_provider == "anthropic" else "openai"
        result = await self._llm.generate_text_with_fallback(
            resolved_system_prompt, user_message,
            primary=primary, temperature=temperature,
            name=f"{self.name}.call_llm",
        )

        if redis is not None and temperature <= 0.3 and not result.startswith("("):
            try:
                await redis.set_llm_cache(cache_key, result, self._LLM_CACHE_TTL)
            except Exception:
                pass

        return result

    # ── knowledge retrieval ──────────────────────────────────────────────

    async def search_knowledge(
        self,
        query: str,
        limit: int = 10,
        sources: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search the unified knowledge base."""
        return await self._retriever.search(query, sources=sources, limit=limit)

    async def search_category(
        self,
        query: str,
        category: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search within a specific knowledge category."""
        return await self._retriever.search_by_category(query, category, limit=limit)

    async def search_domain_knowledge(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Search across all source categories declared in *knowledge_categories*.

        Fires one ``search_category`` call per category in parallel, then
        deduplicates and sorts by score.  Falls back to the generic
        ``search_knowledge`` when no categories are configured.
        """
        if not self.knowledge_categories:
            return await self.search_knowledge(query, limit=limit)

        per_cat = max(3, limit // len(self.knowledge_categories))
        results_lists = await asyncio.gather(*(
            self.search_category(query, cat, limit=per_cat)
            for cat in self.knowledge_categories
        ))

        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for results in results_lists:
            for r in results:
                key = r.get("source", "") + r.get("content", "")[:100]
                if key not in seen:
                    seen.add(key)
                    merged.append(r)

        merged.sort(key=lambda r: r.get("score", 0), reverse=True)
        return merged[:limit]

    # ── inter-agent communication ────────────────────────────────────────

    async def send_to(self, to_agent: str, query: str, context: dict[str, Any] | None = None) -> None:
        """Send a message to another agent via the message bus."""
        await self._bus.send(self.name, to_agent, query, context)

    # ── web scraping (Firecrawl → Crawl4AI fallback) ────────────────────

    async def scrape_url(self, url: str, *, max_chars: int = 8000) -> str:
        """Fetch a URL and return its content as clean markdown.

        Order: Firecrawl (if FIRECRAWL_API_KEY) → Jina Reader (no key) →
        Crawl4AI (Playwright) → web_search fallback.
        """
        firecrawl_key = get_settings().firecrawl.api_key.get_secret_value()
        if firecrawl_key:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        "https://api.firecrawl.dev/v1/scrape",
                        headers={
                            "Authorization": f"Bearer {firecrawl_key}",
                            "Content-Type": "application/json",
                        },
                        json={"url": url, "formats": ["markdown"]},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
                    text = data.get("markdown", "")
                    if text:
                        return text[:max_chars]
            except Exception as exc:
                logger.warning(
                    "Firecrawl failed for %s in %s, trying next scraper: %s",
                    url, self.name, exc,
                )

        # Jina Reader: no API key for basic use (https://jina.ai/reader/)
        text = await self._scrape_url_jina(url, max_chars=max_chars)
        if text:
            return text
        return await self._scrape_url_crawl4ai(url, max_chars=max_chars)

    async def _scrape_url_jina(self, url: str, *, max_chars: int = 8000) -> str:
        """Jina Reader: GET r.jina.ai/<url> returns markdown. Uses JINA_API_KEY when set for better rate limits."""
        try:
            headers: dict[str, str] = {}
            jina_key = get_settings().jina.api_key.get_secret_value()
            if jina_key:
                headers["Authorization"] = f"Bearer {jina_key}"
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(f"https://r.jina.ai/{url}", headers=headers or None)
                resp.raise_for_status()
                text = (resp.text or "").strip()
                if text and len(text) > 100:
                    return text[:max_chars]
        except Exception as exc:
            logger.debug("Jina Reader failed for %s: %s", url, exc)
        return ""

    async def _scrape_url_crawl4ai(self, url: str, *, max_chars: int = 8000) -> str:
        """Crawl4AI fallback for scrape_url."""
        try:
            from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

            config = CrawlerRunConfig(
                word_count_threshold=50,
                excluded_tags=["nav", "footer", "header", "aside"],
                exclude_external_links=True,
            )
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
                if not result.success:
                    return f"Failed to scrape {url}: {result.error_message or 'unknown error'}"
                # Crawl4AI 0.8+: markdown is MarkdownGenerationResult with .raw_markdown; markdown_v2 removed
                md = getattr(result, "markdown", None)
                if md is not None and hasattr(md, "raw_markdown") and getattr(md, "raw_markdown", None):
                    text = md.raw_markdown
                elif isinstance(md, str):
                    text = md
                else:
                    text = ""
                if not text:
                    return f"Failed to scrape {url}: no markdown content"
                return text[:max_chars]
        except ImportError:
            return await self._scrape_url_web_search_fallback(url, max_chars)
        except Exception as exc:
            logger.warning("scrape_url (Crawl4AI) failed for %s in %s: %s", url, self.name, exc)
            return await self._scrape_url_web_search_fallback(url, max_chars)

    async def _scrape_url_web_search_fallback(self, url: str, max_chars: int = 8000) -> str:
        """When Firecrawl and Crawl4AI fail, use web_search to get snippets about the URL."""
        try:
            # Search for the URL or the domain so we return something useful
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc or url
            query = f"site:{domain}" if domain else url
            results = await self.web_search(query, max_results=5)
            if not results:
                return f"Scrape and search fallback had no results for {url}. Install Playwright (playwright install) or set FIRECRAWL_API_KEY for better scraping."
            parts = []
            for r in results:
                title = r.get("title") or ""
                snippet = r.get("snippet") or ""
                link = r.get("url") or ""
                if snippet or title:
                    parts.append(f"**{title}**\n{snippet}\nSource: {link}")
            out = "\n\n".join(parts)[:max_chars]
            return out or f"No content from search for {url}."
        except Exception as exc:
            logger.warning("scrape_url web_search fallback failed for %s: %s", url, exc)
            return f"Scrape error and fallback failed: {exc}. Install Playwright (playwright install) or set FIRECRAWL_API_KEY for URL scraping."

    # ── web search ────────────────────────────────────────────────────────

    async def web_search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        """Search the web using the best available provider.

        Returns a list of dicts with 'title', 'url', and 'snippet' keys.
        Tries Tavily first, then Serper, then SearchAPI.
        """
        settings = get_settings().search
        tavily = settings.tavily_api_key.get_secret_value()
        serper = settings.serper_api_key.get_secret_value()
        searchapi = settings.searchapi_api_key.get_secret_value()

        if tavily:
            return await self._search_tavily(query, tavily, max_results)
        if serper:
            return await self._search_serper(query, serper, max_results)
        if searchapi:
            return await self._search_searchapi(query, searchapi, max_results)
        logger.warning("Agent '%s' tried web_search but no search API key is configured", self.name)
        return []

    async def _search_tavily(self, query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query, "max_results": max_results},
                )
                resp.raise_for_status()
                return [
                    {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                    for r in resp.json().get("results", [])
                ]
        except (httpx.HTTPError, KeyError):
            logger.exception("Tavily search failed in %s", self.name)
            return []

    async def _search_serper(self, query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    json={"q": query, "num": max_results},
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return [
                    {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                    for r in resp.json().get("organic", [])
                ]
        except (httpx.HTTPError, KeyError):
            logger.exception("Serper search failed in %s", self.name)
            return []

    async def _search_searchapi(self, query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://www.searchapi.io/api/v1/search",
                    params={"engine": "google", "q": query, "num": max_results, "api_key": api_key},
                )
                resp.raise_for_status()
                return [
                    {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                    for r in resp.json().get("organic_results", [])
                ]
        except (httpx.HTTPError, KeyError):
            logger.exception("SearchAPI search failed in %s", self.name)
            return []

    # ── relationship reporting ──────────────────────────────────────────

    async def report_relationship(
        self,
        from_type: str,
        from_key: str,
        rel: str,
        to_type: str,
        to_key: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Emit a discovered relationship via the DataEventBus.

        Any agent can call this to contribute graph edges without needing
        direct access to the KnowledgeGraph.
        """
        event_bus = self._services.get(SK.DATA_EVENT_BUS)
        if event_bus is None:
            return
        from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
        try:
            await event_bus.emit(DataEvent(
                event_type=EventType.RELATIONSHIP_DISCOVERED,
                entity_type="relationship",
                entity_id=f"{from_key}-{rel}-{to_key}",
                payload={
                    "from_type": from_type,
                    "from_key": from_key,
                    "rel": rel,
                    "to_type": to_type,
                    "to_key": to_key,
                    "properties": properties or {},
                },
                source_store=SourceStore.NEO4J,
            ))
        except (IraError, Exception):
            logger.debug("Relationship event emission failed in %s", self.name, exc_info=True)

    # ── utility ──────────────────────────────────────────────────────────

    def _format_context(self, kb_results: list[dict[str, Any]]) -> str:
        """Format knowledge-base results into a context string for LLM prompts."""
        if not kb_results:
            return "(No relevant context found)"
        lines = []
        for r in kb_results:
            chunk_id = r.get("id", "?")
            source = r.get("source", "unknown")
            lines.append(f"- [Source: {source}, Chunk: {chunk_id}] {r.get('content', '')[:500]}")
        return "\n".join(lines)

    def _parse_json_response(self, raw: str) -> dict[str, Any] | list[Any]:
        """Attempt to parse an LLM response as JSON, stripping markdown fences. Returns {} on failure."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Try to extract first complete {...} or [...]
        for open_b, close_b in (("{", "}"), ("[", "]")):
            i = cleaned.find(open_b)
            if i < 0:
                continue
            depth = 0
            for j in range(i, len(cleaned)):
                if cleaned[j] == open_b:
                    depth += 1
                elif cleaned[j] == close_b:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[i : j + 1])
                        except json.JSONDecodeError:
                            break
                        break
        logger.debug("_parse_json_response could not parse JSON in %s", self.name)
        return {}

    # ── skill execution ──────────────────────────────────────────────────

    async def use_skill(self, skill_name: str, **kwargs: Any) -> str:
        """Execute a skill from the SKILL_MATRIX by name.

        Every agent inherits this method, giving the entire Pantheon
        uniform access to the shared skill library.

        Raises :class:`ValueError` for unrecognised skill names.
        """
        logger.info("Agent '%s' invoking skill '%s'", self.name, skill_name)
        return await _use_skill(skill_name, **kwargs)

    @staticmethod
    def available_skills() -> dict[str, str]:
        """Return the full skill matrix for introspection."""
        return dict(SKILL_MATRIX)
