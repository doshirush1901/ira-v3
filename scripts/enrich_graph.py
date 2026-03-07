"""Enrich Neo4j graph by connecting orphan nodes and inferring relationships.

The backfill_relationships.py script only adds relationships the LLM finds
in document text.  This script takes a different approach: it looks at the
*existing* graph structure and uses deterministic rules to create missing
relationships between nodes that are already there.

Strategies:
  1. WORKS_AT from email domains — match Person.email domain to Company.website or name
  2. INTERESTED_IN from quotes — if Company has QUOTED_TO from a Quote that QUOTES_MACHINE,
     infer Company -[INTERESTED_IN]-> Machine
  3. MANUFACTURES for Machinecraft — all Machine nodes are Machinecraft products
  4. Orphan cleanup — remove label-less nodes created by graph_consolidation
  5. Person-Company from name matching — Person.name contains Company.name substring

Usage:
    python scripts/enrich_graph.py
    python scripts/enrich_graph.py --dry-run
    python scripts/enrich_graph.py --strategy domain,quotes,manufactures
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ira.brain.knowledge_graph import KnowledgeGraph  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


async def count_stats(graph: KnowledgeGraph) -> dict[str, int]:
    """Get current node and relationship counts."""
    rows = await graph.run_cypher("MATCH (n) RETURN count(n) AS nodes")
    nodes = rows[0]["nodes"] if rows else 0
    rows = await graph.run_cypher("MATCH ()-[r]->() RETURN count(r) AS rels")
    rels = rows[0]["rels"] if rows else 0
    rows = await graph.run_cypher(
        "MATCH (n) WHERE NOT (n)--() RETURN count(n) AS orphans"
    )
    orphans = rows[0]["orphans"] if rows else 0
    return {"nodes": nodes, "relationships": rels, "orphans": orphans}


async def strategy_domain_matching(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Person -> Company by matching email domain to company name/website.

    For each Person with an email, extract the domain and try to find a
    Company whose name or website contains that domain (minus common suffixes).
    """
    persons = await graph.run_cypher(
        "MATCH (p:Person) WHERE p.email IS NOT NULL AND p.email <> '' "
        "AND NOT (p)-[:WORKS_AT]->() "
        "RETURN p.email AS email, p.name AS name"
    )
    if not persons:
        logger.info("Domain matching: no unlinked persons found")
        return 0

    companies = await graph.run_cypher(
        "MATCH (c:Company) RETURN c.name AS name, c.website AS website"
    )
    company_lookup: dict[str, str] = {}
    for c in companies:
        cname = c.get("name", "")
        if not cname:
            continue
        company_lookup[cname.lower()] = cname
        website = c.get("website", "") or ""
        if website:
            domain = website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()
            company_lookup[domain] = cname

    created = 0
    for person in persons:
        email = person.get("email", "")
        if "@" not in email:
            continue
        domain = email.split("@")[1].lower()
        domain_base = domain.rsplit(".", 1)[0]  # strip TLD

        matched_company = None
        if domain in company_lookup:
            matched_company = company_lookup[domain]
        elif domain_base in company_lookup:
            matched_company = company_lookup[domain_base]
        else:
            for ckey, cname in company_lookup.items():
                if domain_base in ckey or ckey in domain_base:
                    matched_company = cname
                    break

        if matched_company:
            if dry_run:
                logger.info(
                    "[DRY RUN] WORKS_AT: %s -> %s (via domain %s)",
                    email, matched_company, domain,
                )
            else:
                ok = await graph.add_relationship(
                    "Person", email, "WORKS_AT", "Company", matched_company,
                )
                if ok:
                    created += 1

    logger.info("Domain matching: %s %d WORKS_AT relationships",
                "would create" if dry_run else "created", created)
    return created


async def strategy_quotes_to_interested(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Infer Company -[INTERESTED_IN]-> Machine from existing quote chains.

    If (q:Quote)-[:QUOTED_TO]->(c:Company) and (q)-[:QUOTES_MACHINE]->(m:Machine),
    then c is INTERESTED_IN m.
    """
    pairs = await graph.run_cypher(
        "MATCH (q:Quote)-[:QUOTED_TO]->(c:Company), "
        "(q)-[:QUOTES_MACHINE]->(m:Machine) "
        "WHERE NOT (c)-[:INTERESTED_IN]->(m) "
        "RETURN DISTINCT c.name AS company, m.model AS machine"
    )
    if not pairs:
        logger.info("Quote inference: no new INTERESTED_IN pairs found")
        return 0

    created = 0
    for pair in pairs:
        company = pair.get("company", "")
        machine = pair.get("machine", "")
        if not company or not machine:
            continue
        if dry_run:
            logger.info("[DRY RUN] INTERESTED_IN: %s -> %s", company, machine)
        else:
            ok = await graph.add_relationship(
                "Company", company, "INTERESTED_IN", "Machine", machine,
            )
            if ok:
                created += 1

    logger.info("Quote inference: %s %d INTERESTED_IN relationships",
                "would create" if dry_run else "created", created)
    return created


async def strategy_manufactures(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Add Machinecraft -[MANUFACTURES]-> Machine for all Machine nodes."""
    await graph.run_cypher(
        "MERGE (c:Company {name: 'Machinecraft'}) "
        "SET c.industry = 'Industrial Machinery', c.region = 'India'"
    )

    machines = await graph.run_cypher(
        "MATCH (m:Machine) "
        "WHERE NOT (:Company {name: 'Machinecraft'})-[:MANUFACTURES]->(m) "
        "RETURN m.model AS model"
    )
    if not machines:
        logger.info("Manufactures: all machines already linked")
        return 0

    created = 0
    for m in machines:
        model = m.get("model", "")
        if not model:
            continue
        if dry_run:
            logger.info("[DRY RUN] MANUFACTURES: Machinecraft -> %s", model)
        else:
            ok = await graph.add_relationship(
                "Company", "Machinecraft", "MANUFACTURES", "Machine", model,
            )
            if ok:
                created += 1

    logger.info("Manufactures: %s %d MANUFACTURES relationships",
                "would create" if dry_run else "created", created)
    return created


async def strategy_cleanup_orphans(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Remove label-less orphan nodes (created by graph_consolidation's MERGE without labels)."""
    orphans = await graph.run_cypher(
        "MATCH (n) WHERE size(labels(n)) = 0 AND NOT (n)--() "
        "RETURN count(n) AS c"
    )
    count = orphans[0]["c"] if orphans else 0

    if count == 0:
        logger.info("Orphan cleanup: no label-less orphans found")
        return 0

    if dry_run:
        logger.info("[DRY RUN] Would delete %d label-less orphan nodes", count)
    else:
        await graph.run_cypher(
            "MATCH (n) WHERE size(labels(n)) = 0 AND NOT (n)--() DELETE n"
        )
        logger.info("Deleted %d label-less orphan nodes", count)

    return count


async def strategy_labeled_orphans(graph: KnowledgeGraph, dry_run: bool) -> int:
    """For labeled orphan nodes (Company, Person, Machine with no relationships),
    try to connect them using property-based heuristics."""
    persons = await graph.run_cypher(
        "MATCH (p:Person) WHERE NOT (p)--() AND p.name IS NOT NULL "
        "RETURN p.email AS email, p.name AS name"
    )

    created = 0
    if persons:
        companies = await graph.run_cypher(
            "MATCH (c:Company) RETURN c.name AS name"
        )
        company_names = {c["name"].lower(): c["name"] for c in companies if c.get("name")}

        for p in persons:
            pname = (p.get("name") or "").lower()
            email = p.get("email") or ""
            if not email:
                continue
            domain = email.split("@")[1].lower() if "@" in email else ""
            domain_base = domain.rsplit(".", 1)[0] if domain else ""

            for ckey, cname in company_names.items():
                if (domain_base and (domain_base in ckey or ckey in domain_base)) or \
                   (len(ckey) > 3 and ckey in pname):
                    if dry_run:
                        logger.info("[DRY RUN] WORKS_AT (orphan): %s -> %s", email, cname)
                    else:
                        ok = await graph.add_relationship(
                            "Person", email, "WORKS_AT", "Company", cname,
                        )
                        if ok:
                            created += 1
                    break

    orphan_companies = await graph.run_cypher(
        "MATCH (c:Company) WHERE NOT (c)--() AND c.name IS NOT NULL "
        "RETURN c.name AS name"
    )
    if orphan_companies:
        machines = await graph.run_cypher(
            "MATCH (m:Machine) RETURN m.model AS model"
        )
        machine_models = [m["model"] for m in machines if m.get("model")]

        for c in orphan_companies:
            cname = c.get("name", "")
            if not cname:
                continue
            search_results = await graph.run_cypher(
                "MATCH (q:Quote)-[:QUOTED_TO]->(target:Company {name: $name}) "
                "RETURN count(q) AS qcount",
                {"name": cname},
            )
            if search_results and search_results[0].get("qcount", 0) > 0:
                continue

    logger.info("Labeled orphan linking: %s %d relationships",
                "would create" if dry_run else "created", created)
    return created


async def strategy_person_company_cooccurrence(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Person to Company when the person's name property contains the company name
    (common in extracted entities where company wasn't set)."""
    results = await graph.run_cypher(
        "MATCH (p:Person), (c:Company) "
        "WHERE NOT (p)-[:WORKS_AT]->(c) "
        "AND p.name IS NOT NULL AND c.name IS NOT NULL "
        "AND size(c.name) > 3 "
        "AND toLower(p.role) CONTAINS toLower(c.name) "
        "RETURN p.email AS email, c.name AS company LIMIT 500"
    )
    if not results:
        logger.info("Person-Company co-occurrence: no matches")
        return 0

    created = 0
    for r in results:
        email = r.get("email", "")
        company = r.get("company", "")
        if not email or not company:
            continue
        if dry_run:
            logger.info("[DRY RUN] WORKS_AT (co-occur): %s -> %s", email, company)
        else:
            ok = await graph.add_relationship(
                "Person", email, "WORKS_AT", "Company", company,
            )
            if ok:
                created += 1

    logger.info("Person-Company co-occurrence: %s %d relationships",
                "would create" if dry_run else "created", created)
    return created


async def strategy_knowledge_to_machine(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Knowledge nodes to Machine nodes via the entity property."""
    if dry_run:
        rows = await graph.run_cypher(
            "MATCH (k:Knowledge), (m:Machine) "
            "WHERE k.entity IS NOT NULL AND k.entity = m.model "
            "AND NOT (k)-[:DESCRIBES]->(m) "
            "RETURN count(*) AS c"
        )
        count = rows[0]["c"] if rows else 0
        logger.info("[DRY RUN] Would create %d Knowledge-[DESCRIBES]->Machine links", count)
        return count

    result = await graph.run_cypher(
        "MATCH (k:Knowledge), (m:Machine) "
        "WHERE k.entity IS NOT NULL AND k.entity = m.model "
        "AND NOT (k)-[:DESCRIBES]->(m) "
        "MERGE (k)-[:DESCRIBES]->(m) "
        "RETURN count(*) AS created"
    )
    created = result[0].get("created", 0) if result else 0
    logger.info("Knowledge->Machine: created %d DESCRIBES relationships", created)
    return created


async def strategy_knowledge_to_source(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Knowledge nodes to Source nodes via source_file/path."""
    if dry_run:
        rows = await graph.run_cypher(
            "MATCH (k:Knowledge), (s:Source) "
            "WHERE k.source_file IS NOT NULL "
            "AND s.path CONTAINS k.source_file "
            "AND NOT (k)-[:FROM_SOURCE]->(s) "
            "RETURN count(*) AS c"
        )
        count = rows[0]["c"] if rows else 0
        logger.info("[DRY RUN] Would create %d Knowledge-[FROM_SOURCE]->Source links", count)
        return count

    result = await graph.run_cypher(
        "MATCH (k:Knowledge), (s:Source) "
        "WHERE k.source_file IS NOT NULL "
        "AND s.path CONTAINS k.source_file "
        "AND NOT (k)-[:FROM_SOURCE]->(s) "
        "MERGE (k)-[:FROM_SOURCE]->(s) "
        "RETURN count(*) AS created"
    )
    created = result[0].get("created", 0) if result else 0
    logger.info("Knowledge->Source: created %d FROM_SOURCE relationships", created)
    return created


async def strategy_entity_to_machine(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Entity nodes to Machine nodes when Entity.name matches Machine.model."""
    if dry_run:
        rows = await graph.run_cypher(
            "MATCH (e:Entity), (m:Machine) "
            "WHERE e.name = m.model AND NOT (e)-[:REFERS_TO]->(m) "
            "RETURN count(*) AS c"
        )
        count = rows[0]["c"] if rows else 0
        logger.info("[DRY RUN] Would create %d Entity-[REFERS_TO]->Machine links", count)
        return count

    result = await graph.run_cypher(
        "MATCH (e:Entity), (m:Machine) "
        "WHERE e.name = m.model AND NOT (e)-[:REFERS_TO]->(m) "
        "MERGE (e)-[:REFERS_TO]->(m) "
        "RETURN count(*) AS created"
    )
    created = result[0].get("created", 0) if result else 0
    logger.info("Entity->Machine: created %d REFERS_TO relationships", created)
    return created


async def strategy_entity_to_company(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Entity nodes to Company nodes when Entity.name matches Company.name."""
    if dry_run:
        rows = await graph.run_cypher(
            "MATCH (e:Entity), (c:Company) "
            "WHERE e.name = c.name AND NOT (e)-[:REFERS_TO]->(c) "
            "RETURN count(*) AS c"
        )
        count = rows[0]["c"] if rows else 0
        logger.info("[DRY RUN] Would create %d Entity-[REFERS_TO]->Company links", count)
        return count

    result = await graph.run_cypher(
        "MATCH (e:Entity), (c:Company) "
        "WHERE e.name = c.name AND NOT (e)-[:REFERS_TO]->(c) "
        "MERGE (e)-[:REFERS_TO]->(c) "
        "RETURN count(*) AS created"
    )
    created = result[0].get("created", 0) if result else 0
    logger.info("Entity->Company: created %d REFERS_TO relationships", created)
    return created


async def strategy_knowledge_to_cluster(graph: KnowledgeGraph, dry_run: bool) -> int:
    """Link Knowledge nodes to Cluster nodes via cluster_id."""
    if dry_run:
        rows = await graph.run_cypher(
            "MATCH (k:Knowledge), (cl:Cluster) "
            "WHERE k.cluster_id IS NOT NULL "
            "AND k.cluster_id = cl.cluster_id "
            "AND NOT (k)-[:IN_CLUSTER]->(cl) "
            "RETURN count(*) AS c"
        )
        count = rows[0]["c"] if rows else 0
        logger.info("[DRY RUN] Would create %d Knowledge-[IN_CLUSTER]->Cluster links", count)
        return count

    result = await graph.run_cypher(
        "MATCH (k:Knowledge), (cl:Cluster) "
        "WHERE k.cluster_id IS NOT NULL "
        "AND k.cluster_id = cl.cluster_id "
        "AND NOT (k)-[:IN_CLUSTER]->(cl) "
        "MERGE (k)-[:IN_CLUSTER]->(cl) "
        "RETURN count(*) AS created"
    )
    created = result[0].get("created", 0) if result else 0
    logger.info("Knowledge->Cluster: created %d IN_CLUSTER relationships", created)
    return created


ALL_STRATEGIES = {
    "knowledge_machine": ("Link Knowledge->Machine via entity field", strategy_knowledge_to_machine),
    "knowledge_source": ("Link Knowledge->Source via source_file", strategy_knowledge_to_source),
    "knowledge_cluster": ("Link Knowledge->Cluster via cluster_id", strategy_knowledge_to_cluster),
    "entity_machine": ("Link Entity->Machine by name match", strategy_entity_to_machine),
    "entity_company": ("Link Entity->Company by name match", strategy_entity_to_company),
    "domain": ("Link Person->Company by email domain", strategy_domain_matching),
    "quotes": ("Infer INTERESTED_IN from quote chains", strategy_quotes_to_interested),
    "manufactures": ("Add Machinecraft MANUFACTURES all machines", strategy_manufactures),
    "cleanup": ("Delete label-less orphan nodes", strategy_cleanup_orphans),
    "orphans": ("Connect labeled orphan nodes", strategy_labeled_orphans),
    "cooccurrence": ("Link Person-Company by role field", strategy_person_company_cooccurrence),
}


async def enrich(
    strategies: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    graph = KnowledgeGraph()

    try:
        before = await count_stats(graph)
        logger.info(
            "Before: %d nodes, %d relationships, %d orphans (ratio: %.2f)",
            before["nodes"], before["relationships"], before["orphans"],
            before["relationships"] / max(before["nodes"], 1),
        )

        active = strategies or list(ALL_STRATEGIES.keys())
        total_created = 0

        for name in active:
            if name not in ALL_STRATEGIES:
                logger.warning("Unknown strategy: %s (skipping)", name)
                continue
            desc, fn = ALL_STRATEGIES[name]
            logger.info("Running strategy: %s — %s", name, desc)
            count = await fn(graph, dry_run)
            total_created += count

        after = await count_stats(graph)
        logger.info(
            "After: %d nodes, %d relationships, %d orphans (ratio: %.2f)",
            after["nodes"], after["relationships"], after["orphans"],
            after["relationships"] / max(after["nodes"], 1),
        )
        logger.info(
            "Delta: %+d nodes, %+d relationships, %+d orphans",
            after["nodes"] - before["nodes"],
            after["relationships"] - before["relationships"],
            after["orphans"] - before["orphans"],
        )
    finally:
        await graph.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich Neo4j graph by connecting orphan nodes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--strategy", type=str, default=None,
        help=f"Comma-separated strategies to run. Available: {', '.join(ALL_STRATEGIES.keys())}",
    )
    args = parser.parse_args()

    strategies = args.strategy.split(",") if args.strategy else None
    asyncio.run(enrich(strategies=strategies, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
