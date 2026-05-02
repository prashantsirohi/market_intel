from market_intel.processing.classifier import classify_category, classify_event


def test_demerger_classified_correctly():
    assert classify_category(
        "Scheme of demerger: Demerger of FMCG business approved"
    ) == "demerger"


def test_bulk_deal_classified():
    assert classify_category("Bulk deal data for 28-Apr-2026") == "bulk_deal"


def test_block_deal_outranks_bulk():
    # When both keywords appear, block_deal sits earlier in priority list
    assert classify_category("Block deal window summary, also bulk deal") == "block_deal"


def test_sast_classified():
    assert classify_category(
        "Disclosure under Regulation 29 of SAST Regulations"
    ) == "sast_filing"


def test_rating_downgrade_classified():
    out = classify_event("CRISIL rating downgrade to A+ (negative outlook)")
    assert out["primary_category"] == "rating_downgrade"
    assert out["event_tier"] == "A"


def test_capex_unchanged():
    """Regression: existing classification still works after taxonomy edits."""
    assert classify_category(
        "Capex announcement: new manufacturing facility at Pune"
    ) == "capex_expansion"
