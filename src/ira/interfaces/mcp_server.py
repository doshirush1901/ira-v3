"""MCP (Model Context Protocol) server for Ira.

Exposes Ira's core capabilities as MCP tools, making them accessible
to Claude, Cursor, and any MCP-compatible client.  Uses the same
bootstrap logic as the CLI to avoid service duplication.

Start with::

    ira mcp
    # or
    poetry run python -m ira.interfaces.mcp_server
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ira.pipeline_loop import AgentLoop, LoopDecision

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "ira",
    instructions=(
        "Ira is the AI that runs Machinecraft, an industrial machinery company. "
        "Use these tools to query Ira's 11-stage pipeline, search the knowledge base, "
        "manage the CRM, search emails, access memory, explore the knowledge graph, "
        "search the web, and interact with 24 specialist agents."
    ),
)

# ── Service globals (populated by _ensure_initialized) ──────────────────

_pantheon: Any = None
_shared_services: dict[str, Any] = {}
_pipeline: Any = None
_retriever: Any = None
_crm: Any = None
_ingestor: Any = None
_long_term_memory: Any = None
_conversation_memory: Any = None
_relationship_memory: Any = None
_goal_manager: Any = None
_knowledge_graph: Any = None
_email_processor: Any = None
_task_orchestrator: Any = None
_agent_loop: AgentLoop | None = None
_initialized = False


async def _ensure_initialized() -> None:
    """Lazy-init the Ira subsystems on first tool call."""
    global _pantheon, _shared_services, _pipeline, _retriever, _crm, _ingestor  # noqa: PLW0603
    global _long_term_memory, _conversation_memory, _relationship_memory  # noqa: PLW0603
    global _goal_manager, _knowledge_graph, _email_processor  # noqa: PLW0603
    global _task_orchestrator, _agent_loop, _initialized  # noqa: PLW0603
    if _initialized:
        return

    from ira.interfaces.cli import _build_pantheon, _build_pipeline
    from ira.service_keys import ServiceKey as SK

    _pantheon, _shared_services = _build_pantheon()
    _retriever = _shared_services.get(SK.RETRIEVER)
    _crm = _shared_services.get(SK.CRM)

    _pipeline, _ = await _build_pipeline(_pantheon, _shared_services)

    # Memory services — pipeline stores these as instance attributes
    _conversation_memory = getattr(_pipeline, "_conversation", None)
    _relationship_memory = getattr(_pipeline, "_relationship", None)
    _goal_manager = getattr(_pipeline, "_goals", None)

    # Long-term memory is injected into agents, not stored on the pipeline
    mnemosyne = _pantheon.get_agent("mnemosyne") if _pantheon else None
    if mnemosyne and hasattr(mnemosyne, "_services"):
        _long_term_memory = mnemosyne._services.get(SK.LONG_TERM_MEMORY)

    # Knowledge graph
    from ira.brain.knowledge_graph import KnowledgeGraph
    _knowledge_graph = KnowledgeGraph()

    # Ingestor
    digestive = _shared_services.get(SK.DIGESTIVE)
    if digestive and hasattr(digestive, "_ingestor"):
        _ingestor = digestive._ingestor

    # Email processor (best-effort — requires Google credentials)
    try:
        from ira.interfaces.email_processor import EmailProcessor
        from ira.systems.sensory import SensorySystem

        graph = KnowledgeGraph()
        sensory = SensorySystem(knowledge_graph=graph)
        delphi = _pantheon.get_agent("delphi") if _pantheon else None
        _email_processor = EmailProcessor(
            delphi=delphi,
            digestive=digestive,
            sensory=sensory,
            crm=_crm,
            pantheon=_pantheon,
        )
    except Exception:
        logger.info("Email processor not available for MCP — continuing without it")

    # Task orchestrator (requires Redis for state persistence)
    try:
        from ira.systems.task_orchestrator import TaskOrchestrator

        redis_cache = _shared_services.get(SK.REDIS)
        voice = _shared_services.get(SK.VOICE)
        _task_orchestrator = TaskOrchestrator(
            pantheon=_pantheon,
            redis_cache=redis_cache,
            voice=voice,
        )
    except Exception:
        logger.info("Task orchestrator not available for MCP — continuing without it")

    if _pantheon is not None:
        _agent_loop = AgentLoop(_pantheon)

    _initialized = True
    logger.info("Ira MCP server initialized (%d tools registered)", len(mcp._tool_manager._tools))


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model or Pydantic model to a JSON-safe dict."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {
            k: v for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    return {"value": str(obj)}


# ═══════════════════════════════════════════════════════════════════════════
# EXISTING TOOLS (Pipeline, Knowledge, CRM basics, Email draft, Ingest)
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def query_ira(question: str) -> str:
    """Ask Ira a question about Machinecraft.

    Routes through the full 11-stage pipeline: perceive, remember,
    route, execute, assess, reflect, shape, learn, and return.
    Ira will delegate to the appropriate specialist agents automatically.
    """
    await _ensure_initialized()
    if _pipeline is None:
        return "Ira pipeline not available."

    try:
        response, agents_used = await _pipeline.process_request(
            raw_input=question,
            channel="mcp",
            sender_id="mcp_user",
        )
        suffix = ""
        if agents_used:
            suffix = f"\n\n[Agents consulted: {', '.join(agents_used)}]"
        return response + suffix
    except Exception as exc:
        logger.exception("MCP query_ira failed")
        return f"Error: {exc}"


@mcp.tool()
async def search_knowledge(query: str, limit: int = 10) -> str:
    """Search Ira's knowledge base across Qdrant, Neo4j, and Mem0.

    Returns the top results with content, scores, and source metadata.
    Use this for direct knowledge retrieval without agent reasoning.
    """
    await _ensure_initialized()
    if _retriever is None:
        return "Retriever not available."

    try:
        results = await _retriever.search(query, limit=limit)
        formatted = []
        for r in results[:limit]:
            formatted.append({
                "content": r.get("content", "")[:500],
                "score": round(r.get("score", 0), 3),
                "source": r.get("source", ""),
                "source_type": r.get("source_type", ""),
            })
        return json.dumps(formatted, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP search_knowledge failed")
        return f"Error: {exc}"


@mcp.tool()
async def search_crm(query: str) -> str:
    """Search the Machinecraft CRM for contacts, companies, and deals.

    Returns matching CRM records. Use for customer lookups, deal status,
    and pipeline queries.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        contact_dicts = await _crm.search_contacts(query)
        contacts = [
            {
                "name": c.get("name", ""),
                "email": c.get("email", ""),
                "company": c.get("company_name", ""),
                "role": c.get("role", ""),
            }
            for c in contact_dicts[:10]
        ]

        all_companies = await _crm.list_companies()
        query_lower = query.lower()
        companies = [
            {
                "name": co.name,
                "region": co.region or "",
                "industry": co.industry or "",
            }
            for co in all_companies
            if query_lower in (co.name or "").lower()
               or query_lower in (co.region or "").lower()
               or query_lower in (co.industry or "").lower()
        ][:10]

        return json.dumps({"contacts": contacts, "companies": companies}, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP search_crm failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_pipeline_summary() -> str:
    """Get the current Machinecraft sales pipeline summary.

    Returns active deals, total value, stage breakdown, and top deals.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        summary = await _crm.get_pipeline_summary()
        return json.dumps(summary, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_pipeline_summary failed")
        return f"Error: {exc}"


@mcp.tool()
async def draft_email(to: str, subject: str, context: str) -> str:
    """Draft a professional email using Ira's writing agent (Calliope).

    Provide the recipient, subject, and context/instructions for the email.
    Returns a formatted email draft.
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        calliope = _pantheon.get_agent("calliope")
        if calliope is None:
            return "Calliope agent not found."
        prompt = f"Draft an email to {to} with subject '{subject}'. Context: {context}"
        return await calliope.handle(prompt)
    except Exception as exc:
        logger.exception("MCP draft_email failed")
        return f"Error: {exc}"


@mcp.tool()
async def ingest_document(file_path: str) -> str:
    """Ingest a document into Ira's knowledge base.

    Supports PDF, DOCX, XLSX, CSV, TXT, PPTX, HTML, and MD files.
    The document will be chunked, embedded, and stored in Qdrant,
    with entities extracted into the Neo4j knowledge graph.
    """
    await _ensure_initialized()

    try:
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            return f"File not found: {file_path}"

        ingestor = _ingestor
        if ingestor is None:
            from ira.brain.document_ingestor import DocumentIngestor
            from ira.brain.embeddings import EmbeddingService
            from ira.brain.knowledge_graph import KnowledgeGraph
            from ira.brain.qdrant_manager import QdrantManager

            embedding = EmbeddingService()
            qdrant = QdrantManager(embedding_service=embedding)
            graph = KnowledgeGraph()
            ingestor = DocumentIngestor(qdrant=qdrant, knowledge_graph=graph)

        file_info = {
            "path": str(path),
            "name": path.name,
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
            "category": "mcp_upload",
        }
        chunks = await ingestor.ingest_file(file_info)
        return f"Ingested {path.name}: {chunks} chunks stored."
    except Exception as exc:
        logger.exception("MCP ingest_document failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_agent_list() -> str:
    """List all Ira Pantheon agents with their roles and descriptions."""
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        agents = []
        for name, agent in _pantheon.agents.items():
            agents.append({
                "name": name,
                "role": getattr(agent, "role", ""),
                "description": getattr(agent, "description", ""),
            })
        return json.dumps(agents, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_agent_list failed")
        return f"Error: {exc}"


@mcp.tool()
async def ask_agent(agent_name: str, question: str) -> str:
    """Ask a specific Ira agent a question directly.

    Available agents include: athena, clio, prometheus, hephaestus,
    plutus, calliope, vera, hermes, atlas, quotebuilder, and others.
    Use get_agent_list to see all available agents.
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        agent = _pantheon.get_agent(agent_name.lower())
        if agent is None:
            return f"Agent '{agent_name}' not found."
        return await agent.handle(question)
    except Exception as exc:
        logger.exception("MCP ask_agent failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def search_emails(
    from_address: str = "",
    subject: str = "",
    query: str = "",
    after: str = "",
    before: str = "",
    max_results: int = 10,
) -> str:
    """Search Machinecraft's Gmail inbox.

    Filter by sender address, subject keywords, free-form query,
    and date range (YYYY/MM/DD format). Returns matching emails
    with id, from, to, subject, date, and thread_id.
    """
    await _ensure_initialized()
    if _email_processor is None:
        return "Email processor not available."

    try:
        emails = await _email_processor.search_emails(
            from_address=from_address,
            subject=subject,
            query=query,
            after=after,
            before=before,
            max_results=max_results,
        )
        return json.dumps(
            [e.model_dump() for e in emails],
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.exception("MCP search_emails failed")
        return f"Error: {exc}"


@mcp.tool()
async def read_email_thread(thread_id: str) -> str:
    """Fetch the full email thread by Gmail thread ID.

    Returns all messages in the thread with sender, recipient,
    subject, body, and timestamps.
    """
    await _ensure_initialized()
    if _email_processor is None:
        return "Email processor not available."

    try:
        emails = await _email_processor.get_thread(thread_id)
        return json.dumps(
            {
                "thread_id": thread_id,
                "message_count": len(emails),
                "messages": [e.model_dump() for e in emails],
            },
            indent=2,
            default=str,
        )
    except Exception as exc:
        logger.exception("MCP read_email_thread failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def recall_memory(query: str, user_id: str = "global", limit: int = 5) -> str:
    """Search Ira's long-term semantic memory (Mem0).

    Returns relevant memories with content, score, and metadata.
    Use for recalling facts, preferences, and learned information.
    """
    await _ensure_initialized()
    if _long_term_memory is None:
        return "Long-term memory not available."

    try:
        results = await _long_term_memory.search(query, user_id=user_id, limit=limit)
        return json.dumps(results, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP recall_memory failed")
        return f"Error: {exc}"


@mcp.tool()
async def store_memory(content: str, user_id: str = "global", metadata: str = "") -> str:
    """Store a fact or learning in Ira's long-term memory.

    Provide the content to remember and an optional metadata JSON string
    (e.g. '{"source": "meeting", "topic": "pricing"}').
    """
    await _ensure_initialized()
    if _long_term_memory is None:
        return "Long-term memory not available."

    try:
        meta = json.loads(metadata) if metadata else None
        result = await _long_term_memory.store(content, user_id=user_id, metadata=meta)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP store_memory failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_conversation_history(
    user_id: str,
    channel: str = "mcp",
    limit: int = 20,
) -> str:
    """Retrieve recent conversation history for a user.

    Returns the last N messages with role, content, and timestamp.
    """
    await _ensure_initialized()
    if _conversation_memory is None:
        return "Conversation memory not available."

    try:
        history = await _conversation_memory.get_history(user_id, channel, limit=limit)
        return json.dumps(history, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_conversation_history failed")
        return f"Error: {exc}"


@mcp.tool()
async def check_relationship(contact_name: str) -> str:
    """Look up Ira's relationship profile with a contact.

    Returns warmth level, interaction count, memorable moments,
    learned preferences, and interaction dates.
    """
    await _ensure_initialized()
    if _relationship_memory is None:
        return "Relationship memory not available."

    try:
        rel = await _relationship_memory.get_relationship(contact_name)
        return json.dumps(_model_to_dict(rel), indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP check_relationship failed")
        return f"Error: {exc}"


@mcp.tool()
async def check_goals(contact_name: str) -> str:
    """Check active goals for a contact (e.g. quote follow-up, onboarding).

    Returns goal type, status, required slots, and progress.
    """
    await _ensure_initialized()
    if _goal_manager is None:
        return "Goal manager not available."

    try:
        goal = await _goal_manager.get_active_goal(contact_name)
        if goal is None:
            return json.dumps({"contact": contact_name, "active_goal": None})
        return json.dumps(_model_to_dict(goal), indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP check_goals failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# CRM OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_deal(deal_id: str) -> str:
    """Get a specific CRM deal by its ID.

    Returns deal title, value, stage, machine model, contact,
    expected close date, and notes.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        deal = await _crm.get_deal(deal_id)
        if deal is None:
            return f"Deal '{deal_id}' not found."
        return json.dumps(_model_to_dict(deal), indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_deal failed")
        return f"Error: {exc}"


@mcp.tool()
async def list_deals(
    stage: str = "",
    contact_id: str = "",
    limit: int = 20,
) -> str:
    """List CRM deals with optional filters.

    Filter by stage (e.g. 'new', 'proposal', 'negotiation', 'won', 'lost')
    and/or contact_id. Returns up to `limit` deals.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        filters: dict[str, Any] = {}
        if stage:
            filters["stage"] = stage
        if contact_id:
            filters["contact_id"] = contact_id
        deals = await _crm.list_deals(filters=filters if filters else None)
        result = [_model_to_dict(d) for d in deals[:limit]]
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP list_deals failed")
        return f"Error: {exc}"


@mcp.tool()
async def create_contact(
    name: str,
    email: str,
    company_name: str = "",
    role: str = "",
) -> str:
    """Create a new contact in the Machinecraft CRM.

    Returns the created contact record with its assigned ID.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        kwargs: dict[str, Any] = {"name": name, "email": email}
        if company_name:
            kwargs["company_name"] = company_name
        if role:
            kwargs["role"] = role
        contact = await _crm.create_contact(**kwargs)
        return json.dumps(_model_to_dict(contact), indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP create_contact failed")
        return f"Error: {exc}"


@mcp.tool()
async def update_deal(
    deal_id: str,
    stage: str = "",
    value: str = "",
    notes: str = "",
) -> str:
    """Update an existing CRM deal.

    Provide the deal_id and any fields to update: stage, value, or notes.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        kwargs: dict[str, Any] = {}
        if stage:
            kwargs["stage"] = stage
        if value:
            kwargs["value"] = value
        if notes:
            kwargs["notes"] = notes
        if not kwargs:
            return "No fields to update. Provide at least one of: stage, value, notes."
        deal = await _crm.update_deal(deal_id, **kwargs)
        if deal is None:
            return f"Deal '{deal_id}' not found."
        return json.dumps(_model_to_dict(deal), indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP update_deal failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_stale_leads(days: int = 14) -> str:
    """Find CRM leads with no activity in the specified number of days.

    Returns contacts that need follow-up attention.
    """
    await _ensure_initialized()
    if _crm is None:
        return "CRM not available."

    try:
        leads = await _crm.get_stale_leads(days=days)
        return json.dumps(leads, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_stale_leads failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def find_related_entities(name: str, max_hops: int = 2) -> str:
    """Explore the Neo4j knowledge graph around an entity.

    Returns nodes and relationships within max_hops of the named entity
    (person, company, machine, quote). Useful for understanding connections.
    """
    await _ensure_initialized()
    if _knowledge_graph is None:
        return "Knowledge graph not available."

    try:
        result = await _knowledge_graph.find_related_entities(name, max_hops=max_hops)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP find_related_entities failed")
        return f"Error: {exc}"


@mcp.tool()
async def find_company_contacts(company_name: str) -> str:
    """Find all contacts associated with a company in the knowledge graph.

    Returns names, emails, and roles of people linked to the company.
    """
    await _ensure_initialized()
    if _knowledge_graph is None:
        return "Knowledge graph not available."

    try:
        contacts = await _knowledge_graph.find_company_contacts(company_name)
        return json.dumps(contacts, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP find_company_contacts failed")
        return f"Error: {exc}"


@mcp.tool()
async def find_company_quotes(company_name: str) -> str:
    """Find all quotes associated with a company in the knowledge graph.

    Returns quote IDs, values, dates, statuses, and machine models.
    """
    await _ensure_initialized()
    if _knowledge_graph is None:
        return "Knowledge graph not available."

    try:
        quotes = await _knowledge_graph.find_company_quotes(company_name)
        return json.dumps(quotes, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP find_company_quotes failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# CORRECTION TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def submit_correction(
    entity: str,
    wrong_value: str,
    correct_value: str,
    category: str = "GENERAL",
) -> str:
    """Submit a factual correction so Nemesis can train Ira during Dream Mode.

    Use this when Ira gets a fact wrong — pricing, specs, customer info, etc.
    Valid categories: PRICING, SPECS, CUSTOMER, COMPETITOR, GENERAL.
    """
    from ira.brain.correction_store import CorrectionCategory, CorrectionStore

    try:
        cat = CorrectionCategory[category.upper()]
    except KeyError:
        cat = CorrectionCategory.GENERAL

    try:
        store = CorrectionStore()
        await store.initialize()
        row_id = await store.add_correction(
            entity=entity,
            new_value=correct_value,
            old_value=wrong_value,
            category=cat,
            source="cursor_mcp",
        )
        await store.close()
        return (
            f"Correction #{row_id} logged for entity '{entity}' "
            f"(category={cat.value}). Nemesis will process this during "
            "the next Dream Mode cycle."
        )
    except Exception as exc:
        logger.exception("MCP submit_correction failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# WEB TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for real-time information via Ira's Iris agent.

    Returns titles, URLs, and snippets from search results.
    Uses Tavily, Serper, or SearchAPI (whichever is configured).
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        iris = _pantheon.get_agent("iris")
        if iris is None:
            return "Iris agent not found."
        results = await iris.web_search(query, max_results=5)
        return json.dumps(results, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP web_search failed")
        return f"Error: {exc}"


@mcp.tool()
async def scrape_url(url: str) -> str:
    """Fetch a web page and return its content as clean markdown.

    Uses Crawl4AI to extract readable content from the URL.
    Useful for reading full articles after a web_search.
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        iris = _pantheon.get_agent("iris")
        if iris is None:
            return "Iris agent not found."
        return await iris.scrape_url(url)
    except Exception as exc:
        logger.exception("MCP scrape_url failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# PROJECT TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_project_status(project_name: str) -> str:
    """Get the status of a Machinecraft project via the Atlas agent.

    Returns project timeline, milestones, and current status.
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        atlas = _pantheon.get_agent("atlas")
        if atlas is None:
            return "Atlas agent not found."
        return await atlas.handle(f"What is the current status of the {project_name} project?")
    except Exception as exc:
        logger.exception("MCP get_project_status failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_overdue_milestones() -> str:
    """List all overdue project milestones via the Atlas agent.

    Returns projects and milestones that are past their due dates.
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        atlas = _pantheon.get_agent("atlas")
        if atlas is None:
            return "Atlas agent not found."
        return await atlas.handle("List all overdue project milestones.")
    except Exception as exc:
        logger.exception("MCP get_overdue_milestones failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# AGENT LOOP TOOLS (Plan → Execute → Observe → Compile)
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def plan_task(request: str, complexity: str = "auto") -> str:
    """Analyze a user request and create a structured multi-phase execution plan.

    Breaks down a complex request into phases, each mapped to the
    appropriate specialist agents. Use this for research, analysis,
    proposals, and reports that require multiple agents.

    Args:
        request: The user's natural language request.
        complexity: One of 'simple', 'moderate', 'complex', or 'auto'.
    """
    await _ensure_initialized()
    if _agent_loop is None:
        return json.dumps({"error": "Agent loop not available"})

    try:
        plan = await _agent_loop.plan(request, complexity=complexity)
        return json.dumps({
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "complexity": plan.complexity,
            "phases": [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "agents": p.agents,
                    "delegation_type": p.delegation_type,
                    "expected_output": p.expected_output,
                    "depends_on": p.depends_on,
                }
                for p in plan.phases
            ],
            "status": plan.status,
        }, indent=2)
    except Exception as exc:
        logger.exception("plan_task failed")
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def execute_phase(plan_id: str, phase_id: int) -> str:
    """Execute a specific phase of an existing plan.

    Runs the agents assigned to this phase, collects their responses,
    and lets Athena decide whether to continue, re-plan, or request
    clarification.

    Args:
        plan_id: The ID returned by plan_task.
        phase_id: The phase number to execute (1-indexed).
    """
    await _ensure_initialized()
    if _agent_loop is None:
        return json.dumps({"error": "Agent loop not available"})

    plan = _agent_loop.get_plan(plan_id)
    if plan is None:
        return json.dumps({"error": f"Plan '{plan_id}' not found. Call plan_task first."})

    phase = next((p for p in plan.phases if p.id == phase_id), None)
    if phase is None:
        return json.dumps({"error": f"Phase {phase_id} not found in plan."})

    try:
        result = await _agent_loop.execute_phase(plan, phase)

        if result.decision == LoopDecision.REPLAN:
            await _agent_loop.replan(plan, result)

        output = {
            "plan_id": plan_id,
            "phase_id": phase_id,
            "phase_title": phase.title,
            "agents_consulted": list(result.agent_responses.keys()),
            "results": result.agent_responses,
            "decision": result.decision.value,
            "decision_reason": result.decision_reason,
            "is_final_phase": plan.is_complete,
            "status": plan.status,
        }
        if result.clarification_question:
            output["clarification_question"] = result.clarification_question

        return json.dumps(output, indent=2, default=str)
    except Exception as exc:
        logger.exception("execute_phase failed")
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def generate_report(
    plan_id: str,
    title: str = "Ira Report",
) -> str:
    """Compile all phase results from a completed plan into a structured report.

    Uses Calliope (Chief Writer) to synthesize findings from all phases
    into a professional document. Call this after all phases are executed.

    Args:
        plan_id: The plan whose results should be compiled.
        title: Title for the report.
    """
    await _ensure_initialized()
    if _agent_loop is None:
        return json.dumps({"error": "Agent loop not available"})

    plan = _agent_loop.get_plan(plan_id)
    if plan is None:
        return json.dumps({"error": f"Plan '{plan_id}' not found."})

    try:
        report_content = await _agent_loop.compile(plan, title=title)

        from pathlib import Path
        from datetime import datetime

        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)
        slug = title.lower().replace(" ", "_")[:40]
        md_path = report_dir / f"{slug}_{datetime.now().strftime('%Y%m%d')}.md"
        md_path.write_text(report_content, encoding="utf-8")

        return json.dumps({
            "format": "markdown",
            "path": str(md_path),
            "content_preview": report_content[:500],
            "full_content": report_content,
        }, indent=2)
    except Exception as exc:
        logger.exception("generate_report failed")
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """Get current state for a server-side task orchestrator task."""
    await _ensure_initialized()
    if _task_orchestrator is None:
        return json.dumps({"error": "Task orchestrator not available"})
    state = await _task_orchestrator.get_task_state(task_id)
    if state is None:
        return json.dumps({"error": f"Task '{task_id}' not found"})
    return json.dumps(state, indent=2, default=str)


@mcp.tool()
async def abort_task(task_id: str, reason: str = "") -> str:
    """Request cancellation for a running server-side task."""
    await _ensure_initialized()
    if _task_orchestrator is None:
        return json.dumps({"error": "Task orchestrator not available"})
    ok = await _task_orchestrator.abort_task(task_id, reason=reason)
    if not ok:
        return json.dumps({"error": f"Task '{task_id}' not found"})
    return json.dumps(
        {"task_id": task_id, "status": "aborting", "reason": reason},
        indent=2,
        default=str,
    )


@mcp.tool()
async def list_tasks(limit: int = 20) -> str:
    """List recent server-side task states for operator visibility."""
    await _ensure_initialized()
    if _task_orchestrator is None:
        return json.dumps({"error": "Task orchestrator not available"})
    tasks = await _task_orchestrator.list_tasks(limit=limit)
    return json.dumps({"count": len(tasks), "tasks": tasks}, indent=2, default=str)


@mcp.tool()
async def get_task_events(task_id: str, limit: int = 200) -> str:
    """Fetch recent event timeline for a task."""
    await _ensure_initialized()
    if _task_orchestrator is None:
        return json.dumps({"error": "Task orchestrator not available"})
    state = await _task_orchestrator.get_task_state(task_id)
    if state is None:
        return json.dumps({"error": f"Task '{task_id}' not found"})
    events = await _task_orchestrator.get_task_events(task_id, limit=limit)
    return json.dumps(
        {"task_id": task_id, "count": len(events), "events": events},
        indent=2,
        default=str,
    )


@mcp.tool()
async def retry_task(task_id: str, from_phase: int = 0) -> str:
    """Retry a server-side task from a specific phase index."""
    await _ensure_initialized()
    if _task_orchestrator is None:
        return json.dumps({"error": "Task orchestrator not available"})
    result = await _task_orchestrator.retry_task(task_id, from_phase=from_phase)
    return json.dumps(
        {
            "task_id": result.task_id,
            "status": result.status,
            "summary": result.summary,
            "file_path": result.file_path,
            "file_format": result.file_format,
        },
        indent=2,
        default=str,
    )


# ═══════════════════════════════════════════════════════════════════════════
# DREAM MODE & METACOGNITION TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def trigger_dream_mode() -> str:
    """Trigger Ira's Dream Mode consolidation cycle immediately.

    Runs the full 11-stage dream cycle: memory consolidation, gap resolution,
    creative connections, campaign insights, and Nemesis training.
    Returns a report with what was consolidated and discovered.
    """
    await _ensure_initialized()

    try:
        from ira.memory.dream_mode import DreamMode
        from ira.memory.episodic import EpisodicMemory
        from ira.memory.long_term import LongTermMemory
        from ira.memory.conversation import ConversationMemory
        from ira.service_keys import ServiceKey as SK

        long_term = _long_term_memory
        if long_term is None:
            long_term = LongTermMemory()

        episodic = None
        conversation = _conversation_memory

        if _pantheon is not None:
            mnemosyne = _pantheon.get_agent("mnemosyne")
            if mnemosyne and hasattr(mnemosyne, "_services"):
                episodic = mnemosyne._services.get(SK.EPISODIC_MEMORY)

        if episodic is None:
            episodic = EpisodicMemory(long_term=long_term)
            await episodic.initialize()

        if conversation is None:
            conversation = ConversationMemory()
            await conversation.initialize()

        dm = DreamMode(
            long_term=long_term,
            episodic=episodic,
            conversation=conversation,
            retriever=_retriever,
            crm=_crm,
        )
        await dm.initialize()
        report = await dm.run_dream_cycle()
        await dm.close()

        return json.dumps({
            "cycle_date": str(report.cycle_date),
            "memories_consolidated": report.memories_consolidated,
            "gaps_identified": report.gaps_identified,
            "creative_connections": report.creative_connections,
            "campaign_insights": report.campaign_insights,
            "stage_results": report.stage_results,
        }, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP trigger_dream_mode failed")
        return f"Error: {exc}"


@mcp.tool()
async def get_knowledge_gaps(limit: int = 10) -> str:
    """Show knowledge gaps Ira has identified during conversations.

    Returns unresolved gaps so you know what documents to upload next.
    Each gap includes the original query, the knowledge state, and
    specific missing information.
    """
    try:
        from ira.memory.metacognition import Metacognition

        meta = Metacognition()
        await meta.initialize()
        gaps = await meta.get_unresolved_gaps(limit=limit)
        await meta.close()

        if not gaps:
            return "No unresolved knowledge gaps found."

        return json.dumps(gaps, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP get_knowledge_gaps failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# BOARD MEETING TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def convene_board_meeting(
    topic: str,
    participants: str = "all",
) -> str:
    """Convene a Pantheon Board Meeting for complex strategic questions.

    Multiple agents debate the topic and Athena synthesizes a final answer.
    Set participants to a comma-separated list of agent names, or "all"
    for a full board meeting (e.g. "prometheus,plutus,hephaestus").
    """
    await _ensure_initialized()
    if _pantheon is None:
        return "Pantheon not available."

    try:
        names: list[str] | None = None
        if participants.strip().lower() != "all":
            names = [n.strip().lower() for n in participants.split(",") if n.strip()]

        minutes = await _pantheon.board_meeting(topic=topic, participants=names)

        return json.dumps({
            "topic": minutes.topic,
            "participants": minutes.participants,
            "contributions": minutes.contributions,
            "synthesis": minutes.synthesis,
            "action_items": minutes.action_items,
        }, indent=2, default=str)
    except Exception as exc:
        logger.exception("MCP convene_board_meeting failed")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM STATUS TOOLS
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_system_status() -> str:
    """Check Ira's system health and agent power levels.

    Returns two sections:
    1. Service health — status of Qdrant, Neo4j, PostgreSQL, OpenAI, Voyage
    2. Agent leaderboard — top agents ranked by performance score and tier
    """
    await _ensure_initialized()

    result: dict[str, Any] = {}

    try:
        from ira.brain.power_levels import PowerLevelTracker

        tracker = PowerLevelTracker()
        await tracker._load()
        leaderboard = tracker.get_leaderboard()
        result["agent_leaderboard"] = leaderboard[:10]
    except Exception as exc:
        logger.warning("Power level check failed: %s", exc)
        result["agent_leaderboard"] = f"Error: {exc}"

    try:
        from ira.brain.embeddings import EmbeddingService
        from ira.brain.knowledge_graph import KnowledgeGraph
        from ira.brain.qdrant_manager import QdrantManager
        from ira.systems.immune import ImmuneSystem

        embedding = EmbeddingService()
        qdrant = QdrantManager(embedding_service=embedding)
        graph = KnowledgeGraph()
        immune = ImmuneSystem(
            qdrant=qdrant,
            knowledge_graph=graph,
            embedding_service=embedding,
        )
        health = await immune.run_startup_validation()
        result["service_health"] = {
            name: {"status": info["status"], "latency_ms": info.get("latency_ms")}
            for name, info in health.items()
        }
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)
        result["service_health"] = f"Error: {exc}"

    return json.dumps(result, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for running the MCP server."""
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
