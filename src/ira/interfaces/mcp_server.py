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

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "ira",
    instructions=(
        "Ira is the AI that runs Machinecraft, an industrial machinery company. "
        "Use these tools to search Ira's knowledge base, query the CRM, "
        "get sales pipeline data, draft emails, and ingest documents."
    ),
)

_pantheon: Any = None
_shared_services: dict[str, Any] = {}
_pipeline: Any = None
_retriever: Any = None
_crm: Any = None
_ingestor: Any = None
_initialized = False


async def _ensure_initialized() -> None:
    """Lazy-init the Ira subsystems on first tool call."""
    global _pantheon, _shared_services, _pipeline, _retriever, _crm, _ingestor, _initialized
    if _initialized:
        return

    from ira.interfaces.cli import _build_pantheon, _build_pipeline
    from ira.service_keys import ServiceKey as SK

    _pantheon, _shared_services = _build_pantheon()
    _retriever = _shared_services.get(SK.RETRIEVER)
    _crm = _shared_services.get(SK.CRM)

    _pipeline, _ = await _build_pipeline(_pantheon, _shared_services)

    digestive = _shared_services.get(SK.DIGESTIVE)
    if digestive and hasattr(digestive, "_ingestor"):
        _ingestor = digestive._ingestor

    _initialized = True
    logger.info("Ira MCP server initialized")


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


def main() -> None:
    """Entry point for running the MCP server."""
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
