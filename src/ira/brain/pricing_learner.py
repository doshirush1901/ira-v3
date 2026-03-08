"""Learns prices from historical quotes and detects conflicts.

Builds a price index from the quotes database and Qdrant, tracking
per-model averages, variant multipliers, and flagging price conflicts
that exceed a configurable variance threshold.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ira.config import get_settings
from ira.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_PRICE_INDEX_PATH = Path("data/brain/price_index.json")

_EMPTY_INDEX: dict[str, Any] = {"models": {}}


class PricingLearner:
    """Accumulates pricing data and detects cross-source conflicts."""

    def __init__(
        self,
        qdrant_manager: Any | None = None,
        quotes_manager: Any | None = None,
    ) -> None:
        self._qdrant = qdrant_manager
        self._quotes = quotes_manager
        self._index: dict[str, Any] = json.loads(json.dumps(_EMPTY_INDEX))
        self._initialized = False

    async def initialize(self) -> None:
        """Load the price index from disk. Call before first use."""
        self._index = await self._load_index()
        self._initialized = True
        logger.info("PricingLearner initialised with %d models", len(self._index.get("models", {})))

    # ── persistence ───────────────────────────────────────────────────────

    async def _load_index(self) -> dict[str, Any]:
        if _PRICE_INDEX_PATH.exists():
            try:
                raw = await asyncio.to_thread(
                    _PRICE_INDEX_PATH.read_text, "utf-8",
                )
                data = json.loads(raw)
                data.setdefault("models", {})
                return data
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not load price index; starting fresh")
        return json.loads(json.dumps(_EMPTY_INDEX))

    async def _save_index(self) -> None:
        try:
            _PRICE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._index, indent=2, default=str) + "\n"
            await asyncio.to_thread(
                _PRICE_INDEX_PATH.write_text, payload, "utf-8",
            )
        except OSError:
            logger.exception("Failed to persist price index")

    # ── learning ──────────────────────────────────────────────────────────

    async def learn_from_quotes(self) -> dict[str, Any]:
        """Scan the quotes database, extract prices, and update the index."""
        if not self._initialized:
            await self.initialize()
        if self._quotes is None:
            logger.debug("No quotes manager; skipping quote-based learning")
            return {"status": "skipped", "reason": "no quotes manager"}

        learned = 0
        try:
            quotes = await self._quotes.get_all_quotes()
            for quote in quotes:
                model = quote.get("model") or quote.get("machine_model", "")
                price = quote.get("price") or quote.get("total_price")
                currency = quote.get("currency", "USD")
                if not model or not price:
                    continue
                self._record_price(
                    model=model,
                    value=float(price),
                    currency=currency,
                    source=f"quote_{quote.get('id', 'unknown')}",
                )
                learned += 1

            self._recalculate_averages()
            await self._save_index()
            logger.info("Learned %d prices from quotes", learned)
            return {"status": "ok", "prices_learned": learned}
        except (DatabaseError, Exception):
            logger.exception("Failed to learn from quotes")
            return {"status": "error"}

    async def learn_from_qdrant(self, query: str = "machine price") -> dict[str, Any]:
        """Search Qdrant for pricing data and incorporate into the index."""
        if self._qdrant is None:
            logger.debug("No Qdrant manager; skipping Qdrant-based learning")
            return {"status": "skipped", "reason": "no qdrant manager"}

        learned = 0
        try:
            results = await self._qdrant.search(query, limit=20)
            price_pattern = re.compile(
                r"([A-Z]{2,4}[-\s]?\w+).*?(?:USD|EUR|\$|€)\s?([\d,]+(?:\.\d{2})?)",
                re.IGNORECASE,
            )
            for hit in results:
                content = hit.get("content", "")
                for m in price_pattern.finditer(content):
                    model = m.group(1).strip()
                    value = float(m.group(2).replace(",", ""))
                    self._record_price(
                        model=model,
                        value=value,
                        currency="USD",
                        source=f"qdrant_{hit.get('source', 'unknown')}",
                    )
                    learned += 1

            self._recalculate_averages()
            await self._save_index()
            logger.info("Learned %d prices from Qdrant", learned)
            return {"status": "ok", "prices_learned": learned}
        except (DatabaseError, Exception):
            logger.exception("Failed to learn from Qdrant")
            return {"status": "error"}

    # ── analysis ──────────────────────────────────────────────────────────

    def detect_conflicts(self, threshold: float = 0.15) -> list[dict[str, Any]]:
        """Find models where price variance exceeds *threshold* (default 15%)."""
        conflicts: list[dict[str, Any]] = []
        for model, data in self._index["models"].items():
            prices = [p["value"] for p in data.get("prices", [])]
            if len(prices) < 2:
                continue
            avg = sum(prices) / len(prices)
            if avg == 0:
                continue
            max_dev = max(abs(p - avg) / avg for p in prices)
            if max_dev > threshold:
                conflicts.append({
                    "model": model,
                    "avg_price": round(avg, 2),
                    "max_deviation": round(max_dev, 4),
                    "price_count": len(prices),
                    "prices": prices,
                })
        if conflicts:
            logger.warning("Price conflicts detected for %d models", len(conflicts))
        return conflicts

    def estimate_price(self, model: str, variant: str = "") -> dict[str, Any] | None:
        """Return an estimated price from learned data, or None."""
        data = self._index["models"].get(model)
        if data is None:
            for key in self._index["models"]:
                if model.lower() in key.lower():
                    data = self._index["models"][key]
                    break
        if data is None:
            return None

        avg = data.get("avg_price", 0)
        if variant:
            multiplier = self.get_variant_multiplier(model, variant)
            avg *= multiplier

        return {
            "model": model,
            "variant": variant or "base",
            "estimated_price": round(avg, 2),
            "currency": data["prices"][0]["currency"] if data.get("prices") else "USD",
            "data_points": len(data.get("prices", [])),
            "confidence": "high" if len(data.get("prices", [])) >= 3 else "low",
        }

    def get_variant_multiplier(self, base_model: str, variant: str) -> float:
        """Derive a multiplier for *variant* relative to *base_model*.

        Falls back to heuristic multipliers when insufficient data exists.
        """
        base_data = self._index["models"].get(base_model)
        variant_key = f"{base_model}-{variant}" if variant else base_model
        variant_data = self._index["models"].get(variant_key)

        if base_data and variant_data:
            base_avg = base_data.get("avg_price", 0)
            var_avg = variant_data.get("avg_price", 0)
            if base_avg > 0:
                return round(var_avg / base_avg, 4)

        variant_upper = variant.upper()
        if variant_upper == "X":
            return 1.15
        if variant_upper == "C":
            return 1.0
        return 1.0

    def get_price_index(self) -> dict[str, Any]:
        """Return the full price index for inspection."""
        return dict(self._index)

    async def send_conflict_alert(self, conflicts: list[dict[str, Any]]) -> None:
        """Log price conflicts for review."""
        if not conflicts:
            return

        lines = ["Price Conflicts Detected"]
        for c in conflicts[:10]:
            lines.append(
                f"- {c['model']}: avg ${c['avg_price']:,.0f}, "
                f"deviation {c['max_deviation']:.1%} ({c['price_count']} data points)"
            )
        logger.warning("\n".join(lines))

    # ── internals ─────────────────────────────────────────────────────────

    def _record_price(
        self,
        model: str,
        value: float,
        currency: str,
        source: str,
    ) -> None:
        if model not in self._index["models"]:
            self._index["models"][model] = {
                "prices": [],
                "avg_price": 0,
                "variant_multiplier": 1.0,
            }
        entry = {
            "value": value,
            "currency": currency,
            "source": source,
            "date": datetime.now(timezone.utc).isoformat(),
        }
        existing_sources = {p["source"] for p in self._index["models"][model]["prices"]}
        if source not in existing_sources:
            self._index["models"][model]["prices"].append(entry)

    def _recalculate_averages(self) -> None:
        for data in self._index["models"].values():
            prices = [p["value"] for p in data.get("prices", [])]
            data["avg_price"] = round(sum(prices) / len(prices), 2) if prices else 0
