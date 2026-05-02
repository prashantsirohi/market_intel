"""Exponential time-decay weighting for resolved events.

Recent events are more actionable than stale ones, but ongoing M&A and
litigation processes stay relevant for longer. Per-category τ (tau) lets
callers tune the half-life.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone


# Tau (in days) controls the decay rate: weight = exp(-Δdays / tau).
# Larger tau = slower decay = event stays relevant longer.
DEFAULT_TAU_DAYS: dict[str, float] = {
    "mna_partnership": 30.0,
    "demerger": 30.0,
    "regulatory_legal": 30.0,
    "sast_filing": 21.0,
    "buyback": 14.0,
    "fundraise": 14.0,
    "capex_expansion": 14.0,
    "rating_downgrade": 14.0,
    "rating_upgrade": 10.0,
    "results": 7.0,
    "board_meeting": 7.0,
    "dividend": 7.0,
    "insider_buy": 7.0,
    "insider_sell": 7.0,
    "bulk_deal": 5.0,
    "block_deal": 5.0,
    "major_order_win": 7.0,
    "promoter_activity": 14.0,
    "management_change": 14.0,
}

DEFAULT_TAU_FALLBACK = 7.0


@dataclass(frozen=True)
class DecayResult:
    weight: float          # 0.0 - 1.0
    age_days: float
    tau_days: float


def _to_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


def compute_weight(
    *,
    event_date: date | datetime | str,
    as_of: date | datetime | None = None,
    category: str,
    tau_days: dict[str, float] | None = None,
) -> DecayResult:
    """Return an exponential decay weight in [0, 1]."""
    event_d = _to_date(event_date)
    if as_of is None:
        as_of_d = datetime.now(timezone.utc).date()
    else:
        as_of_d = _to_date(as_of)

    age = max(0.0, float((as_of_d - event_d).days))
    tau = (tau_days or DEFAULT_TAU_DAYS).get(category, DEFAULT_TAU_FALLBACK)
    weight = math.exp(-age / tau) if tau > 0 else 0.0
    return DecayResult(weight=weight, age_days=age, tau_days=tau)


def is_within_lookback(
    *,
    event_date: date | datetime | str,
    as_of: date | datetime | None = None,
    category: str,
    routine_lookback_days: int = 30,
    extended_lookback_days: int = 90,
    extended_categories: set[str] = frozenset({
        "mna_partnership", "demerger", "regulatory_legal", "sast_filing",
    }),
) -> bool:
    """Hard cut-off for the noise filter: returns False if event is stale."""
    event_d = _to_date(event_date)
    if as_of is None:
        as_of_d = datetime.now(timezone.utc).date()
    else:
        as_of_d = _to_date(as_of)

    age = (as_of_d - event_d).days
    if age < 0:
        return True  # future-dated event (record date, board meeting): keep
    cutoff = (
        extended_lookback_days
        if category in extended_categories
        else routine_lookback_days
    )
    return age <= cutoff
