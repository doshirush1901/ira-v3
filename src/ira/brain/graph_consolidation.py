"""Usage-based knowledge graph tuning during dream mode.

Analyzes retrieval logs to find which knowledge chunks are frequently
accessed together, then strengthens the Neo4j relationships between
co-accessed entities and decays stale nodes that haven't been touched
in a configurable window.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ira.brain.knowledge_graph import KnowledgeGraph

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

    def log_retrieval(
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
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
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

        co_access: dict[str, int] = defaultdict(int)
        try:
            with self._log_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    chunks = entry.get("chunks", [])
                    for i, a in enumerate(chunks):
                        for b in chunks[i + 1 :]:
                            key = "|||".join(sorted([a, b]))
                            co_access[key] += 1
        except OSError:
            logger.exception("Failed to read retrieval log")

        logger.info("Co-access matrix: %d pairs analyzed", len(co_access))
        return dict(co_access)

    async def tune_relationships(self, co_access: dict) -> None:
        """Strengthen relationships between co-accessed entities in Neo4j.

        Pairs accessed together >= 3 times get a ``CO_RELEVANT`` edge with
        a ``strength`` property.  Pairs that appear in the graph but have
        zero co-access get their strength decremented.
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
                await self._graph.run_cypher(
                    """
                    MERGE (a {name: $a})
                    MERGE (b {name: $b})
                    MERGE (a)-[r:CO_RELEVANT]-(b)
                    SET r.strength = COALESCE(r.strength, 0) + $boost,
                        r.updated_at = $now
                    """,
                    params={
                        "a": entity_a,
                        "b": entity_b,
                        "boost": min(count, 10),
                        "now": datetime.now(timezone.utc).isoformat(),
                    },
                )
                strengthened += 1
            except Exception:
                logger.debug("Failed to strengthen edge %s <-> %s", entity_a, entity_b)

        logger.info("Tuned %d co-access relationships", strengthened)

    async def decay_stale_nodes(self, days_threshold: int = 30) -> None:
        """Mark nodes not accessed in *days_threshold* days as stale.

        Sets a ``stale`` property to ``true`` and records the decay timestamp.
        """
        cutoff = datetime.now(timezone.utc)
        accessed_entities: set[str] = set()

        if self._log_path.exists():
            try:
                with self._log_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
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
                                accessed_entities.add(chunk)
            except OSError:
                logger.exception("Failed to read retrieval log for decay analysis")

        try:
            result = await self._graph.run_cypher(
                """
                MATCH (n)
                WHERE n.name IS NOT NULL AND NOT n.name IN $active
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
        except Exception:
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
        except Exception:
            logger.exception("Graph consolidation failed")
            stats["status"] = "error"

        logger.info("Graph consolidation complete: %s", stats)
        return stats
