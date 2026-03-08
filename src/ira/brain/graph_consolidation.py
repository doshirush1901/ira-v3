"""Usage-based knowledge graph tuning during dream mode.

Analyzes retrieval logs to find which knowledge chunks are frequently
accessed together, then strengthens the Neo4j relationships between
co-accessed entities and decays stale nodes that haven't been touched
in a configurable window.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.brain.knowledge_graph import KnowledgeGraph
from ira.exceptions import DatabaseError, IraError

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("data/brain/retrieval_log.jsonl")


class GraphConsolidation:
    """Tune the knowledge graph based on real retrieval usage patterns."""

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        retrieval_log_path: Path = _DEFAULT_LOG_PATH,
    ) -> None:
        self._graph = knowledge_graph
        self._log_path = retrieval_log_path

    # ── logging ───────────────────────────────────────────────────────────

    async def log_retrieval(
        self,
        query: str,
        chunks_retrieved: list[str],
        source_types: list[str],
    ) -> None:
        """Append a retrieval event to the JSONL log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "chunks": chunks_retrieved,
            "source_types": source_types,
        }

        def _append() -> None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

        try:
            await asyncio.to_thread(_append)
        except OSError:
            logger.exception("Failed to write retrieval log entry")

    # ── analysis ──────────────────────────────────────────────────────────

    async def build_co_access_matrix(self) -> dict:
        """Analyze the retrieval log to find chunks frequently retrieved together.

        Returns a dict mapping ``(chunk_a, chunk_b)`` tuple-keys (serialized
        as ``"chunk_a|||chunk_b"``) to co-occurrence counts.
        """
        if not self._log_path.exists():
            return {}

        def _read_and_parse() -> dict[str, int]:
            co: dict[str, int] = defaultdict(int)
            with self._log_path.open(encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    chunks = entry.get("chunks", [])
                    for i, a in enumerate(chunks):
                        for b in chunks[i + 1 :]:
                            key = "|||".join(sorted([a, b]))
                            co[key] += 1
            return dict(co)

        try:
            co_access = await asyncio.to_thread(_read_and_parse)
        except OSError:
            logger.exception("Failed to read retrieval log")
            co_access = {}

        logger.info("Co-access matrix: %d pairs analyzed", len(co_access))
        return co_access

    async def tune_relationships(self, co_access: dict) -> None:
        """Strengthen relationships between co-accessed entities in Neo4j.

        Pairs accessed together >= 3 times get a ``CO_RELEVANT`` edge with
        a ``strength`` property.  Only links *existing* labeled nodes — never
        creates label-less orphans.
        """
        strengthened = 0
        for pair_key, count in co_access.items():
            if count < 3:
                continue
            parts = pair_key.split("|||")
            if len(parts) != 2:
                continue
            entity_a, entity_b = parts

            try:
                result = await self._graph._run_cypher_write(
                    """
                    MATCH (a) WHERE (a.name = $a OR a.email = $a OR a.model = $a
                                     OR a.source = $a)
                                    AND size(labels(a)) > 0
                    MATCH (b) WHERE (b.name = $b OR b.email = $b OR b.model = $b
                                     OR b.source = $b)
                                    AND size(labels(b)) > 0
                    WITH a, b LIMIT 1
                    MERGE (a)-[r:CO_RELEVANT]-(b)
                    SET r.strength = COALESCE(r.strength, 0) + $boost,
                        r.updated_at = $now
                    RETURN count(r) AS created
                    """,
                    params={
                        "a": entity_a,
                        "b": entity_b,
                        "boost": min(count, 10),
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                if result and result[0].get("created", 0) > 0:
                    strengthened += 1
            except (DatabaseError, Exception):
                logger.debug("Failed to strengthen edge %s <-> %s", entity_a, entity_b)

        logger.info("Tuned %d co-access relationships", strengthened)

    async def decay_stale_nodes(self, days_threshold: int = 30) -> None:
        """Mark nodes not accessed in *days_threshold* days as stale.

        Sets a ``stale`` property to ``true`` and records the decay timestamp.
        """
        cutoff = datetime.now(timezone.utc)

        def _read_active_entities() -> set[str]:
            active: set[str] = set()
            if not self._log_path.exists():
                return active
            with self._log_path.open(encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        entry = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = entry.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        continue
                    age_days = (cutoff - ts).days
                    if age_days <= days_threshold:
                        for chunk in entry.get("chunks", []):
                            active.add(chunk)
            return active

        try:
            accessed_entities = await asyncio.to_thread(_read_active_entities)
        except OSError:
            logger.exception("Failed to read retrieval log for decay analysis")
            accessed_entities = set()

        try:
            result = await self._graph._run_cypher_write(
                """
                MATCH (n)
                WHERE n.name IS NOT NULL AND size(labels(n)) > 0
                      AND NOT n.name IN $active
                      AND NOT COALESCE(n.source, '') IN $active
                SET n.stale = true, n.stale_since = $now
                RETURN count(n) AS decayed
                """,
                params={
                    "active": list(accessed_entities),
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
            decayed = result[0].get("decayed", 0) if result else 0
            logger.info("Marked %d nodes as stale (threshold=%d days)", decayed, days_threshold)
        except (DatabaseError, Exception):
            logger.exception("Failed to decay stale nodes")

    # ── full pipeline ─────────────────────────────────────────────────────

    async def run_consolidation(self) -> dict:
        """Execute the full consolidation pipeline and return stats."""
        stats: dict[str, Any] = {}

        try:
            co_access = await self.build_co_access_matrix()
            stats["co_access_pairs"] = len(co_access)

            await self.tune_relationships(co_access)
            stats["tuning"] = "completed"

            await self.decay_stale_nodes()
            stats["decay"] = "completed"

            stats["status"] = "success"
        except (IraError, Exception):
            logger.exception("Graph consolidation failed")
            stats["status"] = "error"

        logger.info("Graph consolidation complete: %s", stats)
        return stats
