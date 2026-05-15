"""NSE PIT / Reg 7(2) insider-trading disclosure collector.

SEBI's Prohibition of Insider Trading (PIT) Regulation 7(2) requires
designated persons (promoters, KMP, directors, immediate relatives) to
disclose transactions in the company's securities to the exchange within two
trading days. NSE publishes these via:

  https://www.nseindia.com/api/corporates-pit?index=equities&from_date=...&to_date=...

Returns one row per disclosed transaction with quantity, value, and pre/post
holding percentages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from collectors.base import BaseCollector, CollectorItem
from collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    TemporaryHttpError,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


PIT_API_URL = "https://www.nseindia.com/api/corporates-pit"
NSE_WARMUP_URLS = (
    "https://www.nseindia.com/",
    "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
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


def _classify_txn_type(value: str | None) -> str:
    """Map raw txn-type strings to one of {'BUY', 'SELL', 'PLEDGE', 'OTHER'}."""
    if not value:
        return "OTHER"
    v = value.strip().lower()
    if "buy" in v or "acqui" in v or "purchase" in v:
        return "BUY"
    if "sell" in v or "dispos" in v or "sale" in v:
        return "SELL"
    if "pledge" in v or "encum" in v:
        return "PLEDGE"
    return "OTHER"


def parse_pit_rows(payload: Any) -> list[CollectorItem]:
    if isinstance(payload, dict):
        rows = payload.get("data") or []
    else:
        rows = payload or []

    items: list[CollectorItem] = []
    for row in rows:
        symbol = (row.get("symbol") or row.get("Symbol") or "").strip() or None
        if not symbol:
            continue
        person = (
            row.get("personName") or row.get("acqName")
            or row.get("nameOfPerson") or ""
        ).strip()
        designation = (row.get("personCategory") or row.get("designation") or "").strip()
        txn_raw = row.get("acqMode") or row.get("buyOrSell") or row.get("typeOfTransaction")
        txn_type = _classify_txn_type(txn_raw)
        qty = _to_float(row.get("securitiesAcquired") or row.get("noOfSecAcq"))
        value = _to_float(row.get("securityValue") or row.get("transactionValue"))
        pre_pct = _to_float(row.get("befAcqSharesPer") or row.get("preHoldingPct"))
        post_pct = _to_float(row.get("afterAcqSharesPer") or row.get("postHoldingPct"))
        txn_date = _parse_dmy(row.get("acquisitionDate") or row.get("dateOfTransaction"))
        disclosed_date = _parse_dmy(row.get("date") or row.get("disclosureDate"))

        title = f"Insider {txn_type.lower()} disclosed for {symbol}: {person or 'unknown'}"
        if qty is not None:
            title += f" ({int(qty):,} shares)"
        if value is not None:
            title += f" ₹{value/1e7:.2f} Cr"
        items.append(
            CollectorItem(
                source="nse_pit",
                source_type="api",
                external_id=str(row.get("id") or row.get("disclosureId") or "") or None,
                symbol=symbol,
                title=title,
                description=(
                    f"Person: {person or 'n/a'} ({designation or 'n/a'}); "
                    f"Mode: {txn_raw or 'n/a'}; "
                    f"Pre: {pre_pct or 0:.2f}% → Post: {post_pct or 0:.2f}%"
                ),
                event_date=txn_date or disclosed_date,
                published_at=disclosed_date or txn_date,
                link=row.get("attchmntFile") or row.get("link"),
                attachment_url=row.get("attchmntFile") or None,
                company_name=(row.get("companyName") or "").strip() or None,
                raw_payload={**row, "_normalized_txn_type": txn_type},
            )
        )
    return items


class NseInsiderCollector(BaseCollector):
    """NSE PIT Reg 7(2) insider-disclosure collector."""

    source_name = "nse_pit"
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
                "Referer": (
                    "https://www.nseindia.com/companies-listing/"
                    "corporate-filings-insider-trading"
                ),
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
            response = self.http.get_or_raise(PIT_API_URL, params=params)
            try:
                return response.json()
            except ValueError as exc:
                raise TemporaryHttpError(f"PIT returned non-JSON: {exc}") from exc

        try:
            payload = fetch_with_retries(_do, label="nse_pit_api")
        except CollectorHttpError as exc:
            logger.warning("PIT fetch failed: %s", exc)
            return []

        items = parse_pit_rows(payload)
        logger.info("Parsed %d PIT disclosures", len(items))
        return items
