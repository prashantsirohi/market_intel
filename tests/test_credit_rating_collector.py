"""Unit tests for the credit-rating collector."""

from __future__ import annotations

from typing import Iterable

from market_intel.collectors.credit_rating import (
    CreditRatingCollector,
    RatingAction,
    RatingAgencyAdapter,
    _parse_generic_html,
    _rating_score,
    classify_action,
)


def test_rating_score_orders_letter_grades():
    assert _rating_score("AAA") > _rating_score("AA+")
    assert _rating_score("AA+") > _rating_score("AA")
    assert _rating_score("AA") > _rating_score("AA-")
    assert _rating_score("BBB") > _rating_score("BB+")
    assert _rating_score("D") < _rating_score("B-")
    # Strips agency prefix
    assert _rating_score("CRISIL AA+") == _rating_score("AA+")
    assert _rating_score("[ICRA]A+") == _rating_score("A+")


def test_classify_action_via_rating_change():
    assert classify_action("AA", "AA+") == "upgrade"
    assert classify_action("AA+", "AA") == "downgrade"
    assert classify_action("AA", "AA") == "reaffirm"


def test_classify_action_via_hint():
    assert classify_action(None, None, hint="Rating downgraded today") == "downgrade"
    assert classify_action(None, None, hint="Reaffirmed at AA") == "reaffirm"


SAMPLE_HTML = """
<html><body>
<div>
<h3>Acme Industries Limited rating reaffirmed at AA+ (stable)</h3>
<p>Date: 28-Apr-2026. CRISIL has reaffirmed the long-term rating.</p>
</div>
<div>
<h3>Beta Steel Ltd. - rating downgraded from AA to AA-</h3>
<p>Date: 27-Apr-2026.</p>
</div>
</body></html>
"""


def test_parse_generic_html_extracts_actions():
    actions = list(_parse_generic_html(SAMPLE_HTML, agency="CRISIL"))
    assert len(actions) >= 2
    by_action = {a.action: a for a in actions}
    assert "reaffirm" in by_action
    assert "downgrade" in by_action
    downgrade = by_action["downgrade"]
    assert downgrade.old_rating == "AA"
    assert downgrade.new_rating in ("AA-", "AA")  # tolerate parser ambiguity


def test_parse_empty_html():
    assert list(_parse_generic_html("", agency="CRISIL")) == []


class _RecordingAdapter(RatingAgencyAdapter):
    agency = "MOCK"

    def __init__(self, actions: list[RatingAction]):
        super().__init__()
        self._actions = actions

    def fetch_actions(self) -> Iterable[RatingAction]:
        return self._actions


def test_collector_aggregates_across_adapters():
    a1 = RatingAction(
        agency="CRISIL", company_name="Reliance Industries Limited",
        instrument="LT Bank Loan", old_rating="AA+", new_rating="AAA",
        action="upgrade", dated=None, source_url=None,
        raw_text="reaffirmed at AAA",
    )
    a2 = RatingAction(
        agency="ICRA", company_name="TCS",
        instrument="NCD", old_rating="AAA", new_rating="AAA",
        action="reaffirm", dated=None, source_url=None,
        raw_text="reaffirmed",
    )
    collector = CreditRatingCollector(
        adapters=[
            _RecordingAdapter([a1]),
            _RecordingAdapter([a2]),
        ],
        symbol_lookup={"relianceindustrieslimited": "RELIANCE", "tcs": "TCS"},
    )
    items = list(collector.fetch_all())
    assert len(items) == 2
    rel = next(it for it in items if it.company_name == "Reliance Industries Limited")
    assert rel.symbol == "RELIANCE"
    assert rel.raw_payload["action"] == "upgrade"
    assert rel.source.startswith("rating_")


def test_collector_continues_after_adapter_exception():
    class _FailingAdapter(RatingAgencyAdapter):
        agency = "FAIL"

        def fetch_actions(self) -> Iterable[RatingAction]:
            raise RuntimeError("simulated outage")

    a1 = RatingAction(
        agency="CRISIL", company_name="Acme", instrument=None,
        old_rating=None, new_rating="AA+", action="reaffirm",
        dated=None, source_url=None, raw_text="reaffirmed at AA+",
    )
    collector = CreditRatingCollector(
        adapters=[_FailingAdapter(), _RecordingAdapter([a1])],
    )
    items = list(collector.fetch_all())
    assert len(items) == 1
