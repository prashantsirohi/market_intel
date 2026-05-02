from datetime import date, timedelta

from market_intel.processing.time_decay import compute_weight, is_within_lookback


def test_weight_is_one_at_event_date():
    today = date(2026, 5, 1)
    out = compute_weight(event_date=today, as_of=today, category="capex_expansion")
    assert out.weight == 1.0
    assert out.age_days == 0


def test_weight_decays_with_age():
    today = date(2026, 5, 1)
    young = compute_weight(
        event_date=today - timedelta(days=2), as_of=today,
        category="capex_expansion",
    )
    old = compute_weight(
        event_date=today - timedelta(days=14), as_of=today,
        category="capex_expansion",
    )
    assert young.weight > old.weight
    assert 0.0 < old.weight < 1.0


def test_mna_decays_slower_than_results():
    today = date(2026, 5, 1)
    event_d = today - timedelta(days=20)
    mna = compute_weight(event_date=event_d, as_of=today, category="mna_partnership")
    results = compute_weight(event_date=event_d, as_of=today, category="results")
    assert mna.weight > results.weight


def test_lookback_extended_for_mna():
    today = date(2026, 5, 1)
    event_d = today - timedelta(days=60)
    assert is_within_lookback(
        event_date=event_d, as_of=today, category="mna_partnership"
    )
    assert not is_within_lookback(
        event_date=event_d, as_of=today, category="results"
    )


def test_future_dated_event_kept():
    today = date(2026, 5, 1)
    future = today + timedelta(days=5)  # board meeting scheduled
    assert is_within_lookback(
        event_date=future, as_of=today, category="board_meeting"
    )


def test_iso_string_input():
    out = compute_weight(
        event_date="2026-04-30", as_of="2026-05-01",
        category="capex_expansion",
    )
    assert out.age_days == 1
