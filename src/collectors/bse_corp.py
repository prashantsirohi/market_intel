"""BSE corporate-announcements collector.

Source
------
BSE publishes corporate announcements via a paginated JSON endpoint:

  https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
    ?pageno=1&strCat=-1&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD
    &strScrip=&strSearch=P&strType=C&subcategory=-1

Returns ``{"Table": [...announcements...], "Table1": [{"ROWCNT": ...}]}``.

This collector mirrors ``NseRssClient`` but for BSE-listed scrips, plugging
the gap where some companies are BSE-only or BSE-faster than NSE.
"""

from __future__ import annotations

import logging
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from collectors.base import BaseCollector, CollectorItem
from collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


BSE_API_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
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
        # SCRIP_CD is a BSE numeric code (int); cast to str before strip
        symbol = str(row.get("SCRIP_CD") or row.get("SCRIPCD") or "").strip() or None
        title = str(row.get("SUBCATNAME") or row.get("HEADLINE") or row.get("NEWSSUB") or "").strip()
        if not title:
            continue
        detail_parts = [
            str(row.get("HEADLINE") or "").strip(),
            str(row.get("MORE") or row.get("NEWSBODY") or "").strip(),
        ]
        description = " ".join(part for part in detail_parts if part and part != title) or None
        published = _parse_news_dt(row.get("NEWS_DT") or row.get("DT_TM"))
        attach = row.get("ATTACHMENTNAME") or row.get("ATTACHMENT")
        link = _build_link(row)
        items.append(
            CollectorItem(
                source="bse_corp",
                source_type="api",
                external_id=str(row.get("NEWSID") or "") or None,
                symbol=symbol,
                title=title,
                description=description,
                event_date=published,
                published_at=published,
                link=link,
                attachment_url=f"{BSE_PDF_BASE}{attach}" if attach else None,
                company_name=str(row.get("SLONGNAME") or "").strip() or None,
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
        self.last_response_hashes: list[str] = []
        self.last_failures: list[dict[str, str]] = []
        self.last_page_count = 0
        self.last_pages_complete = False

    @property
    def session(self):
        """Expose the underlying HTTP session for PDF downloads."""
        return self.http.session

    def fetch_all(self) -> Iterable[CollectorItem]:
        today = datetime.now(timezone.utc).date()
        from_d = today - timedelta(days=self.lookback_days)
        return self.fetch_window(from_d, today)

    def fetch_window(self, from_date: date, to_date: date) -> list[CollectorItem]:
        if from_date > to_date:
            raise ValueError("from_date must not be after to_date")
        self.last_response_hashes = []
        self.last_failures = []
        self.last_page_count = 0
        self.last_pages_complete = False
        items: list[CollectorItem] = []
        requested_date = from_date
        completed_dates = 0
        while requested_date <= to_date:
            page_number = 1
            total_pages: int | None = None
            date_failed = False
            while total_pages is None or page_number <= total_pages:
                params = {
                    "pageno": page_number,
                    "strCat": "-1",
                    "strPrevDate": _fmt_bse_date(datetime.combine(requested_date, datetime.min.time())),
                    "strToDate": _fmt_bse_date(datetime.combine(requested_date, datetime.min.time())),
                    "strScrip": "",
                    "strSearch": "P",
                    "strType": "C",
                    "subcategory": "-1",
                }

                def _do(attempt: int) -> dict[str, Any]:
                    if attempt > 1:
                        self.http.warmup(force=True)
                    else:
                        self.http.warmup()
                    response = self.http.get_or_raise(BSE_API_URL, params=params)
                    try:
                        payload = response.json()
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        if not isinstance(payload, dict):
                            raise ValueError(f"expected object, got {type(payload).__name__}")
                        if not isinstance(payload.get("Table"), list) or not isinstance(payload.get("Table1"), list):
                            raise ValueError("missing Table/Table1 response contract")
                        return payload
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        from collectors.http_utils import TemporaryHttpError
                        raise TemporaryHttpError(f"BSE returned invalid JSON payload: {exc}") from exc

                try:
                    payload = fetch_with_retries(
                        _do,
                        label=f"bse_corp_api_{requested_date}_page_{page_number}",
                    )
                except CollectorHttpError as exc:
                    logger.warning("BSE corp fetch failed for %s page %d: %s", requested_date, page_number, exc)
                    self.last_failures.append({
                        "window": f"{requested_date}/{requested_date}",
                        "page": str(page_number),
                        "error": str(exc),
                    })
                    date_failed = True
                    break

                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                page_hash = hashlib.sha256(canonical).hexdigest()
                if page_hash in self.last_response_hashes:
                    self.last_failures.append({
                        "window": f"{requested_date}/{requested_date}",
                        "page": str(page_number),
                        "error": "BSE repeated a prior response page",
                    })
                    date_failed = True
                    break
                self.last_response_hashes.append(page_hash)
                self.last_page_count += 1
                page_items = parse_bse_announcements(payload)
                items.extend(page_items)
                total_row = (payload.get("Table1") or [{}])[0]
                total_count = int(total_row.get("ROWCNT") or len(page_items))
                first_announcement = (payload.get("Table") or [{}])[0]
                reported_pages = int(first_announcement.get("TotalPageCnt") or 0)
                total_pages = reported_pages or max(1, (total_count + 49) // 50)
                page_number += 1

            if not date_failed and total_pages is not None and page_number > total_pages:
                completed_dates += 1
            requested_date += timedelta(days=1)

        requested_date_count = (to_date - from_date).days + 1
        self.last_pages_complete = not self.last_failures and completed_dates == requested_date_count
        logger.info("Parsed %d BSE announcements", len(items))
        return items
