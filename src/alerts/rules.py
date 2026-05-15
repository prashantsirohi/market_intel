from processing.taxonomy import IGNORE_CATEGORIES, TIER_A


def decide_alert_level(
    *,
    primary_category: str | None,
    importance_score: float,
    trust_score: float,
    is_official: bool,
) -> str:
    category = (primary_category or "general").lower()

    if category in IGNORE_CATEGORIES:
        return "ignore"

    if category in TIER_A and trust_score >= 80:
        return "critical"

    if importance_score >= 8.5 and trust_score >= 85 and (is_official or trust_score >= 90):
        return "critical"

    if importance_score >= 7.0 and trust_score >= 60:
        return "important"

    return "info"