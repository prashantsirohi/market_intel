from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from market_intel.storage.repositories import (
    RawEvent,
    RawEventRepository,
    ResolvedEvent,
    ResolvedEventRepository,
)

logger = logging.getLogger(__name__)


CATEGORY_PATTERNS = {
    "corporate_action": [
        r"bonus\s*issue",
        r"stock\s*split",
        r"face\s*value",
        r"rights\s*issue",
        r"preferential\s*allotment",
        r"dividend",
        r"interim\s*dividend",
        r"final\s*dividend",
    ],
    "equity": [
        r"buyback",
        r"repurchase",
        r"open\s*offer",
        r"delisting",
        r"scheme\s*of\s*arrangement",
        r"merger",
        r"amalgamation",
    ],
    "debt": [
        r"ncd",
        r"non\s*convertible\s*debenture",
        r"fixed\s*deposit",
        r"fd\s*issue",
        r"bond\s*issue",
    ],
    "regulatory": [
        r"sebi",
        r"roc",
        r"stock\s*exchange",
        r"regulation",
        r"compliance",
    ],
    "financial_result": [
        r"quarter(?:ly)?\s*result",
        r"q[1-4]",
        r"annual\s*result",
        r"fy\d{2,4}",
        r"revenue",
        r"profit",
        r"loss",
    ],
    "agm_egm": [
        r"agm",
        r"annual\s*general\s*meeting",
        r"egm",
        r"extraordinary\s*general\s*meeting",
        r"court\s*meeting",
    ],
    "insider_trading": [
        r"insider\s*trading",
        r"promoter\s*shareholding",
        r"disclosure\s*under\s*reg",
    ],
    "other_material": [
        r"business",
        r"contract",
        r"agreement",
    ],
}

IMPORTANCE_KEYWORDS = {
    9.0: ["bonus issue", "stock split", "rights issue", "buyback", "delisting"],
    8.5: ["merger", "amalgamation", "scheme of arrangement", "dividend", "interim dividend"],
    8.0: ["ncd", "non convertible debenture", "preferential allotment"],
    7.5: ["quarterly result", "annual result", "annual general meeting", "egm"],
    7.0: ["promoter shareholding", "insider trading", "sebi", "disclosure"],
    6.5: ["board meeting", "notice", "postal ballot"],
    6.0: ["update", "revision", "clarification"],
    5.5: ["press release", "investor presentation"],
    5.0: ["general meeting", "meeting"],
    4.5: ["financial result", "operational update"],
    4.0: ["other", "miscellaneous"],
}

SENTIMENT_KEYWORDS = {
    "positive": [
        "bonus", "dividend", "profit", "growth", "increase", "rise", "gain",
        "strong", "improvement", "better", "record", "high", "best",
    ],
    "negative": [
        "loss", "decline", "decrease", "fall", "drop", "weak", "worse",
        "downgrade", "penalty", "violation", "fraud", "investigation",
    ],
    "neutral": [
        "notice", "meeting", "result", "update", "announcement", "filing",
    ],
}


def classify_category(title: str, description: str = "") -> str:
    combined = f"{title} {description}".lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return category
    return "other"


def compute_importance(title: str, description: str = "", category: str = "") -> float:
    combined = f"{title} {description}".lower()

    base_importance = 5.0
    if category in ("corporate_action", "equity", "debt"):
        base_importance = 6.5
    elif category in ("financial_result", "agm_egm"):
        base_importance = 7.0

    for importance, keywords in sorted(IMPORTANCE_KEYWORDS.items(), reverse=True):
        for keyword in keywords:
            if keyword in combined:
                return importance

    return base_importance


def classify_sentiment(title: str, description: str = "") -> tuple[str, float]:
    combined = f"{title} {description}".lower()

    positive_count = sum(1 for w in SENTIMENT_KEYWORDS["positive"] if w in combined)
    negative_count = sum(1 for w in SENTIMENT_KEYWORDS["negative"] if w in combined)

    if positive_count > negative_count:
        score = min(0.5 + (positive_count - negative_count) * 0.15, 1.0)
        return ("positive", score)
    elif negative_count > positive_count:
        score = min(0.5 + (negative_count - positive_count) * 0.15, 1.0)
        return ("negative", score)

    return ("neutral", 0.5)


def compute_trust_score(raw_event: RawEvent) -> float:
    score = 70.0

    if raw_event.link and "nseindia.com" in raw_event.link:
        score += 15.0
    if raw_event.symbol:
        score += 10.0
    if raw_event.company_name:
        score += 5.0

    if raw_event.category_desc:
        score += 5.0

    min_score = 60.0
    max_score = 100.0

    return max(min_score, min(score, max_score))


def decide_alert_level(importance: float, trust: float, category: str = "") -> str:
    if importance >= 8.5 and trust >= 80:
        return "critical"
    elif importance >= 7.0 and trust >= 60:
        return "important"
    return "info"


class EventAnalysisService:
    def __init__(
        self,
        raw_event_repo: RawEventRepository,
        resolved_event_repo: ResolvedEventRepository,
    ):
        self.raw_event_repo = raw_event_repo
        self.resolved_event_repo = resolved_event_repo

    def analyze_event(self, raw_event: RawEvent) -> Optional[ResolvedEvent]:
        category = classify_category(
            raw_event.title or "", raw_event.description or ""
        )
        importance = compute_importance(
            raw_event.title or "", raw_event.description or "", category
        )
        sentiment_label, sentiment_score = classify_sentiment(
            raw_event.title or "", raw_event.description or ""
        )
        trust = compute_trust_score(raw_event)
        alert_level = decide_alert_level(importance, trust, category)

        resolved = self.resolved_event_repo.upsert(
            raw_event_id=raw_event.raw_event_id,
            primary_category=category,
            importance_score=importance,
            trust_score=trust,
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            alert_level=alert_level,
            summary_text=raw_event.title,
            is_official="nseindia.com" in (raw_event.link or ""),
            status="pending",
        )

        self.raw_event_repo.mark_processed(raw_event.raw_event_id)

        return resolved

    def analyze_pending(self, limit: int = 100) -> dict[str, int]:
        raw_events = self.raw_event_repo.list_unprocessed(limit)
        stats = {"analyzed": 0, "errors": 0}

        for raw_event in raw_events:
            try:
                self.analyze_event(raw_event)
                stats["analyzed"] += 1
            except Exception as e:
                logger.error(f"Error analyzing event {raw_event.raw_event_id}: {e}")
                stats["errors"] += 1

        return stats