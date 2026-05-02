"""BSE corporate-announcements collector.

Source
------
BSE publishes corporate announcements via a JSON endpoint:

  https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w
    ?strCat=-1&strPrevDate=DD/MM/YYYY&strToDate=DD/MM/YYYY
    &strScrip=&strSearch=P&strType=C

Returns ``{"Table": [...announcements...], "Table1": [...categories...]}``.

This collector mirrors ``NseRssClient`` but for BSE-listed scrips, plugging
the gap where some companies are BSE-only or BSE-faster than NSE.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from market_intel.collectors.base import BaseCollector, CollectorItem
from market_intel.collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
BSE_PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
BSE_WARMUP_URLS = (
    "https://www.bseindia.com/",
    "https://www.bseindia.com/corporates/ann.html",
)


def _fmt_bse_date(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _parse_news_dt(value: str | None) -> datetime | None:
    """BSE returns timestamps like '2026-04-28T14:30:00' or 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return None
    value = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _build_link(row: dict[str, Any]) -> str | None:
    attach = row.get("ATTACHMENTNAME") or row.get("ATTACHMENT")
    if attach:
        return f"{BSE_PDF_BASE}{attach}"
    news_id = row.get("NEWSID")
    if news_id:
        return f"https://www.bseindia.com/corporates/anndet_new.aspx?newsid={news_id}"
    return None


def parse_bse_announcements(payload: dict[str, Any]) -> list[CollectorItem]:
    rows = payload.get("Table") or []
    items: list[CollectorItem] = []
    for row in rows:
        symbol = (row.get("SCRIP_CD") or row.get("SCRIPCD") or "").strip() or None
        # SCRIP_CD is BSE numeric code; we try to also pull NSE-style ticker
        ticker = (row.get("SCRIPCDISIN") or row.get("SLONGNAME") or "").strip() or None
        title = (row.get("HEADLINE") or row.get("NEWSSUB") or "").strip()
        if not title:
            continue
        description = (row.get("MORE") or row.get("NEWSBODY") or "").strip() or None
        published = _parse_news_dt(row.get("NEWS_DT") or row.get("DT_TM"))
        attach = row.get("ATTACHMENTNAME") or row.get("ATTACHMENT")
        link = _build_link(row)
        items.append(
            CollectorItem(
                source="bse_corp",
                source_type="api",
                external_id=str(row.get("NEWSID") or "") or None,
                symbol=ticker or symbol,
                title=title,
                description=description,
                event_date=published,
                published_at=published,
                link=link,
                attachment_url=f"{BSE_PDF_BASE}{attach}" if attach else None,
                company_name=(row.get("SLONGNAME") or "").strip() or None,
                raw_payload=row,
            )
        )
    return items


class BseCorporateCollector(BaseCollector):
    """BSE corporate-announcement JSON-API collector."""

    source_name = "bse_corp"
    source_type = "api"

    def __init__(
        self,
        *,
        http: ThrottledHttpClient | None = None,
        lookback_days: int = 1,
    ):
        self.http = http or ThrottledHttpClient(
            warmup_urls=BSE_WARMUP_URLS,
            extra_headers={
                "Accept": "application/json,text/plain,*/*",
                "Origin": "https://www.bseindia.com",
                "Referer": "https://www.bseindia.com/corporates/ann.html",
            },
        )
        self.lookback_days = lookback_days

    def fetch_all(self) -> Iterable[CollectorItem]:
        today = datetime.now(timezone.utc).date()
        from_d = today - timedelta(days=self.lookback_days)
        params = {
            "strCat": "-1",
            "strPrevDate": _fmt_bse_date(datetime.combine(from_d, datetime.min.time())),
            "strToDate": _fmt_bse_date(datetime.combine(today, datetime.min.time())),
            "strScrip": "",
            "strSearch": "P",
            "strType": "C",
        }

        def _do(attempt: int) -> dict[str, Any]:
            if attempt > 1:
                self.http.warmup(force=True)
            else:
                self.http.warmup()
            response = self.http.get_or_raise(BSE_API_URL, params=params)
            try:
                return response.json()
            except ValueError as exc:
                from market_intel.collectors.http_utils import TemporaryHttpError
                raise TemporaryHttpError(f"BSE returned non-JSON: {exc}") from exc

        try:
            payload = fetch_with_retries(_do, label="bse_corp_api")
        except CollectorHttpError as exc:
            logger.warning("BSE corp fetch failed: %s", exc)
            return []

        items = parse_bse_announcements(payload)
        logger.info("Parsed %d BSE announcements", len(items))
        return items
