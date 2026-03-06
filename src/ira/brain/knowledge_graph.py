"""Neo4j knowledge-graph manager for Ira.

Stores and queries structured entity relationships — companies, people,
machines, and quotes — as a property graph.  Every write uses ``MERGE`` to
guarantee idempotent upserts.  An LLM-powered extraction method can
populate the graph from unstructured text.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from neo4j import AsyncGraphDatabase

from ira.config import LLMConfig, Neo4jConfig, get_settings
from ira.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = load_prompt("extract_entities")


class KnowledgeGraph:
    """Async wrapper around the Neo4j graph database."""

    def __init__(self, config: Neo4jConfig | None = None, llm_config: LLMConfig | None = None) -> None:
        cfg = config or get_settings().neo4j
        llm = llm_config or get_settings().llm
        self._driver = AsyncGraphDatabase.driver(
            cfg.uri,
            auth=(cfg.user, cfg.password.get_secret_value()),
        )
        self._openai_key = llm.openai_api_key.get_secret_value()
        self._openai_model = llm.openai_model

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
        async with self._driver.session() as session:
            await session.execute_write(
                self._merge_company, name, region, industry, website
            )

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
        """Return a subgraph of nodes within *max_hops* of the named entity."""
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

    async def run_cypher(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute an arbitrary Cypher query and return the result rows."""
        return await self._read(query, **(params or {}))

    # ── LLM entity extraction ────────────────────────────────────────────

    async def extract_entities_from_text(self, text: str) -> dict[str, Any]:
        """Use OpenAI to pull structured entities out of free text.

        Returns a dict with keys ``companies``, ``people``, ``machines``,
        ``relationships`` — each a list of dicts.
        """
        empty: dict[str, Any] = {
            "companies": [],
            "people": [],
            "machines": [],
            "relationships": [],
        }

        if not self._openai_key:
            logger.warning("No OpenAI API key configured; skipping entity extraction")
            return empty

        headers = {
            "Authorization": f"Bearer {self._openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._openai_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": text[:12_000]},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            logger.exception("Entity extraction failed")
            return empty

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
