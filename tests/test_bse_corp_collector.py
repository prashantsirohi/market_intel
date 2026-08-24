"""Unit tests for the BSE corporate-announcement collector."""

from __future__ import annotations

from datetime import date
from typing import Any

from collectors.bse_corp import (
    BseCorporateCollector,
    parse_bse_announcements,
)


SAMPLE_PAYLOAD = {
    "Table": [
        {
            "NEWSID": "abc-123",
            "SCRIP_CD": "500325",
            "SCRIPCDISIN": "RELIANCE",
            "SLONGNAME": "Reliance Industries Ltd",
            "HEADLINE": "Outcome of Board Meeting - Capex announcement",
            "MORE": "The Board approved capex of Rs. 15,000 crore for Jamnagar.",
            "NEWS_DT": "2026-04-28T14:30:00",
            "ATTACHMENTNAME": "abc-123.pdf",
        },
        {
            "NEWSID": "def-456",
            "SCRIP_CD": "532540",
            "SCRIPCDISIN": "TCS",
            "SLONGNAME": "Tata Consultancy Services",
            "HEADLINE": "Buyback approval",
            "MORE": "Board approved buyback of equity shares.",
            "NEWS_DT": "2026-04-28 13:15:00",
        },
        # Should be skipped (no headline)
        {"NEWSID": "ghi-789", "SCRIP_CD": "0", "HEADLINE": ""},
    ],
    "Table1": [{"ROWCNT": 2}],
}


def test_parse_extracts_two_announcements():
    items = parse_bse_announcements(SAMPLE_PAYLOAD)
    assert len(items) == 2
    rel = items[0]
    assert rel.symbol == "500325"
    assert "Capex" in rel.title
    assert rel.attachment_url is not None
    assert "abc-123.pdf" in rel.attachment_url
    assert rel.event_date is not None
    assert rel.raw_payload["NEWSID"] == "abc-123"


def test_parse_handles_alt_datetime_format():
    items = parse_bse_announcements(SAMPLE_PAYLOAD)
    tcs = items[1]
    assert tcs.symbol == "532540"
    assert tcs.published_at is not None


def test_parse_skips_blank_headlines():
    items = parse_bse_announcements(SAMPLE_PAYLOAD)
    assert all(it.title for it in items)
    assert "ghi-789" not in {it.external_id for it in items}


def test_parse_empty_payload():
    assert parse_bse_announcements({}) == []
    assert parse_bse_announcements({"Table": []}) == []


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


def test_collector_accepts_double_encoded_json():
    import json

    http = _FakeHttp(json.dumps(SAMPLE_PAYLOAD))
    items = BseCorporateCollector(http=http).fetch_window(date(2026, 8, 21), date(2026, 8, 21))  # type: ignore[arg-type]
    assert len(items) == 2


def test_collector_fetch_all():
    http = _FakeHttp(SAMPLE_PAYLOAD)
    collector = BseCorporateCollector(http=http)  # type: ignore[arg-type]
    items = collector.fetch_window(date(2026, 8, 21), date(2026, 8, 21))
    assert len(items) == 2
    assert {it.source for it in items} == {"bse_corp"}
    # Confirm the date-range params were sent
    assert http.calls
    sent_params = http.calls[0][1]
    assert sent_params is not None
    assert "strPrevDate" in sent_params and "strToDate" in sent_params
    assert sent_params["pageno"] == 1
    assert sent_params["subcategory"] == "-1"


class _PagedHttp(_FakeHttp):
    def get_or_raise(self, url: str, params: dict | None = None, **_: Any) -> _FakeResponse:
        assert params is not None
        self.calls.append((url, params))
        page = int(params["pageno"])
        row = dict(SAMPLE_PAYLOAD["Table"][0])
        row["NEWSID"] = f"page-{page}"
        row["TotalPageCnt"] = 2
        return _FakeResponse({"Table": [row], "Table1": [{"ROWCNT": 2}]})


def test_collector_fetches_every_reported_page():
    http = _PagedHttp({})
    collector = BseCorporateCollector(http=http)  # type: ignore[arg-type]
    items = collector.fetch_window(date(2026, 8, 21), date(2026, 8, 21))
    assert len(items) == 2
    assert [call[1]["pageno"] for call in http.calls] == [1, 2]
    assert collector.last_page_count == 2
    assert collector.last_pages_complete is True
    assert collector.last_failures == []


class _DailyHttp(_FakeHttp):
    def get_or_raise(self, url: str, params: dict | None = None, **_: Any) -> _FakeResponse:
        assert params is not None
        self.calls.append((url, params))
        requested_date = params["strPrevDate"]
        assert params["strToDate"] == requested_date
        row = dict(SAMPLE_PAYLOAD["Table"][0])
        row["NEWSID"] = f"news-{requested_date}"
        row["TotalPageCnt"] = 1
        return _FakeResponse({"Table": [row], "Table1": [{"ROWCNT": 1}]})


def test_collector_splits_multi_day_window_into_daily_requests():
    http = _DailyHttp({})
    collector = BseCorporateCollector(http=http)  # type: ignore[arg-type]
    items = collector.fetch_window(date(2026, 8, 19), date(2026, 8, 21))

    assert len(items) == 3
    assert [call[1]["strPrevDate"] for call in http.calls] == ["20260819", "20260820", "20260821"]
    assert collector.last_page_count == 3
    assert collector.last_pages_complete is True
