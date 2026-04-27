from __future__ import annotations

CRITICAL_CATEGORIES = {
    "management_change",
    "regulatory_legal",
    "promoter_pledge",
    "buyback",
    "major_order_win",
    "capex_expansion",
}

IMPORTANT_CATEGORIES = {
    "board_meeting",
    "results",
    "dividend",
    "rights_issue",
    "fundraise",
}


def decide_alert_level(
    *,
    primary_category: str | None,
    importance_score: float,
    trust_score: float,
    is_official: bool,
) -> str:
    category = (primary_category or "").strip().lower()

    if category in CRITICAL_CATEGORIES and trust_score >= 80:
        return "critical"
    if importance_score >= 8.5 and trust_score >= 85 and (is_official or trust_score >= 90):
        return "critical"
    if category in IMPORTANT_CATEGORIES and trust_score >= 60:
        return "important"
    if importance_score >= 7.0 and trust_score >= 60:
        return "important"
    return "info"