from __future__ import annotations

from market_intel.alerts.rules import decide_alert_level
from market_intel.processing.trust import compute_trust_score, is_official_source


def classify_category(raw_event: dict) -> str:
    title = (raw_event.get("title") or "")
    desc = (raw_event.get("description") or "").lower()
    
    # Extract event type from NSE format: "...|SUBJECT: Board Meeting Intimation"
    event_type = ""
    if "|" in desc:
        event_type = desc.split("|")[-1].strip()
    
    # === PRIORITY 1: Most common (225 NAV declarations) ===
    if "declaration of nav" in event_type:
        return "mutual_fund_nav"
    if title and ("Mutual Fund" in title or " ETF" in title):
        if "nav" in desc:
            return "mutual_fund_nav"
    
    # === PRIORITY 2: Board meetings ===
    if "board meeting" in event_type:
        if "intimation" in event_type or "schedule" in event_type:
            return "board_meeting_intimation"
        if "outcome" in event_type:
            return "board_meeting_outcome"
        return "board_meeting"
    
    # === PRIORITY 3: Management changes ===
    if "cessation" in event_type or "demise" in event_type:
        return "management_change"
    if "change in directors" in event_type or "change in kmp" in event_type or "change in smp" in event_type:
        return "management_change"
    
    # === PRIORITY 4: Other event types ===
    if any(k in event_type for k in ["buyback", "repurchase"]):
        return "buyback"
    if any(k in event_type for k in ["dividend", "record date"]):
        return "dividend"
    if any(k in event_type for k in ["rights issue", "qip", "preferential allotment", "bonus issue"]):
        return "fundraise"
    if any(k in event_type for k in ["esop", "esos", "esps"]):
        return "esop_allotment"
    if "allotment" in event_type:
        return "share_allotment"
    if any(k in event_type for k in ["bagging", "award", "loa"]):
        return "major_order_win"
    if any(k in event_type for k in ["result", "quarterly", "annual", "financial", "unaudited"]):
        return "results"
    if "deviation" in event_type or "variation" in event_type:
        return "deviation_statement"
    if any(k in event_type for k in ["sebi", "takeover", "regulation 51", "disclosure under"]):
        return "regulatory"
    
    # === PRIORITY 5: General ===
    if "press release" in event_type:
        return "press_release"
    if "analyst" in event_type or "investor meet" in event_type:
        return "investor_meet"
    if "shareholders meeting" in event_type:
        return "shareholders_meeting"
    if "newspaper publication" in event_type:
        return "newspaper_publication"
    if "price movement" in event_type:
        return "price_movement"
    if "agreements" in event_type:
        return "agreements"
    
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