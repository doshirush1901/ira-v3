"""Lead ranker: score deals/leads 0–100 by order size, interest, stage, customer status, meeting.

Formula is documented in data/knowledge/lead_ranker_formula.md.
Used by CRM (list_deals_with_lead_score), API, and scripts.
"""

from __future__ import annotations

import logging
from typing import Any

from ira.data.models import Channel, ContactType, DealStage

logger = logging.getLogger(__name__)

# Weights (must sum to 100)
MAX_ORDER_SIZE_PTS = 20
MAX_INTEREST_PTS = 20
MAX_STAGE_PTS = 40
MAX_EXISTING_CUSTOMER_PTS = 10
MAX_MEETING_PTS = 10

# Order size bands (USD): (min_inclusive, max_exclusive, points)
_ORDER_SIZE_BANDS = [
    (0, 1, 0),
    (1, 50_000, 5),
    (50_000, 100_000, 8),
    (100_000, 250_000, 12),
    (250_000, 1_000_000, 16),
    (1_000_000, float("inf"), 20),
]

# Interest (genuine replies or emails from them): (min_replies, points). Descending min for lookup.
_INTEREST_BANDS = [
    (51, 20),
    (31, 17),
    (16, 14),
    (6, 10),
    (1, 5),
    (0, 0),
]

# Stage -> points (0–40)
_STAGE_POINTS = {
    DealStage.NEW: 0,
    DealStage.CONTACTED: 5,
    DealStage.ENGAGED: 10,
    DealStage.QUALIFIED: 15,
    DealStage.PROPOSAL: 25,
    DealStage.NEGOTIATION: 35,
    DealStage.WON: 40,
    DealStage.LOST: 0,
}


def _normalize_stage(stage: DealStage | str | None) -> DealStage | None:
    if stage is None:
        return None
    if isinstance(stage, DealStage):
        return stage
    s = (stage or "").strip().upper()
    if not s:
        return None
    for e in DealStage:
        if e.value == s:
            return e
    return None


def _order_size_score(value_usd: float | None) -> int:
    """0–20 points from deal value in USD."""
    if value_usd is None or value_usd <= 0:
        return 0
    for low, high, pts in _ORDER_SIZE_BANDS:
        if low <= value_usd < high:
            return pts
    return 20


def _interest_score(genuine_replies: int | None = None, emails_from_them: int | None = None) -> int:
    """0–20 points from engagement. Prefer genuine_replies; fallback to emails_from_them."""
    count = genuine_replies if genuine_replies is not None else emails_from_them
    if count is None or count <= 0:
        return 0
    for min_r, pts in _INTEREST_BANDS:
        if count >= min_r:
            return pts
    return 0


def _stage_score(stage: DealStage | str | None) -> int:
    """0–40 points from pipeline stage."""
    s = _normalize_stage(stage)
    if s is None:
        return 0
    return _STAGE_POINTS.get(s, 0)


def _existing_customer_score(contact_type: ContactType | str | None) -> int:
    """0 or 10 points. LIVE_CUSTOMER / PAST_CUSTOMER => 10."""
    if contact_type is None:
        return 0
    if isinstance(contact_type, ContactType):
        ct = contact_type
    else:
        try:
            ct = ContactType((contact_type or "").strip())
        except ValueError:
            return 0
    if ct in (ContactType.LIVE_CUSTOMER, ContactType.PAST_CUSTOMER):
        return MAX_EXISTING_CUSTOMER_PTS
    return 0


def _meeting_score(had_meeting_or_web_call: bool) -> int:
    """0 or 10 points."""
    return MAX_MEETING_PTS if had_meeting_or_web_call else 0


def score_lead(
    *,
    value_usd: float | None = None,
    stage: DealStage | str | None = None,
    contact_type: ContactType | str | None = None,
    genuine_replies: int | None = None,
    emails_from_them: int | None = None,
    had_meeting_or_web_call: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Compute lead score 0–100 and component breakdown.

    Args:
        value_usd: Deal/quote value in USD (converted if needed).
        stage: Deal stage (enum or string).
        contact_type: LIVE_CUSTOMER, PAST_CUSTOMER, or lead type.
        genuine_replies: Non–auto-reply emails we received from them (preferred).
        emails_from_them: Total emails from them (used if genuine_replies not set).
        had_meeting_or_web_call: True if any interaction channel is MEETING or WEB.

    Returns:
        (score_0_100, breakdown_dict) where breakdown has keys:
        order_size_pts, interest_pts, stage_pts, existing_customer_pts, meeting_pts, total_raw.
    """
    order_pts = _order_size_score(value_usd)
    interest_pts = _interest_score(genuine_replies=genuine_replies, emails_from_them=emails_from_them)
    stage_pts = _stage_score(stage)
    customer_pts = _existing_customer_score(contact_type)
    meeting_pts = _meeting_score(had_meeting_or_web_call)

    total_raw = order_pts + interest_pts + stage_pts + customer_pts + meeting_pts
    score = min(100, total_raw)

    breakdown = {
        "order_size_pts": order_pts,
        "interest_pts": interest_pts,
        "stage_pts": stage_pts,
        "existing_customer_pts": customer_pts,
        "meeting_pts": meeting_pts,
        "total_raw": total_raw,
    }
    return score, breakdown


def had_meeting_or_web_call(channels: list[str | Channel] | None) -> bool:
    """True if any channel is MEETING or WEB."""
    if not channels:
        return False
    for ch in channels:
        if ch is None:
            continue
        if isinstance(ch, Channel):
            if ch in (Channel.MEETING, Channel.WEB):
                return True
        else:
            s = (ch or "").strip().upper()
            if s in ("MEETING", "WEB"):
                return True
    return False
