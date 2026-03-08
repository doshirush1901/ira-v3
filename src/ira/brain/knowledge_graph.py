"""Neo4j knowledge-graph manager for Ira.

Stores and queries structured entity relationships — companies, people,
machines, and quotes — as a property graph.  Every write uses ``MERGE`` to
guarantee idempotent upserts.  An LLM-powered extraction method can
populate the graph from unstructured text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langfuse.decorators import observe
from neo4j import AsyncGraphDatabase

from ira.config import Neo4jConfig, get_settings
from ira.exceptions import DatabaseError, IraError
from ira.prompt_loader import load_prompt
from ira.schemas.llm_outputs import GraphEntities
from ira.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_VALID_LABEL = re.compile(r"^[A-Z][A-Za-z_]{0,30}$")
_VALID_PROP_KEY = re.compile(r"^[a-z][a-z0-9_]{0,50}$")

_ENTITY_SUFFIXES = re.compile(
    r",?\s*\b(Inc\.?|LLC|Ltd\.?|Corp\.?|Co\.?|PLC|GmbH|SA|AG|NV|BV)\s*$",
    re.IGNORECASE,
)

_EXTRACTION_SYSTEM_PROMPT = load_prompt("extract_entities")


def normalize_entity_name(name: str) -> str:
    """Normalize an entity name for consistent graph storage."""
    name = name.strip()
    name = _ENTITY_SUFFIXES.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name


class KnowledgeGraph:
    """Async wrapper around the Neo4j graph database."""

    def __init__(
        self,
        config: Neo4jConfig | None = None,
        event_bus: Any | None = None,
    ) -> None:
        cfg = config or get_settings().neo4j
        app_cfg = get_settings().app
        self._driver = AsyncGraphDatabase.driver(
            cfg.uri,
            auth=(cfg.user, cfg.password.get_secret_value()),
            max_connection_pool_size=app_cfg.neo4j_max_pool_size,
            connection_acquisition_timeout=60.0,
        )
        self._llm = get_llm_client()
        self._event_bus = event_bus

    def set_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    async def _emit(self, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        from ira.systems.data_event_bus import DataEvent, EventType, SourceStore
        try:
            await self._event_bus.emit(DataEvent(
                event_type=EventType.ENTITY_ADDED,
                entity_type=entity_type,
                entity_id=entity_id,
                payload={**payload, "entity_type": entity_type},
                source_store=SourceStore.NEO4J,
            ))
        except (IraError, Exception):
            logger.debug("Neo4j event emission failed", exc_info=True)

    # ── schema / indexes ─────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        """Create uniqueness constraints and indexes for core node types."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.email IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Machine) REQUIRE m.model IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (q:Quote) REQUIRE q.quote_id IS UNIQUE",
        ]
        async with self._driver.session() as session:
            for stmt in constraints:
                await session.run(stmt)
        logger.info("Neo4j indexes and constraints ensured")

    # ── entity creation ──────────────────────────────────────────────────

    async def add_company(
        self,
        name: str,
        region: str = "",
        industry: str = "",
        website: str = "",
    ) -> None:
        name = normalize_entity_name(name)
        async with self._driver.session() as session:
            await session.execute_write(
                self._merge_company, name, region, industry, website
            )
        await self._emit("company", name, {
            "name": name, "region": region, "industry": industry, "website": website,
        })

    @staticmethod
    async def _merge_company(
        tx: Any, name: str, region: str, industry: str, website: str
    ) -> None:
        await tx.run(
            """
            MERGE (c:Company {name: $name})
            SET c.region = $region, c.industry = $industry, c.website = $website
            """,
            name=name, region=region, industry=industry, website=website,
        )

    async def add_person(
        self,
        name: str,
        email: str,
        company_name: str = "",
        role: str = "",
    ) -> None:
        async with self._driver.session() as session:
            await session.execute_write(
                self._merge_person, name, email, company_name, role
            )
        await self._emit("person", email, {
            "name": name, "email": email, "company": company_name, "role": role,
        })

    @staticmethod
    async def _merge_person(
        tx: Any, name: str, email: str, company_name: str, role: str
    ) -> None:
        await tx.run(
            """
            MERGE (p:Person {email: $email})
            SET p.name = $name, p.role = $role
            """,
            name=name, email=email, role=role,
        )
        if company_name:
            await tx.run(
                """
                MERGE (p:Person {email: $email})
                MERGE (c:Company {name: $company})
                MERGE (p)-[r:WORKS_AT]->(c)
                SET r.role = $role
                """,
                email=email, company=company_name, role=role,
            )

    async def add_machine(
        self,
        model: str,
        category: str = "",
        description: str = "",
    ) -> None:
        async with self._driver.session() as session:
            await session.execute_write(self._merge_machine, model, category, description)
        await self._emit("machine", model, {
            "model": model, "category": category, "description": description,
        })

    @staticmethod
    async def _merge_machine(tx: Any, model: str, category: str, description: str) -> None:
        await tx.run(
            """
            MERGE (m:Machine {model: $model})
            SET m.category = $category, m.description = $description
            """,
            model=model, category=category, description=description,
        )

    async def add_quote(
        self,
        quote_id: str,
        company_name: str,
        machine_model: str,
        value: float,
        date: str,
        status: str = "OPEN",
    ) -> None:
        async with self._driver.session() as session:
            await session.execute_write(
                self._merge_quote, quote_id, company_name, machine_model, value, date, status
            )

    @staticmethod
    async def _merge_quote(
        tx: Any,
        quote_id: str,
        company_name: str,
        machine_model: str,
        value: float,
        date: str,
        status: str,
    ) -> None:
        await tx.run(
            """
            MERGE (q:Quote {quote_id: $qid})
            SET q.value = $value, q.date = $date, q.status = $status
            WITH q
            MERGE (c:Company {name: $company})
            MERGE (q)-[:QUOTED_TO]->(c)
            WITH q
            MERGE (m:Machine {model: $machine})
            MERGE (q)-[:QUOTES_MACHINE]->(m)
            """,
            qid=quote_id, company=company_name, machine=machine_model,
            value=value, date=date, status=status,
        )

    # ── generic relationship creation ────────────────────────────────────

    # SECURITY: _KEY_FIELDS acts as the allowlist for node labels.
    # Only these four labels may be used in dynamic Cypher queries.
    # from_type / to_type are validated against this dict before
    # interpolation — never add entries without reviewing the Cypher
    # injection implications.
    _KEY_FIELDS: dict[str, str] = {
        "Company": "name",
        "Person": "email",
        "Machine": "model",
        "Quote": "quote_id",
    }

    _ALLOWED_REL_TYPES = frozenset({
        "WORKS_AT", "INTERESTED_IN", "QUOTED_FOR", "SUPPLIES",
        "MANUFACTURES", "COMPETES_WITH", "CONTACTED_BY", "REFERRED_BY",
        "QUOTED_TO", "QUOTES_MACHINE", "CO_RELEVANT",
        "DESCRIBES", "FROM_SOURCE", "REFERS_TO", "IN_CLUSTER",
    })

    async def add_relationship(
        self,
        from_type: str,
        from_key: str,
        rel_type: str,
        to_type: str,
        to_key: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Create a relationship between two nodes, merging idempotently.

        ``from_type`` / ``to_type`` must be one of Company, Person, Machine,
        Quote.  ``rel_type`` is validated against ``_ALLOWED_REL_TYPES``.
        Returns True if the relationship was written, False if skipped.
        """
        if not from_key or not to_key:
            return False
        if rel_type not in self._ALLOWED_REL_TYPES:
            logger.warning("Ignoring unknown relationship type: %s", rel_type)
            return False

        from_field = self._KEY_FIELDS.get(from_type)
        to_field = self._KEY_FIELDS.get(to_type)
        if not from_field or not to_field:
            logger.warning(
                "Unknown node type(s): %s, %s", from_type, to_type,
            )
            return False

        if not _VALID_LABEL.match(from_type) or not _VALID_LABEL.match(to_type):
            logger.warning("Invalid node label format: %s, %s", from_type, to_type)
            return False
        if not _VALID_LABEL.match(rel_type):
            logger.warning("Invalid relationship type format: %s", rel_type)
            return False

        props = properties or {}
        props = {k: v for k, v in props.items() if _VALID_PROP_KEY.match(k)}
        set_clause = "SET r += $props" if props else ""

        query = (
            f"MERGE (a:{from_type} {{{from_field}: $from_key}}) "
            f"MERGE (b:{to_type} {{{to_field}: $to_key}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"{set_clause}"
        )
        params: dict[str, Any] = {"from_key": from_key, "to_key": to_key, "props": props}

        try:
            async with self._driver.session() as session:
                await session.run(query, params)
            logger.debug(
                "Relationship created: (%s:%s)-[%s]->(%s:%s)",
                from_type, from_key, rel_type, to_type, to_key,
            )
            return True
        except (DatabaseError, Exception):
            logger.exception(
                "Failed to create relationship (%s:%s)-[%s]->(%s:%s)",
                from_type, from_key, rel_type, to_type, to_key,
            )
            return False

    # ── relationship helpers ─────────────────────────────────────────────

    async def link_person_to_company(self, person_email: str, company_name: str, role: str = "") -> None:
        async with self._driver.session() as session:
            await session.execute_write(
                self._link_person_company, person_email, company_name, role
            )

    @staticmethod
    async def _link_person_company(tx: Any, email: str, company: str, role: str) -> None:
        await tx.run(
            """
            MERGE (p:Person {email: $email})
            MERGE (c:Company {name: $company})
            MERGE (p)-[r:WORKS_AT]->(c)
            SET r.role = $role
            """,
            email=email, company=company, role=role,
        )

    async def link_quote_to_company(self, quote_id: str, company_name: str) -> None:
        async with self._driver.session() as session:
            await session.execute_write(self._link_quote_company, quote_id, company_name)

    @staticmethod
    async def _link_quote_company(tx: Any, quote_id: str, company: str) -> None:
        await tx.run(
            """
            MERGE (q:Quote {quote_id: $qid})
            MERGE (c:Company {name: $company})
            MERGE (q)-[:QUOTED_TO]->(c)
            """,
            qid=quote_id, company=company,
        )

    async def link_quote_to_machine(self, quote_id: str, machine_model: str) -> None:
        async with self._driver.session() as session:
            await session.execute_write(self._link_quote_machine, quote_id, machine_model)

    @staticmethod
    async def _link_quote_machine(tx: Any, quote_id: str, model: str) -> None:
        await tx.run(
            """
            MERGE (q:Quote {quote_id: $qid})
            MERGE (m:Machine {model: $model})
            MERGE (q)-[:QUOTES_MACHINE]->(m)
            """,
            qid=quote_id, model=model,
        )

    # ── queries ──────────────────────────────────────────────────────────

    async def find_company_contacts(self, company_name: str) -> list[dict[str, Any]]:
        """Return all Person nodes linked to a company."""
        return await self._read(
            """
            MATCH (p:Person)-[:WORKS_AT]->(c:Company {name: $name})
            RETURN p.name AS name, p.email AS email, p.role AS role
            """,
            name=company_name,
        )

    async def find_company_quotes(self, company_name: str) -> list[dict[str, Any]]:
        """Return all Quote nodes linked to a company."""
        return await self._read(
            """
            MATCH (q:Quote)-[:QUOTED_TO]->(c:Company {name: $name})
            OPTIONAL MATCH (q)-[:QUOTES_MACHINE]->(m:Machine)
            RETURN q.quote_id AS quote_id, q.value AS value, q.date AS date,
                   q.status AS status, m.model AS machine
            """,
            name=company_name,
        )

    async def find_machine_customers(self, machine_model: str) -> list[dict[str, Any]]:
        """Return companies that have received quotes for a machine model."""
        return await self._read(
            """
            MATCH (q:Quote)-[:QUOTES_MACHINE]->(m:Machine {model: $model})
            MATCH (q)-[:QUOTED_TO]->(c:Company)
            RETURN DISTINCT c.name AS company, c.region AS region,
                   c.industry AS industry
            """,
            model=machine_model,
        )

    async def find_related_entities(
        self,
        entity_name: str,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        """Return a subgraph of nodes within *max_hops* of the named entity.

        Tries APOC ``subgraphAll`` first for efficiency; falls back to a
        standard variable-length MATCH if APOC is not installed.
        """
        try:
            records = await self._read(
                f"""
                MATCH (start)
                WHERE start.name = $name OR start.email = $name
                      OR start.model = $name OR start.quote_id = $name
                CALL apoc.path.subgraphAll(start, {{maxLevel: {max_hops}}})
                YIELD nodes, relationships
                RETURN nodes, relationships
                """,
                name=entity_name,
            )
            if not records:
                return {"nodes": [], "relationships": []}
            row = records[0]
            return {
                "nodes": row.get("nodes", []),
                "relationships": row.get("relationships", []),
            }
        except (DatabaseError, Exception):
            logger.debug("APOC not available, falling back to MATCH path query")

        records = await self._read(
            f"""
            MATCH (start)
            WHERE start.name = $name OR start.email = $name
                  OR start.model = $name OR start.quote_id = $name
            OPTIONAL MATCH path = (start)-[r*1..{max_hops}]-(related)
            WITH start,
                 collect(DISTINCT related) AS related_nodes,
                 [rel IN collect(DISTINCT r) | head(rel)] AS flat_rels
            UNWIND (CASE WHEN size(flat_rels) = 0 THEN [null] ELSE flat_rels END) AS rel
            WITH start, related_nodes,
                 collect(CASE WHEN rel IS NOT NULL THEN
                   {{type: type(rel), from: startNode(rel).name, to: endNode(rel).name}}
                 END) AS rels
            RETURN [start] + related_nodes AS nodes,
                   [r IN rels WHERE r IS NOT NULL] AS relationships
            """,
            name=entity_name,
        )
        if not records:
            return {"nodes": [], "relationships": []}
        return {
            "nodes": records[0].get("nodes", []),
            "relationships": records[0].get("relationships", []),
        }

    _WRITE_KEYWORDS = frozenset({"CREATE", "DELETE", "DETACH", "SET", "REMOVE", "DROP"})

    async def run_cypher(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a **read-only** Cypher query and return the result rows.

        Write operations (CREATE, DELETE, SET, etc.) are rejected.  For
        internal write operations use :meth:`_run_cypher_write` instead.
        """
        tokens = set(query.upper().split())
        if tokens & self._WRITE_KEYWORDS:
            raise ValueError(
                f"Write operations not allowed via run_cypher: "
                f"{sorted(tokens & self._WRITE_KEYWORDS)}"
            )
        if any(c in query for c in (";", "//", "/*")):
            raise ValueError("Query contains disallowed characters")
        return await self._read(query, **(params or {}))

    async def _run_cypher_write(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher write query.  Internal use only."""
        async with self._driver.session() as session:
            result = await session.run(query, **(params or {}))
            return [dict(record) async for record in result]

    # ── LLM entity extraction ────────────────────────────────────────────

    @observe()
    async def extract_entities_from_text(self, text: str) -> dict[str, Any]:
        """Extract entities from free text, preferring GraphRAG when available.

        Tries the Neo4j GraphRAG schema-bound extractor first for better
        entity resolution and consistency.  Falls back to the legacy
        LLM prompt approach if GraphRAG is unavailable or fails.

        Returns a dict with keys ``companies``, ``people``, ``machines``,
        ``relationships`` — each a list of dicts.
        """
        empty: dict[str, Any] = {
            "companies": [],
            "people": [],
            "machines": [],
            "relationships": [],
        }

        try:
            return await self._extract_entities_graphrag(text)
        except Exception:
            logger.debug("GraphRAG extraction unavailable, using legacy LLM", exc_info=True)

        try:
            result = await self._llm.generate_structured(
                _EXTRACTION_SYSTEM_PROMPT,
                text[:12_000],
                GraphEntities,
                name="knowledge_graph.extract",
            )
            return result.model_dump()
        except Exception:
            logger.exception("Entity extraction failed for source text (%d chars)", len(text))
            return empty

    async def _extract_entities_graphrag(self, text: str) -> dict[str, Any]:
        """Schema-bound entity extraction using neo4j-graphrag.

        Uses Pydantic-defined schemas matching Ira's existing Neo4j node
        labels and relationship types for consistent, deduplicated output
        with built-in entity resolution.
        """
        from neo4j_graphrag.experimental.components.entity_relation_extractor import (
            LLMEntityRelationExtractor,
        )
        from neo4j_graphrag.experimental.components.schema import (
            SchemaBuilder,
            SchemaEntity,
            SchemaRelation,
        )
        from neo4j_graphrag.experimental.components.types import (
            TextChunk,
            TextChunks,
        )
        from neo4j_graphrag.llm import OpenAILLM

        schema_builder = SchemaBuilder()
        schema_builder.add_entity(
            SchemaEntity(label="Company", properties=["name", "region", "industry", "website"])
        )
        schema_builder.add_entity(
            SchemaEntity(label="Person", properties=["name", "email", "role"])
        )
        schema_builder.add_entity(
            SchemaEntity(label="Machine", properties=["model", "category", "description"])
        )
        schema_builder.add_entity(
            SchemaEntity(label="Quote", properties=["quote_id", "value", "status"])
        )

        for rel_label, source, target in [
            ("WORKS_AT", "Person", "Company"),
            ("INTERESTED_IN", "Company", "Machine"),
            ("QUOTED_TO", "Quote", "Company"),
            ("QUOTES_MACHINE", "Quote", "Machine"),
            ("SUPPLIES", "Company", "Company"),
            ("MANUFACTURES", "Company", "Machine"),
            ("COMPETES_WITH", "Company", "Company"),
            ("CONTACTED_BY", "Company", "Person"),
            ("REFERRED_BY", "Person", "Person"),
        ]:
            schema_builder.add_relation(
                SchemaRelation(label=rel_label, source_type=source, target_type=target)
            )

        schema = schema_builder.build()

        from ira.config import get_settings
        cfg = get_settings()
        openai_key = cfg.llm.openai_api_key.get_secret_value()
        llm = OpenAILLM(
            model_name=cfg.llm.openai_model,
            api_key=openai_key,
        )

        extractor = LLMEntityRelationExtractor(
            llm=llm, create_lexical_graph=False,
        )
        chunks = TextChunks(chunks=[TextChunk(text=text[:12_000])])
        graph_result = await extractor.run(chunks=chunks, schema=schema)

        _KEY_FIELDS = {
            "Company": "name",
            "Person": "email",
            "Machine": "model",
            "Quote": "quote_id",
        }

        companies: list[dict[str, Any]] = []
        people: list[dict[str, Any]] = []
        machines: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        node_by_id: dict[str, Any] = {}
        for node in graph_result.nodes:
            node_by_id[node.id] = node

        for node in graph_result.nodes:
            props = node.properties or {}
            label = node.label

            if label == "Company":
                companies.append({
                    "name": normalize_entity_name(props.get("name", "")),
                    "region": props.get("region", ""),
                    "industry": props.get("industry", ""),
                    "website": props.get("website", ""),
                })
            elif label == "Person":
                people.append({
                    "name": props.get("name", ""),
                    "email": props.get("email", ""),
                    "company": "",
                    "role": props.get("role", ""),
                })
            elif label == "Machine":
                machines.append({
                    "model": props.get("model", ""),
                    "category": props.get("category", ""),
                    "description": props.get("description", ""),
                })

        for rel in graph_result.relationships:
            start_node = node_by_id.get(rel.start_node_id)
            end_node = node_by_id.get(rel.end_node_id)

            def _node_key(n: Any) -> str:
                if n is None:
                    return ""
                props = n.properties or {}
                key_field = _KEY_FIELDS.get(n.label, "name")
                raw = props.get(key_field, props.get("name", ""))
                if n.label == "Company":
                    return normalize_entity_name(raw)
                return raw

            relationships.append({
                "from_type": start_node.label if start_node else "",
                "from_key": _node_key(start_node),
                "rel": rel.type,
                "to_type": end_node.label if end_node else "",
                "to_key": _node_key(end_node),
            })

        return {
            "companies": companies,
            "people": people,
            "machines": machines,
            "relationships": relationships,
        }

    # ── bulk enrichment ────────────────────────────────────────────────

    async def enrich_interested_in_from_quotes(self) -> int:
        """Infer Company-[INTERESTED_IN]->Machine from existing quote chains."""
        result = await self._read(
            """
            MATCH (q:Quote)-[:QUOTED_TO]->(c:Company),
                  (q)-[:QUOTES_MACHINE]->(m:Machine)
            WHERE NOT (c)-[:INTERESTED_IN]->(m)
            MERGE (c)-[:INTERESTED_IN]->(m)
            RETURN count(*) AS created
            """
        )
        created = result[0].get("created", 0) if result else 0
        logger.info("Enrichment: created %d INTERESTED_IN from quotes", created)
        return created

    async def enrich_manufactures(self) -> int:
        """Link Machinecraft -[MANUFACTURES]-> all Machine nodes."""
        result = await self._read(
            """
            MERGE (mc:Company {name: 'Machinecraft'})
            WITH mc
            MATCH (m:Machine) WHERE NOT (mc)-[:MANUFACTURES]->(m)
            MERGE (mc)-[:MANUFACTURES]->(m)
            RETURN count(*) AS created
            """
        )
        created = result[0].get("created", 0) if result else 0
        logger.info("Enrichment: created %d MANUFACTURES relationships", created)
        return created

    async def cleanup_labelless_orphans(self) -> int:
        """Delete nodes that have no labels and no relationships."""
        result = await self._read(
            "MATCH (n) WHERE size(labels(n)) = 0 AND NOT (n)--() "
            "DELETE n RETURN count(n) AS deleted"
        )
        deleted = result[0].get("deleted", 0) if result else 0
        logger.info("Cleanup: deleted %d label-less orphan nodes", deleted)
        return deleted

    async def graph_stats(self) -> dict[str, Any]:
        """Return summary statistics about the graph."""
        rows = await self._read("MATCH (n) RETURN count(n) AS nodes")
        nodes = rows[0]["nodes"] if rows else 0
        rows = await self._read("MATCH ()-[r]->() RETURN count(r) AS rels")
        rels = rows[0]["rels"] if rows else 0
        rows = await self._read(
            "MATCH (n) WHERE NOT (n)--() RETURN count(n) AS orphans"
        )
        orphans = rows[0]["orphans"] if rows else 0

        label_rows = await self._read(
            "CALL db.labels() YIELD label "
            "CALL { WITH label MATCH (n) WHERE label IN labels(n) "
            "RETURN count(n) AS c } RETURN label, c ORDER BY c DESC"
        )
        labels = {r["label"]: r["c"] for r in label_rows}

        rel_rows = await self._read(
            "CALL db.relationshipTypes() YIELD relationshipType AS type "
            "CALL { WITH type MATCH ()-[r]->() WHERE type(r) = type "
            "RETURN count(r) AS c } RETURN type, c ORDER BY c DESC"
        )
        rel_types = {r["type"]: r["c"] for r in rel_rows}

        return {
            "nodes": nodes,
            "relationships": rels,
            "orphans": orphans,
            "ratio": round(rels / max(nodes, 1), 3),
            "labels": labels,
            "relationship_types": rel_types,
        }

    # ── safe graph-consolidation helpers ─────────────────────────────────

    async def find_active_node_names(self, since_days: int = 30) -> list[str]:
        """Return names of nodes accessed within the last *since_days*."""
        rows = await self._read(
            "MATCH (n) WHERE n.last_accessed IS NOT NULL "
            "AND n.last_accessed > datetime() - duration({days: $days}) "
            "RETURN n.name AS name",
            days=since_days,
        )
        return [r["name"] for r in rows if r.get("name")]

    async def mark_nodes_stale(self, names: list[str]) -> int:
        """Mark the given nodes as stale."""
        result = await self._run_cypher_write(
            "UNWIND $names AS name "
            "MATCH (n) WHERE n.name = name "
            "SET n._stale = true "
            "RETURN count(n) AS marked",
            params={"names": names},
        )
        return result[0].get("marked", 0) if result else 0

    async def create_co_relevant_edge(self, name_a: str, name_b: str) -> int:
        """Create a CO_RELEVANT relationship between two named nodes."""
        result = await self._run_cypher_write(
            "MATCH (a) WHERE a.name = $a "
            "MATCH (b) WHERE b.name = $b "
            "MERGE (a)-[r:CO_RELEVANT]->(b) "
            "RETURN count(r) AS created",
            params={"a": name_a, "b": name_b},
        )
        return result[0].get("created", 0) if result else 0

    # ── internals ────────────────────────────────────────────────────────

    async def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> KnowledgeGraph:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
