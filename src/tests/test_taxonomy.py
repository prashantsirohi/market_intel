from market_intel.processing.classifier import classify_event
from market_intel.alerts.rules import decide_alert_level


def test_nav_is_ignored():
    e = classify_event("Mutual Fund NAV disclosure", "Net Asset Value declaration")
    assert e["primary_category"] == "nav_update"
    assert e["event_tier"] == "IGNORE"
    assert e["importance_score"] == 2.0
    assert e["is_ignored"] is True


def test_order_win_is_tier_a():
    e = classify_event("Company received letter of award", "")
    assert e["primary_category"] == "major_order_win"
    assert e["event_tier"] == "A"
    assert e["importance_score"] >= 8.5


def test_tier_a_high_trust_is_critical():
    level = decide_alert_level(
        primary_category="major_order_win",
        importance_score=8.8,
        trust_score=95,
        is_official=True,
    )
    assert level == "critical"


def test_ignore_never_alerts():
    level = decide_alert_level(
        primary_category="nav_update",
        importance_score=2.0,
        trust_score=95,
        is_official=True,
    )
    assert level == "ignore"