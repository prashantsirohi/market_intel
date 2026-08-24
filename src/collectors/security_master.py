"""Official NSE/BSE active-equity listing masters for identity routing."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from collectors.http_utils import ThrottledHttpClient


SECURITY_MASTER_POLICY_VERSION = "market-intel-security-master-v1"
PARSER_VERSION = "market-intel-security-master-parser-v1"
SCHEMA_VERSION = "listed-security-observation-v1"
NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_ACTIVE_EQUITY_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")


@dataclass(frozen=True)
class ListedSecurityRecord:
    exchange: str
    exchange_security_id: str
    symbol: str | None
    isin: str | None
    company_name: str | None
    series: str | None
    board: str | None
    listing_date: date | None
    active_flag: bool
    instrument_type: str
    identity_status: str
    source_row_hash: str


@dataclass(frozen=True)
class ListingDataset:
    exchange: str
    source_url: str
    source_hash: str
    effective_date: date
    records: tuple[ListedSecurityRecord, ...]


def normalize_isin(value: Any) -> str | None:
    candidate = str(value or "").strip().upper()
    return candidate or None


def classify_instrument(isin: str | None) -> str:
    if isin and isin.startswith("INE"):
        return "CORPORATE_EQUITY"
    if isin and isin.startswith("INF"):
        return "FUND_ETF"
    return "OTHER"


def identity_status(isin: str | None) -> str:
    return "VALID_ISIN" if isin and _ISIN_RE.fullmatch(isin) else "INVALID_ISIN"


def _row_hash(row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_nse_equity_csv(raw: bytes) -> list[ListedSecurityRecord]:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]
    if not rows or not {"SYMBOL", "ISIN NUMBER"}.issubset(rows[0]):
        raise ValueError("NSE equity master schema changed or returned no rows")
    records: list[ListedSecurityRecord] = []
    for normalized in rows:
        symbol = normalized.get("SYMBOL", "").upper()
        series = normalized.get("SERIES", "").upper() or None
        if not symbol:
            continue
        isin = normalize_isin(normalized.get("ISIN NUMBER"))
        records.append(ListedSecurityRecord(
            exchange="NSE",
            exchange_security_id=f"{symbol}:{series or 'UNKNOWN'}",
            symbol=symbol,
            isin=isin,
            company_name=normalized.get("NAME OF COMPANY") or None,
            series=series,
            board="MAIN" if series == "EQ" else "OTHER_SERIES",
            listing_date=_parse_date(normalized.get("DATE OF LISTING")),
            active_flag=True,
            instrument_type=classify_instrument(isin),
            identity_status=identity_status(isin),
            source_row_hash=_row_hash(normalized),
        ))
    return records


def parse_bse_active_equity(payload: Any) -> list[ListedSecurityRecord]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("BSE active-equity master returned no rows")
    required = {"SCRIP_CD", "ISIN_NUMBER", "scrip_id"}
    if not required.issubset(payload[0]):
        raise ValueError("BSE active-equity master schema changed")
    records: list[ListedSecurityRecord] = []
    for source_row in payload:
        row = {str(key): value for key, value in source_row.items()}
        security_id = str(row.get("SCRIP_CD") or "").strip().removesuffix(".0")
        if not security_id:
            continue
        isin = normalize_isin(row.get("ISIN_NUMBER"))
        status = str(row.get("Status") or "Active").strip().upper()
        records.append(ListedSecurityRecord(
            exchange="BSE",
            exchange_security_id=security_id,
            symbol=str(row.get("scrip_id") or "").strip().upper() or None,
            isin=isin,
            company_name=str(row.get("Scrip_Name") or row.get("Issuer_Name") or "").strip() or None,
            series=str(row.get("GROUP") or "").strip().upper() or None,
            board="MAIN",
            listing_date=None,
            active_flag=status == "ACTIVE",
            instrument_type=classify_instrument(isin),
            identity_status=identity_status(isin),
            source_row_hash=_row_hash(row),
        ))
    return records


class OfficialSecurityMasterCollector:
    def __init__(self, *, http: ThrottledHttpClient | None = None):
        self.http = http or ThrottledHttpClient(
            warmup_urls=("https://www.nseindia.com/", "https://www.bseindia.com/"),
            extra_headers={"Accept": "application/json,text/csv,text/plain,*/*"},
        )

    def fetch(self, exchange: str, *, effective_date: date) -> ListingDataset:
        normalized = exchange.strip().upper()
        if normalized == "NSE":
            return self._fetch_nse(effective_date)
        if normalized == "BSE":
            return self._fetch_bse(effective_date)
        raise ValueError(f"unsupported exchange: {exchange}")

    def _fetch_nse(self, effective_date: date) -> ListingDataset:
        self.http.warmup()
        response = self.http.get_or_raise(
            NSE_EQUITY_URL,
            headers={"Referer": "https://www.nseindia.com/all-reports"},
        )
        raw = response.content
        if not raw or raw.lstrip().lower().startswith(b"<!doctype html"):
            raise ValueError("NSE equity master returned empty or HTML content")
        records = parse_nse_equity_csv(raw)
        return ListingDataset(
            exchange="NSE", source_url=NSE_EQUITY_URL,
            source_hash=hashlib.sha256(raw).hexdigest(),
            effective_date=effective_date, records=tuple(records),
        )

    def _fetch_bse(self, effective_date: date) -> ListingDataset:
        self.http.warmup()
        response = self.http.get_or_raise(
            BSE_ACTIVE_EQUITY_URL,
            headers={"Origin": "https://www.bseindia.com", "Referer": "https://www.bseindia.com/corporates/List_Scrips.html"},
        )
        raw = response.content
        if not raw or raw.lstrip().lower().startswith(b"<!doctype html"):
            raise ValueError("BSE active-equity master returned empty or HTML content")
        try:
            payload = response.json()
            if isinstance(payload, str):
                payload = json.loads(payload)
        except ValueError as exc:
            raise ValueError("BSE active-equity master returned invalid JSON") from exc
        records = parse_bse_active_equity(payload)
        return ListingDataset(
            exchange="BSE", source_url=BSE_ACTIVE_EQUITY_URL,
            source_hash=hashlib.sha256(raw).hexdigest(),
            effective_date=effective_date, records=tuple(records),
        )
