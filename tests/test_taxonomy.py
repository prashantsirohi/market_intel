from market_intel.processing.taxonomy import (
    TIER_A,
    TIER_B,
    category_importance,
    category_tier,
    is_ignored,
)


def test_new_categories_have_tiers():
    for cat in ("demerger", "block_deal", "sast_filing", "rating_downgrade"):
        assert category_tier(cat) == "A", cat
    for cat in ("bulk_deal", "insider_buy", "insider_sell", "rating_upgrade"):
        assert category_tier(cat) == "B", cat


def test_new_categories_have_importance_scores():
    for cat in ("demerger", "bulk_deal", "block_deal", "sast_filing",
                "insider_buy", "insider_sell", "rating_upgrade", "rating_downgrade"):
        score = category_importance(cat)
        assert 5.0 < score < 10.0, f"{cat} importance {score} out of expected range"


def test_demerger_outranks_buyback():
    assert category_importance("demerger") >= category_importance("buyback")


def test_block_deal_outranks_bulk_deal():
    assert category_importance("block_deal") > category_importance("bulk_deal")


def test_existing_taxonomy_preserved():
    assert "capex_expansion" in TIER_A
    assert "results" in TIER_B
    assert is_ignored("nav_update")
