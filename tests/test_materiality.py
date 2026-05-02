import pytest

from market_intel.processing.materiality import (
    extract_deal_value_inr,
    score,
)


@pytest.mark.parametrize(
    "text, expected_inr",
    [
        ("Capex announcement: Rs. 1,500 crore expansion", 1500e7),
        ("₹500 Cr buyback approved", 500e7),
        ("INR 1.2 Bn fundraise via QIP", 1.2e9),
        ("Order win worth 250 crore from Indian Railways", 250e7),
        ("Company announces multi-product launch", None),
        ("Rs 25,000 crore mega capex", 25000e7),
    ],
)
def test_extract_deal_value(text, expected_inr):
    assert extract_deal_value_inr(text) == expected_inr


def test_materiality_scales_by_market_cap():
    small = score(category="capex_expansion", deal_value_inr=500e7,
                  market_cap_inr=1_000e7)
    large = score(category="capex_expansion", deal_value_inr=500e7,
                  market_cap_inr=50_000e7)
    assert small.label == "critical"
    assert large.label == "low"
    assert small.material_pct == 0.5
    assert large.material_pct == 0.01


def test_materiality_neutral_when_unknown():
    out = score(category="capex_expansion", deal_value_inr=None,
                market_cap_inr=100e7)
    assert out.label == "medium"
    assert out.material_pct is None


def test_bulk_deal_has_tighter_thresholds():
    # 1% of market cap: bulk_deal treats this as "high" (critical threshold = 2%),
    # capex treats it as "low" (medium threshold = 2%).
    bulk = score(category="bulk_deal", deal_value_inr=100e7,
                 market_cap_inr=10_000e7)
    capex = score(category="capex_expansion", deal_value_inr=100e7,
                  market_cap_inr=10_000e7)
    assert bulk.label in ("high", "critical")
    assert capex.label in ("low", "medium")
    # And: same ratio gives a higher tier under bulk_deal than capex
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    assert rank[bulk.label] > rank[capex.label]
