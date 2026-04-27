from __future__ import annotations

from market_intel.alerts.rules import decide_alert_level
from market_intel.processing.trust import compute_trust_score, is_official_source


def classify_category(raw_event: dict) -> str:
    text = f"{raw_event.get('title', '')} {raw_event.get('description', '')}".lower()
    if any(k in text for k in ["resignation", "appoint", "director", "ceo", "managing director"]):
        return "management_change"
    if any(k in text for k in ["sebi", "nclt", "penalty", "litigation", "tax demand"]):
        return "regulatory_legal"
    if any(k in text for k in ["buyback", "repurchase"]):
        return "buyback"
    if any(k in text for k in ["order", "contract awarded", "l1 bidder"]):
        return "major_order_win"
    if any(k in text for k in ["capex", "expansion", "new plant", "capacity expansion"]):
        return "capex_expansion"
    if "board meeting" in text:
        return "board_meeting"
    if any(k in text for k in ["results", "financial results", "quarterly results"]):
        return "results"
    if "dividend" in text:
        return "dividend"
    if any(k in text for k in ["rights issue", "qip", "preferential allotment"]):
        return "fundraise"
    return "general"


def classify_sentiment(raw_event: dict) -> tuple[str, float]:
    text = f"{raw_event.get('title', '')} {raw_event.get('description', '')}".lower()
    positive = ["buyback", "order win", "expansion", "dividend", "rating upgrade"]
    negative = ["penalty", "pledge", "downgrade", "default", "resignation", "tax demand"]
    score = 0.0
    for k in positive:
        if k in text:
            score += 1.0
    for k in negative:
        if k in text:
            score -= 1.0
    if score >= 1:
        return "positive", min(score / 3, 1.0)
    if score <= -1:
        return "negative", max(score / 3, -1.0)
    return "neutral", 0.0


def compute_importance(raw_event: dict, category: str) -> float:
    if category in {"management_change", "regulatory_legal", "buyback", "major_order_win", "capex_expansion"}:
        return 8.5
    if category in {"board_meeting", "results", "dividend", "fundraise"}:
        return 7.2
    return 5.0


class EventAnalysisService:
    def __init__(self, raw_repo, resolved_repo, entity_resolver) -> None:
        self.raw_repo = raw_repo
        self.resolved_repo = resolved_repo
        self.entity_resolver = entity_resolver

    def process_raw_event(self, raw_event: dict, raw_event_id: int) -> dict:
        symbol = self.entity_resolver.resolve(raw_event.get("symbol"), raw_event.get("title", "")) or raw_event.get("symbol")
        source = raw_event.get("source", "unknown")
        source_type = raw_event.get("source_type", "unknown")
        source_event_type = raw_event.get("source_event_type", "")
        trust_score = compute_trust_score(source, source_type)
        official = is_official_source(source, source_type, source_event_type)
        primary_category = classify_category(raw_event)
        sentiment_label, sentiment_score = classify_sentiment(raw_event)
        importance_score = compute_importance(raw_event, primary_category)
        alert_level = decide_alert_level(
            primary_category=primary_category,
            importance_score=importance_score,
            trust_score=trust_score,
            is_official=official,
        )
        
        result = {
            "raw_event_id": raw_event_id,
            "entity_id": None,
            "primary_category": primary_category,
            "secondary_category": None,
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "importance_score": importance_score,
            "trust_score": trust_score,
            "parser_confidence": 0.9,
            "novelty_score": 1.0,
            "alert_level": alert_level,
            "is_official": official,
            "summary_text": raw_event.get("title"),
        }
        
        resolved_event_id = self.resolved_repo.upsert(**result)
        self.raw_repo.mark_processed(raw_event_id)
        result["resolved_event_id"] = resolved_event_id
        return result