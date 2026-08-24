from datetime import date

from collectors.nse_api import NseApiClient


class _Response:
    status_code = 200

    def __init__(self, rows):
        self._rows = rows
        self.content = repr(rows).encode()

    def json(self):
        return self._rows


def test_daily_window_collects_coverage_and_real_field_names(monkeypatch):
    client = NseApiClient()
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"])
        return _Response([{
            "symbol": "POWERGRID", "sm_name": "Power Grid Corporation",
            "desc": "General Updates", "attchmntText": "Declared successful bidder",
            "attchmntFile": "https://example.test/loi.pdf",
            "an_dt": "21-Aug-2026 21:35:56", "seq_id": "123", "sm_isin": "INE752E01010",
        }])

    monkeypatch.setattr(client, "_get", fake_get)
    rows, hashes, failures = client.fetch_window_with_coverage(
        date(2026, 8, 20), date(2026, 8, 21)
    )
    assert len(calls) == 2
    assert len(rows) == 2
    assert rows[0].subject == "General Updates"
    assert rows[0].details == "Declared successful bidder"
    assert rows[0].isin == "INE752E01010"
    assert rows[0].seq_no == "123"
    assert len(hashes) == 2
    assert failures == []
