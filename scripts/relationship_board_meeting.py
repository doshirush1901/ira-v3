#!/usr/bin/env python3
"""Relationship Enrichment Board Meeting — every agent contributes graph edges.

Runs a targeted board meeting where each agent searches their domain for
entities and relationships, then writes the discovered relationships
directly to Neo4j via the KnowledgeGraph.

Usage:
    python scripts/relationship_board_meeting.py
    python scripts/relationship_board_meeting.py --dry-run
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("relationship_board")


RELATIONSHIP_TOPIC = """\
KNOWLEDGE GRAPH ENRICHMENT SESSION — Relationship Discovery

You are participating in a special board meeting focused on enriching our
knowledge graph. Your job is to search your domain knowledge and return
STRUCTURED RELATIONSHIPS that should exist in our graph.

Return ONLY a JSON object with this exact schema (no markdown, no explanation):
{{
  "relationships": [
    {{
      "from_type": "Company|Person|Machine",
      "from_key": "the entity name/email/model",
      "rel": "WORKS_AT|INTERESTED_IN|QUOTED_FOR|SUPPLIES|MANUFACTURES|COMPETES_WITH|CONTACTED_BY|REFERRED_BY",
      "to_type": "Company|Person|Machine",
      "to_key": "the entity name/email/model"
    }}
  ],
  "reasoning": "Brief explanation of where you found these relationships"
}}

RELATIONSHIP TYPES:
- WORKS_AT: Person -> Company
- INTERESTED_IN: Company -> Machine (enquired about, shown interest)
- QUOTED_FOR: Company -> Machine (quote was sent)
- SUPPLIES: Company -> Company (vendor/supplier relationship)
- MANUFACTURES: Company -> Machine
- COMPETES_WITH: Company -> Company
- CONTACTED_BY: Person -> Person
- REFERRED_BY: Company -> Company or Person -> Person

RULES:
- Use REAL company names, email addresses, and machine models from your knowledge
- Machine models look like: PF1-C-2015, AM-5060, RF-200, SL-100
- Be thorough — extract EVERY relationship you can find
- Only include relationships you are confident about from the data
"""

AGENT_PROMPTS: dict[str, str] = {
    "prometheus": (
        "Focus on SALES relationships: which companies are interested in which machines? "
        "Which contacts work at which companies? Which deals involve which machines? "
        "Search your CRM data and pipeline knowledge."
    ),
    "plutus": (
        "Focus on QUOTE/PRICING relationships: which companies have been quoted for which machines? "
        "What are the quote values? Search your pricing and quote history."
    ),
    "hermes": (
        "Focus on MARKETING/LEAD relationships: which leads are from which companies? "
        "Which companies have been contacted? Which regions are interested in which machines?"
    ),
    "hera": (
        "Focus on VENDOR/SUPPLY CHAIN relationships: which companies supply parts to Machinecraft? "
        "Which vendors supply which components? Search your procurement knowledge."
    ),
    "hephaestus": (
        "Focus on PRODUCTION/MACHINE relationships: which machines does Machinecraft manufacture? "
        "What are the machine model families and their relationships? "
        "Which companies have ordered which machines?"
    ),
    "clio": (
        "Focus on RESEARCH relationships: search the knowledge base broadly for any "
        "company-to-company, person-to-company, or company-to-machine relationships "
        "you can find in documents, emails, and reports."
    ),
    "atlas": (
        "Focus on PROJECT relationships: which companies have active projects? "
        "Which machines are being delivered to which customers? "
        "Search your project logbook data."
    ),
    "iris": (
        "Focus on EXTERNAL INTELLIGENCE: which companies compete with Machinecraft? "
        "Which companies are in the same industry? Search your external knowledge."
    ),
    "chiron": (
        "Focus on SALES TRAINING patterns: from your training logs, which companies "
        "have been discussed in sales coaching? Which contacts have been trained on?"
    ),
    "cadmus": (
        "Focus on CASE STUDY relationships: which companies are featured in case studies? "
        "Which machines were delivered to which customers in success stories?"
    ),
    "asclepius": (
        "Focus on QUALITY relationships: which machines have had quality issues at which "
        "customer sites? Which companies have punch lists or FAT tracking?"
    ),
    "delphi": (
        "Focus on CONTACT CLASSIFICATION: from your email analysis, which people work at "
        "which companies? Which contacts have communicated with each other?"
    ),
}


async def run_relationship_meeting(dry_run: bool = False):
    """Run the relationship enrichment meeting with minimal memory footprint.

    Uses a lightweight approach: one KnowledgeGraph connection for writes,
    one retriever for KB search, and direct LLM calls per agent (no full
    Pantheon in memory).
    """
    import gc
    import httpx
    from ira.brain.embeddings import EmbeddingService
    from ira.brain.knowledge_graph import KnowledgeGraph
    from ira.brain.qdrant_manager import QdrantManager
    from ira.brain.retriever import UnifiedRetriever
    from ira.config import get_settings

    settings = get_settings()
    openai_key = settings.llm.openai_api_key.get_secret_value()
    openai_model = settings.llm.openai_model

    logger.info("Bootstrapping lightweight services...")
    embedding = EmbeddingService()
    qdrant = QdrantManager(embedding_service=embedding)
    graph = KnowledgeGraph()
    retriever = UnifiedRetriever(qdrant=qdrant, graph=graph)

    before = await graph.graph_stats()
    logger.info(
        "Before: %d nodes, %d rels, %d orphans (ratio: %.3f)",
        before["nodes"], before["relationships"], before["orphans"], before["ratio"],
    )

    async def _call_llm(system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "model": openai_model,
                    "temperature": 0.1,
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

    agent_roles = {
        "prometheus": "Chief Revenue Officer",
        "plutus": "Chief Financial Officer",
        "hermes": "Chief Marketing Officer",
        "hera": "Vendor/Procurement Manager",
        "hephaestus": "Chief Production Officer",
        "clio": "Research Director",
        "atlas": "Project Manager",
        "iris": "External Intelligence",
        "chiron": "Sales Trainer",
        "cadmus": "CMO / Case Studies",
        "asclepius": "Quality Manager",
        "delphi": "Classification Specialist",
    }

    total_discovered = 0
    total_written = 0
    agent_results: dict[str, dict] = {}

    for agent_name, domain_prompt in AGENT_PROMPTS.items():
        role = agent_roles.get(agent_name, "Specialist")
        logger.info("Consulting %s (%s)...", agent_name, role)

        kb_context = ""
        try:
            kb_results = await retriever.search(
                domain_prompt, limit=10, sources=["qdrant"],
            )
            parts = []
            for r in kb_results:
                parts.append(f"- [{r.get('source', '?')}] {r.get('content', '')[:400]}")
            kb_context = "\n".join(parts)
        except Exception:
            logger.debug("KB search failed for %s, proceeding without context", agent_name)

        sys_prompt = (
            f"You are {agent_name}, the {role} at Machinecraft, "
            f"an industrial packaging machinery company."
        )
        user_prompt = RELATIONSHIP_TOPIC + "\n\nYOUR SPECIFIC FOCUS:\n" + domain_prompt
        if kb_context:
            user_prompt += "\n\nKNOWLEDGE BASE CONTEXT:\n" + kb_context

        try:
            response = await _call_llm(sys_prompt, user_prompt)
        except Exception:
            logger.exception("Agent %s LLM call failed", agent_name)
            agent_results[agent_name] = {"error": True, "discovered": 0, "written": 0}
            continue

        relationships = _parse_relationships(response, agent_name)
        discovered = len(relationships)
        written = 0

        if relationships:
            if dry_run:
                for rel in relationships:
                    logger.info(
                        "  [DRY RUN] %s: (%s:%s)-[%s]->(%s:%s)",
                        agent_name,
                        rel["from_type"], rel["from_key"],
                        rel["rel"],
                        rel["to_type"], rel["to_key"],
                    )
                written = discovered
            else:
                for rel in relationships:
                    try:
                        ok = await graph.add_relationship(
                            from_type=rel["from_type"],
                            from_key=rel["from_key"],
                            rel_type=rel["rel"],
                            to_type=rel["to_type"],
                            to_key=rel["to_key"],
                        )
                        if ok:
                            written += 1
                    except Exception:
                        logger.debug("Failed to write rel: %s", rel, exc_info=True)

        total_discovered += discovered
        total_written += written
        agent_results[agent_name] = {
            "discovered": discovered,
            "written": written,
            "error": False,
        }
        logger.info(
            "  %s contributed %d relationships (%d written)",
            agent_name, discovered, written,
        )
        gc.collect()

    after = await graph.graph_stats()
    logger.info(
        "After: %d nodes, %d rels, %d orphans (ratio: %.3f)",
        after["nodes"], after["relationships"], after["orphans"], after["ratio"],
    )
    logger.info(
        "Delta: %+d nodes, %+d rels, %+d orphans",
        after["nodes"] - before["nodes"],
        after["relationships"] - before["relationships"],
        after["orphans"] - before["orphans"],
    )

    print("\n" + "=" * 60)
    print("  RELATIONSHIP BOARD MEETING RESULTS")
    print("=" * 60)
    print(f"\n  {'Agent':<15} {'Found':>8} {'Written':>8}")
    print(f"  {'─' * 31}")
    for name, result in sorted(agent_results.items()):
        status = "ERROR" if result.get("error") else ""
        print(f"  {name:<15} {result['discovered']:>8} {result['written']:>8}  {status}")
    print(f"  {'─' * 31}")
    print(f"  {'TOTAL':<15} {total_discovered:>8} {total_written:>8}")
    print(f"\n  Before: {before['relationships']} rels (ratio {before['ratio']:.3f})")
    print(f"  After:  {after['relationships']} rels (ratio {after['ratio']:.3f})")
    print(f"  Orphans: {before['orphans']} -> {after['orphans']}")
    print("=" * 60 + "\n")

    output_dir = Path("data/board_meetings")
    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"{ts}_relationship_meeting.json"
    report_path.write_text(json.dumps({
        "before": before,
        "after": after,
        "agent_results": agent_results,
        "total_discovered": total_discovered,
        "total_written": total_written,
        "dry_run": dry_run,
    }, indent=2, default=str))
    logger.info("Report saved to %s", report_path)

    await graph.close()


def _parse_relationships(response: str, agent_name: str) -> list[dict]:
    """Extract relationship dicts from an agent's response."""
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    json_start = cleaned.find("{")
    json_end = cleaned.rfind("}") + 1
    if json_start == -1 or json_end <= json_start:
        logger.warning("%s: no JSON found in response", agent_name)
        return []

    try:
        data = json.loads(cleaned[json_start:json_end])
    except json.JSONDecodeError:
        logger.warning("%s: failed to parse JSON response", agent_name)
        return []

    rels = data.get("relationships", [])
    if not isinstance(rels, list):
        return []

    valid = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        if all(k in r for k in ("from_type", "from_key", "rel", "to_type", "to_key")):
            if r["from_key"] and r["to_key"]:
                valid.append(r)

    logger.info("%s: parsed %d valid relationships from %d raw", agent_name, len(valid), len(rels))
    return valid


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Relationship enrichment board meeting")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Neo4j")
    args = parser.parse_args()

    asyncio.run(run_relationship_meeting(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
