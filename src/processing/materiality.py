"""Materiality scoring: scale event importance by deal size relative to market cap.

A ₹500Cr capex on a ₹50,000Cr company is noise; the same on a ₹1,000Cr company
is highly material. The trading-system enrichment uses this to filter events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MaterialityLabel = Literal["low", "medium", "high", "critical"]


# Per-category thresholds: deal_value / market_cap ratios that map to each tier.
# Tunable via config in the host system; these defaults reflect typical Indian-
# equities practice (bulk-deal disclosure threshold is 0.5% of equity).
DEFAULT_THRESHOLDS: dict[str, dict[MaterialityLabel, float]] = {
    "capex_expansion": {"low": 0.0, "medium": 0.02, "high": 0.05, "critical": 0.10},
    "major_order_win": {"low": 0.0, "medium": 0.01, "high": 0.03, "critical": 0.08},
    "buyback":         {"low": 0.0, "medium": 0.02, "high": 0.05, "critical": 0.10},
    "fundraise":       {"low": 0.0, "medium": 0.02, "high": 0.05, "critical": 0.10},
    "mna_partnership": {"low": 0.0, "medium": 0.01, "high": 0.05, "critical": 0.15},
    "demerger":        {"low": 0.0, "medium": 0.05, "high": 0.15, "critical": 0.30},
    "bulk_deal":       {"low": 0.0, "medium": 0.005, "high": 0.01, "critical": 0.02},
    "block_deal":      {"low": 0.0, "medium": 0.005, "high": 0.01, "critical": 0.02},
    "sast_filing":     {"low": 0.0, "medium": 0.02, "high": 0.05, "critical": 0.10},
    "insider_buy":     {"low": 0.0, "medium": 0.001, "high": 0.005, "critical": 0.02},
    "insider_sell":    {"low": 0.0, "medium": 0.001, "high": 0.005, "critical": 0.02},
}


@dataclass(frozen=True)
class MaterialityResult:
    label: MaterialityLabel
    material_pct: float | None
    deal_value_inr: float | None
    market_cap_inr: float | None


# Regex for extracting INR amounts from titles/descriptions. Supports formats
# like "Rs. 1,500 crore", "₹500 Cr", "INR 1.2 Bn", "Rs 25,00,00,000".
_AMOUNT_PATTERNS = [
    # ₹/Rs/INR + number + cr/crore
    re.compile(
        r"(?:rs\.?|₹|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:cr|crore|crores)\b",
        re.IGNORECASE,
    ),
    # ₹/Rs/INR + number + bn/billion (treat as 100 cr)
    re.compile(
        r"(?:rs\.?|₹|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:bn|billion)\b",
        re.IGNORECASE,
    ),
    # Bare "X crore" without currency symbol
    re.compile(
        r"\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:cr|crore|crores)\b",
        re.IGNORECASE,
    ),
]


def extract_deal_value_inr(text: str | None) -> float | None:
    """Return the largest INR amount found in `text`, in rupees.

    Returns None if no amount is detected. Picks the maximum because release
    titles often state several numbers (e.g. order value vs total order book)
    and the max is usually the headline figure.
    """
    if not text:
        return None
    candidates: list[float] = []
    for pattern in _AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            num_str = match.group(1).replace(",", "")
            try:
                value = float(num_str)
            except ValueError:
                continue
            if "bn" in match.group(0).lower() or "billion" in match.group(0).lower():
                value_inr = value * 1_000_000_000
            else:
                value_inr = value * 10_000_000  # crore = 1e7
            candidates.append(value_inr)
    if not candidates:
        return None
    return max(candidates)


def score(
    *,
    category: str,
    deal_value_inr: float | None,
    market_cap_inr: float | None,
    thresholds: dict[str, dict[MaterialityLabel, float]] | None = None,
) -> MaterialityResult:
    """Compute a materiality label.

    If either deal_value or market_cap is unavailable, returns label="medium"
    (neutral assumption — the host filter chain decides whether to suppress).
    """
    if deal_value_inr is None or market_cap_inr is None or market_cap_inr <= 0:
        return MaterialityResult(
            label="medium",
            material_pct=None,
            deal_value_inr=deal_value_inr,
            market_cap_inr=market_cap_inr,
        )

    pct = deal_value_inr / market_cap_inr
    cat_thresholds = (thresholds or DEFAULT_THRESHOLDS).get(
        category, DEFAULT_THRESHOLDS["capex_expansion"]
    )

    if pct >= cat_thresholds["critical"]:
        label: MaterialityLabel = "critical"
    elif pct >= cat_thresholds["high"]:
        label = "high"
    elif pct >= cat_thresholds["medium"]:
        label = "medium"
    else:
        label = "low"

    return MaterialityResult(
        label=label,
        material_pct=pct,
        deal_value_inr=deal_value_inr,
        market_cap_inr=market_cap_inr,
    )
