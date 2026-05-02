"""Unit tests for the NSE bulk/block-deal CSV collector."""

from __future__ import annotations

from typing import Any

import pytest

from market_intel.collectors.bulk_block import (
    NseBulkBlockCollector,
    parse_nse_deal_csv,
)


# Realistic snippet of NSE bulk.csv content with the modern header.
SAMPLE_BULK_CSV = """\
BULK DEAL DATA - DAILY
Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks
28-Apr-2026,RELIANCE,Reliance Industries Limited,ICICI PRUDENTIAL MF,BUY,500000,2400.50,-
28-Apr-2026,RELIANCE,Reliance Industries Limited,GOLDMAN SACHS,SELL,250000,2399.75,-
28-Apr-2026,TCS,Tata Consultancy Services,SBI MUTUAL FUND,BUY,100000,3850.10,-
"""

# Block-deal CSV (slightly different header style is tolerated).
SAMPLE_BLOCK_CSV = """\
BLOCK DEAL DATA
Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity,Price,Remarks
28-Apr-2026,INFY,Infosys Limited,LIC,BUY,750000,1610.00,-
"""


def test_parse_bulk_csv_extracts_three_rows():
    rows = parse_nse_deal_csv(SAMPLE_BULK_CSV, deal_kind="bulk")
    assert len(rows) == 3
    rel_buy = next(r for r in rows if r["symbol"] == "RELIANCE" and r["side"] == "BUY")
    assert rel_buy["client_name"] == "ICICI PRUDENTIAL MF"
    assert rel_buy["quantity"] == 500_000
    assert rel_buy["avg_price"] == 2400.50
    assert rel_buy["deal_kind"] == "bulk"
    assert rel_buy["exchange"] == "NSE"
    # 500_000 * 2400.50 / 1e7 = 120.025
    assert rel_buy["deal_value_cr"] == pytest.approx(120.025)


def test_parse_block_csv_handles_alt_header():
    rows = parse_nse_deal_csv(SAMPLE_BLOCK_CSV, deal_kind="block")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "INFY"
    assert rows[0]["deal_kind"] == "block"


def test_parse_empty_csv_returns_empty():
    assert parse_nse_deal_csv("", deal_kind="bulk") == []
    assert parse_nse_deal_csv("   \n", deal_kind="bulk") == []


def test_parse_handles_malformed_quantity():
    csv = (
        "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
        "28-Apr-2026,WIPRO,Wipro,LIC,BUY,N/A,500.00\n"
    )
    rows = parse_nse_deal_csv(csv, deal_kind="bulk")
    assert len(rows) == 1
    assert rows[0]["quantity"] is None
    assert rows[0]["deal_value_cr"] is None


class _FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status


class _FakeHttp:
    """Minimal stand-in for ThrottledHttpClient that returns canned bodies."""

    def __init__(self, responses: dict[str, str]):
        self._responses = responses
        self.calls: list[str] = []
        self._warmed = False

    def warmup(self, force: bool = False) -> None:
        self._warmed = True

    def get_or_raise(self, url: str, **_: Any) -> _FakeResponse:
        self.calls.append(url)
        body = self._responses.get(url, "")
        return _FakeResponse(body)


def test_collector_fetch_all_returns_collector_items():
    http = _FakeHttp({
        "https://nsearchives.nseindia.com/content/equities/bulk.csv": SAMPLE_BULK_CSV,
        "https://nsearchives.nseindia.com/content/equities/block.csv": SAMPLE_BLOCK_CSV,
    })
    collector = NseBulkBlockCollector(http=http)  # type: ignore[arg-type]
    items = list(collector.fetch_all())
    assert len(items) == 4  # 3 bulk + 1 block
    sources = {it.source for it in items}
    assert sources == {"nse_bulk_deal", "nse_block_deal"}
    rel = next(
        it for it in items
        if it.symbol == "RELIANCE" and it.raw_payload["side"] == "BUY"
    )
    assert "ICICI" in rel.title
    assert rel.event_date is not None
    assert rel.raw_payload["deal_kind"] == "bulk"


def test_collector_skips_kind_when_disabled():
    http = _FakeHttp({
        "https://nsearchives.nseindia.com/content/equities/bulk.csv": SAMPLE_BULK_CSV,
    })
    collector = NseBulkBlockCollector(http=http, include_block=False)  # type: ignore[arg-type]
    items = list(collector.fetch_all())
    assert len(items) == 3
    assert all(it.source == "nse_bulk_deal" for it in items)
