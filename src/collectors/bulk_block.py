"""NSE / BSE bulk and block deal collector.

Sources
-------
- NSE bulk deals: https://nsearchives.nseindia.com/content/equities/bulk.csv
- NSE block deals: https://nsearchives.nseindia.com/content/equities/block.csv
- NSE historical API:
  https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from=DD-MM-YYYY&to=DD-MM-YYYY
- BSE bulk: https://api.bseindia.com/BseIndiaAPI/api/BulkDeals/w?Fdate=YYYYMMDD&Tdate=YYYYMMDD
- BSE block: https://api.bseindia.com/BseIndiaAPI/api/BlockDeals/w?Fdate=YYYYMMDD&Tdate=YYYYMMDD

Output
------
``CollectorItem`` rows with category-style markers in ``raw_payload``:
  - ``raw_payload["deal_kind"]`` ∈ {"bulk", "block"}
  - ``raw_payload["exchange"]`` ∈ {"NSE", "BSE"}
  - ``raw_payload["side"]`` ∈ {"BUY", "SELL"}
  - ``raw_payload["client_name"]``, ``quantity``, ``avg_price``, ``deal_value_cr``

Repository writers translate these into the ``bulk_deal`` table as well as
producing a synthetic ``raw_event`` whose ``primary_category`` is
``bulk_deal`` or ``block_deal`` for taxonomy joins.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Iterable, Iterator

from collectors.base import BaseCollector, CollectorItem
from collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


NSE_BULK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
NSE_BLOCK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
NSE_WARMUP_URLS = (
    "https://www.nseindia.com/",
    "https://www.nseindia.com/market-data/large-deals",
)


def _parse_indian_decimal(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_quantity(value: str | None) -> int | None:
    f = _parse_indian_decimal(value)
    return int(f) if f is not None else None


def _parse_trade_date(value: str | None) -> datetime | None:
    """NSE CSV uses dd-MMM-yyyy or dd-MM-yyyy."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _normalize_side(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    v = value.strip().upper()
    if v.startswith("B") or v == "BUY":
        return "BUY"
    if v.startswith("S") or v == "SELL":
        return "SELL"
    return "UNKNOWN"


# Canonical column names we look for. NSE has shifted these over the years; we
# match case-insensitively and tolerate spaces / abbreviations.
_COL_ALIASES = {
    "trade_date": ["date", "deal date", "trade date", "tradedate"],
    "symbol": ["symbol", "security in nse", "scrip code"],
    "security_name": ["security name", "name of the security", "symbol description"],
    "client_name": ["client name", "name of client", "client"],
    "side": ["buy/sell", "buy / sell", "deal type"],
    "quantity": [
        "quantity traded", "quantity", "qty traded", "no. of shares", "qty",
    ],
    "price": [
        "trade price / wght. avg. price",
        "trade price",
        "wght. avg. price",
        "weighted average price",
        "avg price",
        "price",
    ],
    "remarks": ["remarks"],
}


def _build_column_index(header: list[str]) -> dict[str, int]:
    """Map canonical column → index, using fuzzy lowercase matching."""
    lookup: dict[str, int] = {}
    lowered = [h.strip().lower() for h in header]
    for canonical, aliases in _COL_ALIASES.items():
        for alias in aliases:
            try:
                lookup[canonical] = lowered.index(alias)
                break
            except ValueError:
                continue
    return lookup


def parse_nse_deal_csv(text: str, *, deal_kind: str) -> list[dict]:
    """Parse the NSE bulk.csv / block.csv format into raw row dicts.

    Robust to the format variations seen in archive vs report CSVs.
    """
    if not text or not text.strip():
        return []
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(cell.strip() for cell in r)]
    if not rows:
        return []

    # First non-empty row is the header. Some CSVs have a one-line preamble
    # (e.g. "BULK DEAL DATA") above the header — skip until we find a row
    # containing "symbol" or "scrip code".
    header_idx = 0
    for idx, row in enumerate(rows[:3]):
        joined = ",".join(c.lower() for c in row)
        if "symbol" in joined or "scrip" in joined:
            header_idx = idx
            break
    header = rows[header_idx]
    cols = _build_column_index(header)
    out: list[dict] = []
    for row in rows[header_idx + 1:]:
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        try:
            symbol = row[cols["symbol"]].strip().upper() if "symbol" in cols else ""
        except IndexError:
            continue
        if not symbol:
            continue
        qty = _parse_quantity(row[cols["quantity"]]) if "quantity" in cols else None
        price = _parse_indian_decimal(row[cols["price"]]) if "price" in cols else None
        side = _normalize_side(row[cols["side"]]) if "side" in cols else "UNKNOWN"
        deal_value_cr = (
            (qty * price / 1e7) if (qty is not None and price is not None) else None
        )
        out.append({
            "deal_kind": deal_kind,
            "exchange": "NSE",
            "trade_date": _parse_trade_date(
                row[cols["trade_date"]] if "trade_date" in cols else None
            ),
            "symbol": symbol,
            "security_name": (
                row[cols["security_name"]].strip()
                if "security_name" in cols and cols["security_name"] < len(row)
                else None
            ),
            "client_name": (
                row[cols["client_name"]].strip()
                if "client_name" in cols and cols["client_name"] < len(row)
                else None
            ),
            "side": side,
            "quantity": qty,
            "avg_price": price,
            "deal_value_cr": deal_value_cr,
            "remarks": (
                row[cols["remarks"]].strip()
                if "remarks" in cols and cols["remarks"] < len(row)
                else None
            ),
        })
    return out


def _row_to_collector_item(row: dict) -> CollectorItem:
    title = (
        f"{row['deal_kind'].title()} deal: "
        f"{row['side']} {row.get('quantity') or '?'} {row['symbol']}"
    )
    if row.get("client_name"):
        title += f" by {row['client_name']}"
    if row.get("deal_value_cr") is not None:
        title += f" (₹{row['deal_value_cr']:.1f} Cr)"
    description = (
        f"{row['exchange']} {row['deal_kind']} deal on "
        f"{row['trade_date'].date().isoformat() if row.get('trade_date') else 'unknown date'}"
    )
    if row.get("avg_price") is not None:
        description += f" at avg price ₹{row['avg_price']:.2f}"
    return CollectorItem(
        source=f"{row['exchange'].lower()}_{row['deal_kind']}_deal",
        source_type="csv",
        external_id=None,
        symbol=row.get("symbol"),
        title=title,
        description=description,
        event_date=row.get("trade_date"),
        published_at=row.get("trade_date"),
        link=NSE_BULK_CSV_URL if row["deal_kind"] == "bulk" else NSE_BLOCK_CSV_URL,
        company_name=row.get("security_name"),
        raw_payload=row,
    )


class NseBulkBlockCollector(BaseCollector):
    """Daily NSE bulk + block deal CSV collector."""

    source_name = "nse_bulk_block"
    source_type = "csv"

    def __init__(
        self,
        *,
        http: ThrottledHttpClient | None = None,
        include_bulk: bool = True,
        include_block: bool = True,
    ):
        self.http = http or ThrottledHttpClient(
            warmup_urls=NSE_WARMUP_URLS,
            extra_headers={
                "Referer": "https://www.nseindia.com/market-data/large-deals",
                "Accept": "text/csv,application/csv,*/*;q=0.8",
            },
        )
        self.include_bulk = include_bulk
        self.include_block = include_block

    def fetch_all(self) -> Iterable[CollectorItem]:
        items: list[CollectorItem] = []
        if self.include_bulk:
            items.extend(self._fetch_kind("bulk", NSE_BULK_CSV_URL))
        if self.include_block:
            items.extend(self._fetch_kind("block", NSE_BLOCK_CSV_URL))
        return items

    def _fetch_kind(self, kind: str, url: str) -> Iterator[CollectorItem]:
        def _do(attempt: int) -> str:
            if attempt > 1:
                self.http.warmup(force=True)
            else:
                self.http.warmup()
            response = self.http.get_or_raise(url)
            text = response.text
            if not text or not text.strip():
                # Empty CSV is normal on holidays — not an error.
                return ""
            return text

        try:
            text = fetch_with_retries(_do, label=f"nse_{kind}_csv")
        except CollectorHttpError as exc:
            logger.warning("Skipping %s deals: %s", kind, exc)
            return iter(())

        rows = parse_nse_deal_csv(text, deal_kind=kind)
        logger.info("Parsed %d %s-deal rows from NSE", len(rows), kind)
        for row in rows:
            yield _row_to_collector_item(row)
