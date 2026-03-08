"""Persistent semantic memory backed by the Mem0 REST API."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

from ira.config import MemoryConfig, get_settings
from ira.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class LongTermMemory:
    def __init__(self, config: MemoryConfig | None = None) -> None:
        cfg = config or get_settings().memory
        self._api_key = cfg.api_key.get_secret_value()
        self._base_url = "https://api.mem0.ai"
        self._headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
        }

    async def store(
        self,
        content: str,
        user_id: str = "global",
        metadata: dict | None = None,
    ) -> list[dict]:
        if not self._api_key:
            logger.warning("Mem0 API key not configured; skipping memory store")
            return []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/v1/memories/",
                    headers=self._headers,
                    json={
                        "messages": [{"role": "user", "content": content}],
                        "user_id": user_id,
                        "metadata": metadata or {},
                        "infer": True,
                    },
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as e:
            logger.exception("Mem0 store failed: %s", e)
            return []

    async def search(
        self,
        query: str,
        user_id: str = "global",
        limit: int = 5,
    ) -> list[dict]:
        if not self._api_key:
            return []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/v1/memories/search/",
                    headers=self._headers,
                    json={
                        "query": query,
                        "user_id": user_id,
                        "top_k": limit,
                    },
                )
                resp.raise_for_status()
                raw = resp.json()
                memories = raw.get("results", raw) if isinstance(raw, dict) else raw
                results = []
                now = datetime.now(timezone.utc)
                for m in memories:
                    result = {
                        "id": m.get("id", ""),
                        "memory": m.get("memory", ""),
                        "score": m.get("score", 0.5),
                        "metadata": m.get("metadata", {}),
                        "created_at": m.get("created_at", ""),
                    }
                    created_at = result["created_at"]
                    if created_at:
                        try:
                            if isinstance(created_at, str):
                                dt = datetime.fromisoformat(
                                    created_at.replace("Z", "+00:00")
                                )
                            else:
                                dt = created_at
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            delta = now - dt
                            days_old = max(0, delta.days)
                            result["score"] *= self.apply_decay(days_old)
                        except (ValueError, TypeError):
                            pass
                    results.append(result)
                results.sort(key=lambda r: r["score"], reverse=True)
                return results
        except httpx.HTTPError as e:
            logger.exception("Mem0 search failed: %s", e)
            return []

    async def store_correction(
        self,
        original: str,
        corrected: str,
        context: str,
    ) -> list[dict]:
        content = (
            f"CORRECTION: Originally '{original}' was stated, but the correct "
            f"information is '{corrected}'. Context: {context}"
        )
        return await self.store(
            content,
            user_id="global",
            metadata={
                "type": "correction",
                "priority": "high",
                "original": original,
                "corrected": corrected,
            },
        )

    async def store_preference(
        self,
        user_id: str,
        preference_type: str,
        value: str,
    ) -> list[dict]:
        content = f"User preference: {preference_type} = {value}"
        return await self.store(
            content,
            user_id=user_id,
            metadata={
                "type": "preference",
                "preference_type": preference_type,
                "value": value,
            },
        )

    async def get_user_preferences(self, user_id: str) -> dict:
        try:
            results = await self.search(
                "user preferences and settings",
                user_id=user_id,
                limit=20,
            )
            filtered = [
                m
                for m in results
                if m.get("metadata", {}).get("type") == "preference"
            ]
            return {
                m["metadata"]["preference_type"]: m["metadata"]["value"]
                for m in filtered
                if "preference_type" in m.get("metadata", {})
            }
        except (DatabaseError, Exception) as e:
            logger.exception("Mem0 get_user_preferences failed: %s", e)
            return {}

    async def store_fact(
        self,
        fact: str,
        source: str,
        confidence: float,
    ) -> list[dict]:
        return await self.store(
            fact,
            user_id="global",
            metadata={
                "type": "fact",
                "source": source,
                "confidence": confidence,
                "verified": confidence >= 0.8,
            },
        )

    def apply_decay(self, days_old: int, access_count: int = 0) -> float:
        base_stability = 30.0
        stability = base_stability * (1 + math.log(1 + access_count))
        retention = math.exp(-days_old / stability)
        return max(0.0, min(1.0, retention))
