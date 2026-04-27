TIER_A = {
    "management_change",
    "regulatory_legal",
    "major_order_win",
    "capex_expansion",
    "buyback",
    "promoter_activity",
}

TIER_B = {
    "results",
    "board_meeting",
    "dividend",
    "fundraise",
    "mna_partnership",
}

TIER_C = {
    "credit_rating",
    "guidance",
    "clarification",
}

IGNORE_CATEGORIES = {
    "nav_update",
    "newspaper_publication",
    "investor_meet",
    "agm_notice",
    "compliance_certificate",
    "loss_of_certificate",
    "analyst_call",
}

CATEGORY_IMPORTANCE = {
    "management_change": 9.0,
    "regulatory_legal": 9.5,
    "major_order_win": 8.8,
    "capex_expansion": 8.5,
    "buyback": 9.2,
    "promoter_activity": 9.0,
    "results": 8.0,
    "board_meeting": 7.2,
    "dividend": 7.2,
    "fundraise": 8.0,
    "mna_partnership": 8.0,
    "credit_rating": 6.5,
    "guidance": 7.0,
    "clarification": 6.0,
    "nav_update": 2.0,
    "newspaper_publication": 2.0,
    "investor_meet": 2.0,
    "agm_notice": 2.0,
    "compliance_certificate": 2.0,
    "loss_of_certificate": 2.0,
    "analyst_call": 2.0,
    "general": 5.0,
}


KEYWORDS = {
    "management_change": [
        "resignation", "resigned", "appointment", "appointed",
        "chief executive officer", "ceo", "chief financial officer",
        "cfo", "managing director", "md", "director", "cessation", "demise"
    ],
    "regulatory_legal": [
        "sebi", "nclt", "litigation", "penalty", "tax demand",
        "gst demand", "show cause", "investigation", "default",
        "insolvency", "cci", "tribunal", "disclosure under", "takeover"
    ],
    "major_order_win": [
        "order win", "order received", "contract awarded",
        "letter of award", "loa", "l1 bidder", "work order",
        "purchase order", "order book", "bagging", "awarding"
    ],
    "capex_expansion": [
        "capex", "capital expenditure", "capacity expansion",
        "new plant", "greenfield", "brownfield", "commissioning",
        "expansion project", "manufacturing facility"
    ],
    "buyback": ["buyback", "share repurchase", "buy-back"],
    "promoter_activity": [
        "promoter pledge", "pledge", "encumbrance",
        "promoter acquisition", "promoter sale", "stake sale",
        "promoter buying"
    ],
    "results": [
        "financial results", "quarterly results", "audited results",
        "unaudited results", "standalone and consolidated",
        "reg. 33", "quarterly"
    ],
    "board_meeting": [
        "board meeting", "meeting of the board", "board of directors"
    ],
    "dividend": ["dividend", "interim dividend", "final dividend", "record date"],
    "fundraise": [
        "qip", "qualified institutional placement", "rights issue",
        "preferential allotment", "fund raising", "fundraise",
        "ncd", "debenture", "warrants", "bonus issue"
    ],
    "mna_partnership": [
        "acquisition", "merger", "amalgamation", "joint venture",
        "strategic partnership", "mou", "memorandum of understanding",
        "stake acquisition"
    ],
    "credit_rating": [
        "credit rating", "rating upgrade", "rating downgrade",
        "rating reaffirmed", "outlook revised"
    ],
    "guidance": ["guidance", "outlook", "business update", "operational update"],
    "clarification": ["clarification", "rumour", "rumor", "price movement"],
    "nav_update": ["net asset value", "nav", "declaration of nav"],
    "newspaper_publication": ["newspaper publication", "publication of notice"],
    "investor_meet": [
        "investor presentation", "investor meet", "analyst meet",
        "conference call", "earnings call", "institutional investor"
    ],
    "agm_notice": [
        "annual general meeting", "agm", "egm", "extra ordinary general meeting"
    ],
    "compliance_certificate": [
        "compliance certificate", "certificate under regulation",
        "secretarial compliance"
    ],
    "loss_of_certificate": [
        "loss of share certificate", "duplicate share certificate"
    ],
    "analyst_call": ["analyst call", "investor call"],
}


def category_tier(category: str) -> str:
    if category in TIER_A:
        return "A"
    if category in TIER_B:
        return "B"
    if category in TIER_C:
        return "C"
    if category in IGNORE_CATEGORIES:
        return "IGNORE"
    return "GENERAL"


def category_importance(category: str) -> float:
    return CATEGORY_IMPORTANCE.get(category, 5.0)


def is_ignored(category: str) -> bool:
    return category in IGNORE_CATEGORIES