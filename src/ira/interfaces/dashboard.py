"""Performance dashboard — HTML view of CRM and LearningHub metrics.

Provides a single GET endpoint that aggregates interaction volume,
intent distribution, feedback trends, pipeline qualification, and
campaign activity, then renders them into a Chart.js-powered template.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ira.interfaces.server import _svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_QUALIFIED_STAGES = {"QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON"}


def _parse_route(interaction: Any) -> str:
    """Extract the routing method from an interaction's JSON content field."""
    raw = interaction.content
    if not raw:
        return "unknown"
    try:
        data = json.loads(raw)
        return data.get("route", "unknown")
    except (json.JSONDecodeError, TypeError):
        return "unknown"


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the performance dashboard."""
    crm = _svc("crm")
    learning_hub = _svc("learning_hub")

    interactions = await crm.list_interactions()
    pipeline = await crm.get_pipeline_summary()
    campaigns = await crm.list_campaigns(filters={"status": "ACTIVE"})
    feedback_records = learning_hub.get_all_feedback()

    # -- Interactions by day --------------------------------------------------
    day_counts: dict[str, int] = defaultdict(int)
    intent_counter: Counter[str] = Counter()

    for ix in interactions:
        day_key = ix.created_at.strftime("%Y-%m-%d") if ix.created_at else "unknown"
        day_counts[day_key] += 1
        intent_counter[_parse_route(ix)] += 1

    sorted_days = sorted(day_counts.keys())
    interactions_by_day_labels = sorted_days
    interactions_by_day_values = [day_counts[d] for d in sorted_days]

    # -- Intent distribution --------------------------------------------------
    intent_labels = list(intent_counter.keys()) or ["none"]
    intent_values = list(intent_counter.values()) or [0]

    # -- Leads qualified (QUALIFIED + later stages) ---------------------------
    stages: dict[str, Any] = pipeline.get("stages", {})
    leads_qualified = sum(
        stage_data.get("count", 0)
        for stage_name, stage_data in stages.items()
        if stage_name in _QUALIFIED_STAGES
    )

    # -- Feedback metrics -----------------------------------------------------
    fb_day_scores: dict[str, list[int]] = defaultdict(list)
    for rec in feedback_records:
        fb_day = rec.created_at.strftime("%Y-%m-%d")
        fb_day_scores[fb_day].append(rec.feedback_score)

    sorted_fb_days = sorted(fb_day_scores.keys())
    feedback_trend_labels = sorted_fb_days
    feedback_trend_values = [
        round(sum(fb_day_scores[d]) / len(fb_day_scores[d]), 1)
        for d in sorted_fb_days
    ]

    all_scores = [r.feedback_score for r in feedback_records]
    avg_feedback = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0.0

    # -- Template context -----------------------------------------------------
    context = {
        "request": request,
        "total_interactions": len(interactions),
        "avg_feedback": avg_feedback,
        "intents_classified": len(intent_counter),
        "leads_qualified": leads_qualified,
        "active_campaigns": len(campaigns),
        "interactions_by_day_labels": interactions_by_day_labels,
        "interactions_by_day_values": interactions_by_day_values,
        "intent_labels": intent_labels,
        "intent_values": intent_values,
        "feedback_trend_labels": feedback_trend_labels,
        "feedback_trend_values": feedback_trend_values,
    }
    return templates.TemplateResponse("dashboard.html", context)
