"""Unit tests for the NSE SAST collector."""

from __future__ import annotations

from typing import Any

from market_intel.collectors.sast import (
    NseSastCollector,
    parse_sast_rows,
)


SAMPLE_RESPONSE = {
    "data": [
        {
            "symbol": "RELIANCE",
            "companyName": "Reliance Industries Ltd",
            "acqName": "ABC Family Trust",
            "regulation": "Reg 29(2)",
            "typeOfTransaction": "Market Purchase",
            "befAcqSharesPer": "4.95",
            "afterAcqSharesPer": "5.20",
            "noOfShareAcq": "1500000",
            "date": "28-04-2026",
            "attchmntFile": "https://archives.nseindia.com/abc.pdf",
        },
        {
            # Missing symbol -> should be skipped
            "symbol": "",
            "acqName": "Unknown",
        },
        {
            "symbol": "TCS",
            "companyName": "Tata Consultancy Services",
            "acqName": "XYZ Holdings",
            "regulation": "Reg 29(1)",
            "befAcqSharesPer": "2.10",
            "afterAcqSharesPer": "5.05",
            "date": "27-04-2026",
        },
    ]
}


def test_parse_extracts_two_rows_with_symbol():
    items = parse_sast_rows(SAMPLE_RESPONSE)
    assert len(items) == 2
    assert items[0].symbol == "RELIANCE"
    assert "ABC Family Trust" in items[0].title
    assert items[0].event_date is not None
    assert items[0].raw_payload["regulation"] == "Reg 29(2)"


def test_parse_includes_pct_progression_in_title():
    items = parse_sast_rows(SAMPLE_RESPONSE)
    rel = items[0]
    assert "4.95" in rel.title and "5.20" in rel.title


def test_parse_accepts_list_payload():
    items = parse_sast_rows(SAMPLE_RESPONSE["data"])
    assert len(items) == 2


def test_parse_empty_payload():
    assert parse_sast_rows({}) == []
    assert parse_sast_rows([]) == []
    assert parse_sast_rows(None) == []


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload


class _FakeHttp:
    def __init__(self, payload: Any):
        self._payload = payload
        self.calls: list[tuple[str, dict | None]] = []

    def warmup(self, force: bool = False) -> None:
        pass

    def get_or_raise(self, url: str, params: dict | None = None, **_: Any) -> _FakeResponse:
        self.calls.append((url, params))
        return _FakeResponse(self._payload)


def test_collector_sends_date_range_params():
    http = _FakeHttp(SAMPLE_RESPONSE)
    collector = NseSastCollector(http=http, lookback_days=14)  # type: ignore[arg-type]
    items = list(collector.fetch_all())
    assert len(items) == 2
    assert http.calls
    params = http.calls[0][1]
    assert params is not None
    assert "from_date" in params and "to_date" in params
    assert params["index"] == "equities"
