"""Unit tests for the NSE PIT insider-trading collector."""

from __future__ import annotations

from typing import Any

from collectors.insider import (
    NseInsiderCollector,
    _classify_txn_type,
    parse_pit_rows,
)


SAMPLE_RESPONSE = {
    "data": [
        {
            "symbol": "RELIANCE",
            "companyName": "Reliance Industries Ltd",
            "personName": "Mukesh D Ambani",
            "personCategory": "Promoter",
            "acqMode": "Market Purchase",
            "securitiesAcquired": "100000",
            "securityValue": "240050000",
            "befAcqSharesPer": "0.05",
            "afterAcqSharesPer": "0.07",
            "acquisitionDate": "27-04-2026",
            "date": "28-04-2026",
        },
        {
            "symbol": "INFY",
            "companyName": "Infosys",
            "personName": "Designated Person A",
            "personCategory": "KMP",
            "acqMode": "Sell",
            "securitiesAcquired": "5000",
            "securityValue": "8050000",
            "befAcqSharesPer": "0.01",
            "afterAcqSharesPer": "0.005",
            "acquisitionDate": "26-04-2026",
            "date": "28-04-2026",
        },
        {
            "symbol": "WIPRO",
            "personName": "Pledger X",
            "acqMode": "Pledge created",
            "securitiesAcquired": "1000000",
            "date": "28-04-2026",
        },
    ]
}


def test_classify_txn_type():
    assert _classify_txn_type("Market Purchase") == "BUY"
    assert _classify_txn_type("Sell") == "SELL"
    assert _classify_txn_type("Pledge created") == "PLEDGE"
    assert _classify_txn_type("Bonus") == "OTHER"
    assert _classify_txn_type(None) == "OTHER"


def test_parse_extracts_three_rows():
    items = parse_pit_rows(SAMPLE_RESPONSE)
    assert len(items) == 3
    rel = items[0]
    assert rel.symbol == "RELIANCE"
    assert "Mukesh" in rel.title
    assert rel.raw_payload["_normalized_txn_type"] == "BUY"


def test_parse_classifies_sell_correctly():
    items = parse_pit_rows(SAMPLE_RESPONSE)
    infy = items[1]
    assert infy.raw_payload["_normalized_txn_type"] == "SELL"
    assert "sell" in infy.title.lower()


def test_parse_classifies_pledge():
    items = parse_pit_rows(SAMPLE_RESPONSE)
    wipro = items[2]
    assert wipro.raw_payload["_normalized_txn_type"] == "PLEDGE"


def test_parse_empty():
    assert parse_pit_rows({"data": []}) == []
    assert parse_pit_rows([]) == []


class _FakeResponse:
    def __init__(self, payload: Any):
        self._payload = payload
        self.status_code = 200

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


def test_collector_fetches_and_parses():
    http = _FakeHttp(SAMPLE_RESPONSE)
    collector = NseInsiderCollector(http=http)  # type: ignore[arg-type]
    items = list(collector.fetch_all())
    assert len(items) == 3
    assert all(it.source == "nse_pit" for it in items)
