from __future__ import annotations

from alerts.rules import decide_alert_level
from processing.classifier import classify_event
from processing.trust import compute_trust_score, is_official_source


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


class EventAnalysisService:
    def __init__(self, raw_repo, resolved_repo, entity_resolver) -> None:
        self.raw_repo = raw_repo
        self.resolved_repo = resolved_repo
        self.entity_resolver = entity_resolver

    def process_raw_event(self, raw_event: dict, raw_event_id: int) -> dict:
        title = raw_event.get("title") or ""
        description = raw_event.get("description") or ""
        
        symbol = self.entity_resolver.resolve(raw_event.get("symbol"), title) or raw_event.get("symbol")
        source = raw_event.get("source", "unknown")
        source_type = raw_event.get("source_type", "unknown")
        source_event_type = raw_event.get("source_event_type", "")
        
        classified = classify_event(title, description)
        
        trust_score = compute_trust_score(source, source_type)
        official = is_official_source(source, source_type, source_event_type)
        sentiment_label, sentiment_score = classify_sentiment(raw_event)
        
        alert_level = decide_alert_level(
            primary_category=classified["primary_category"],
            importance_score=classified["importance_score"],
            trust_score=trust_score,
            is_official=official,
        )
        
        result = {
            "raw_event_id": raw_event_id,
            "entity_id": None,
            "primary_category": classified["primary_category"],
            "secondary_category": None,
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "importance_score": classified["importance_score"],
            "trust_score": trust_score,
            "parser_confidence": 0.9,
            "novelty_score": 1.0,
            "alert_level": alert_level,
            "is_official": official,
            "summary_text": title,
            "event_tier": classified["event_tier"],
            "ignored_reason": f"ignored:{classified['primary_category']}" if classified["is_ignored"] else None,
        }
        
        resolved_event_id = self.resolved_repo.upsert(**result)
        self.raw_repo.mark_processed(raw_event_id)
        result["resolved_event_id"] = resolved_event_id
        return result