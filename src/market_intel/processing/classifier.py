import re

from market_intel.processing.taxonomy import (
    KEYWORDS,
    CATEGORY_IMPORTANCE,
    category_importance,
    category_tier,
    is_ignored,
)


CATEGORY_MAP = {
    "board_meeting_outcome": "board_meeting",
    "board_meeting_intimation": "board_meeting",
    "deviation_statement": "compliance_certificate",
    "esop_allotment": "fundraise",
    "share_allotment": "fundraise",
    "price_movement": "clarification",
    "agreements": "mna_partnership",
    "press_release": "clarification",
    "shareholders_meeting": "agm_notice",
}


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def classify_category(title: str, description: str | None = None) -> str:
    text = normalize_text(f"{title or ''} {description or ''}")

    priority = [
        "nav_update",
        "loss_of_certificate",
        "compliance_certificate",
        "newspaper_publication",
        "investor_meet",
        "agm_notice",
        "analyst_call",
        "regulatory_legal",
        "promoter_activity",
        "management_change",
        "buyback",
        "major_order_win",
        "capex_expansion",
        "fundraise",
        "mna_partnership",
        "results",
        "board_meeting",
        "dividend",
        "credit_rating",
        "guidance",
        "clarification",
    ]

    for category in priority:
        for keyword in KEYWORDS.get(category, []):
            if keyword in text:
                return CATEGORY_MAP.get(category, category)

    return "clarification"


def classify_event(title: str, description: str | None = None) -> dict:
    raw_category = classify_category(title, description)
    
    return {
        "primary_category": raw_category,
        "event_tier": category_tier(raw_category),
        "importance_score": category_importance(raw_category),
        "is_ignored": is_ignored(raw_category),
    }