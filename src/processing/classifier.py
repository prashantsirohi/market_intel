import re

from processing.taxonomy import (
    KEYWORDS,
    CATEGORY_IMPORTANCE,
    category_importance,
    category_tier,
    is_ignored,
)
from processing.utils import normalize_text


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


from processing.utils import normalize_text


def classify_category(title: str, description: str | None = None) -> str:
    text = normalize_text(f"{title or ''} {description or ''}")

    priority = [
        "demerger",
        "results",
        "management_change",
        "buyback",
        "major_order_win",
        "capex_expansion",
        "fundraise",
        "dividend",
        "board_meeting",
        "sast_filing",
        "rating_downgrade",
        "rating_upgrade",
        "rating_reaffirmed",
        "block_deal",
        "bulk_deal",
        "insider_sell",
        "insider_buy",
        "mna_partnership",
        "regulatory_legal",
        "compliance_certificate",
        "credit_rating",
        "promoter_activity",
        "loss_of_certificate",
        "guidance",
        "analyst_call",
        "investor_meet",
        "agm_notice",
        "newspaper_publication",
        "nav_update",
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