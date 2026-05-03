"""NSE SAST (Substantial Acquisition of Shares & Takeovers) collector.

SEBI Regulation 29 (under the SAST Regulations, 2011) requires acquirers to
disclose substantial acquisitions or disposals of shares to the exchange.
NSE publishes these on a JSON-backed page:

  https://www.nseindia.com/api/corporate-sast-reg29?index=equities&from_date=...&to_date=...

Returns a list of acquirer-disclosure rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from market_intel.collectors.base import BaseCollector, CollectorItem
from market_intel.collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    TemporaryHttpError,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


SAST_PAGE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-regulation-29"
SAST_API_URL = "https://www.nseindia.com/api/corporate-sast-reg29"
NSE_WARMUP_URLS = (
    "https://www.nseindia.com/",
    SAST_PAGE_URL,
)


def _fmt_dmy(d: datetime) -> str:
    return d.strftime("%d-%m-%Y")


def _parse_dmy(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_sast_rows(payload: Any) -> list[CollectorItem]:
    """Accepts either a list-of-rows or a dict with a 'data' key."""
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("Data") or []
    else:
        rows = payload or []

    items: list[CollectorItem] = []
    for row in rows:
        symbol = (row.get("symbol") or row.get("Symbol") or "").strip() or None
        if not symbol:
            continue
        acquirer = (row.get("acqName") or row.get("acquirerName") or row.get("name") or "").strip()
        regulation = (row.get("regulation") or row.get("regNo") or "").strip()
        txn_type = (row.get("typeOfTransaction") or row.get("acqMode") or "").strip()
        pre_pct = _to_float(row.get("befAcqSharesPer") or row.get("prePct"))
        post_pct = _to_float(row.get("afterAcqSharesPer") or row.get("postPct"))
        qty = _to_float(row.get("noOfShareAcq") or row.get("noOfShare"))
        date_field = (
            row.get("date") or row.get("disclosureDate")
            or row.get("recievedDate") or row.get("acqDate")
        )
        published = _parse_dmy(date_field)
        title = (
            f"SAST {regulation or 'Reg 29'} disclosure for {symbol}: "
            f"{acquirer or 'unknown acquirer'}"
        )
        if pre_pct is not None and post_pct is not None:
            title += f" ({pre_pct:.2f}% → {post_pct:.2f}%)"
        items.append(
            CollectorItem(
                source="nse_sast",
                source_type="api",
                external_id=str(row.get("id") or row.get("disclosureId") or "") or None,
                symbol=symbol,
                title=title,
                description=(
                    f"Acquirer: {acquirer}; Regulation: {regulation or 'n/a'}; "
                    f"Mode: {txn_type or 'n/a'}; Shares: {int(qty) if qty else '?'}"
                ),
                event_date=published,
                published_at=published,
                link=row.get("attchmntFile") or row.get("link"),
                attachment_url=row.get("attchmntFile") or None,
                company_name=(row.get("companyName") or "").strip() or None,
                raw_payload=row,
            )
        )
    return items


class NseSastCollector(BaseCollector):
    """NSE SAST disclosure collector."""

    source_name = "nse_sast"
    source_type = "api"

    def __init__(
        self,
        *,
        http: ThrottledHttpClient | None = None,
        lookback_days: int = 7,
    ):
        self.http = http or ThrottledHttpClient(
            warmup_urls=NSE_WARMUP_URLS,
            extra_headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": SAST_PAGE_URL,
            },
        )
        self.lookback_days = lookback_days

    def fetch_all(self) -> Iterable[CollectorItem]:
        today = datetime.now(timezone.utc)
        params = {
            "index": "equities",
            "from_date": _fmt_dmy(today - timedelta(days=self.lookback_days)),
            "to_date": _fmt_dmy(today),
        }

        def _do(attempt: int) -> Any:
            if attempt > 1:
                self.http.warmup(force=True)
            else:
                self.http.warmup()
            response = self.http.get_or_raise(SAST_API_URL, params=params)
            try:
                return response.json()
            except ValueError as exc:
                raise TemporaryHttpError(f"SAST returned non-JSON: {exc}") from exc

        try:
            payload = fetch_with_retries(_do, label="nse_sast_api")
        except CollectorHttpError as exc:
            logger.warning("SAST fetch failed: %s", exc)
            return []

        items = parse_sast_rows(payload)
        logger.info("Parsed %d SAST disclosures", len(items))
        return items
