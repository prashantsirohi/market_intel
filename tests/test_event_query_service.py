from datetime import date, datetime, timezone

from market_intel.services.event_query_service import EventQueryService


def test_get_events_for_symbol_returns_seeded_event(seeded_db):
    svc = EventQueryService(db=seeded_db)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    events = svc.get_events_for_symbol("RELIANCE", since=since, min_trust=80.0)
    assert len(events) == 1
    e = events[0]
    assert e.symbol == "RELIANCE"
    assert e.primary_category == "capex_expansion"
    assert e.event_tier == "A"
    assert e.trust_score == 95.0


def test_trust_filter_excludes_low_trust(seeded_db):
    svc = EventQueryService(db=seeded_db)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    events = svc.get_events_for_symbol("RELIANCE", since=since, min_trust=99.0)
    assert events == []


def test_tier_filter_excludes_non_a(seeded_db):
    svc = EventQueryService(db=seeded_db)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    # capex_expansion is Tier A; restrict to Tier B only -> nothing
    events = svc.get_events_for_symbol(
        "RELIANCE", since=since, tiers=("B",), min_trust=80.0,
    )
    assert events == []


def test_get_events_for_universe(seeded_db):
    svc = EventQueryService(db=seeded_db)
    since = datetime(2026, 4, 1, tzinfo=timezone.utc)
    out = svc.get_events_for_universe(
        ["RELIANCE", "TCS"], since=since, min_trust=80.0,
    )
    assert "RELIANCE" in out and "TCS" in out
    assert len(out["RELIANCE"]) == 1
    assert out["TCS"] == []


def test_get_bulk_deals(seeded_db):
    svc = EventQueryService(db=seeded_db)
    deals = svc.get_bulk_deals(["RELIANCE"], since=date(2026, 4, 1))
    assert len(deals) == 1
    assert deals[0].symbol == "RELIANCE"
    assert deals[0].deal_value_cr == 120.0
    assert deals[0].is_block is False


def test_get_important_events_returns_market_wide_seeded_event(seeded_db):
    svc = EventQueryService(db=seeded_db)
    events = svc.get_important_events(
        since=datetime(2026, 4, 1, tzinfo=timezone.utc),
        min_trust=80.0,
    )
    assert len(events) == 1
    assert events[0].symbol == "RELIANCE"
    assert events[0].event_hash == "hash-reliance-001"


def test_get_market_caps_returns_inr(seeded_db):
    with seeded_db.get_connection() as conn:
        conn.execute(
            "INSERT INTO tracked_entity (symbol, market_cap_cr) VALUES (?, ?)",
            ["RELIANCE", 1500.0],
        )
    svc = EventQueryService(db=seeded_db)
    assert svc.get_market_caps(["RELIANCE"]) == {"RELIANCE": 1500.0 * 1e7}
