from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
WARMUP_URLS = [
    "https://www.nseindia.com/",
    "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    "X-Requested-With": "XMLHttpRequest",
}


class NseApiError(Exception):
    pass


class TemporaryNseApiError(NseApiError):
    pass


@dataclass
class CorpFiling:
    filing_id: str
    symbol: str
    company_name: str
    filing_type: str
    filing_date: datetime
    description: str
    attachment_url: Optional[str]
    category: str
    raw: dict[str, Any]


class NseApiClient:
    def __init__(
        self,
        timeout: tuple[float, float] = (10.0, 25.0),
        min_request_gap_sec: float = 2.0,
    ):
        self.timeout = timeout
        self.min_request_gap_sec = min_request_gap_sec
        self.session = self._build_session()
        self.last_request_ts = 0.0
        self._cookies_loaded = False

    def _build_session(self) -> Session:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _throttle(self) -> None:
        elapsed = time.time() - self.last_request_ts
        if elapsed < self.min_request_gap_sec:
            sleep_for = self.min_request_gap_sec - elapsed + random.uniform(0.1, 0.4)
            time.sleep(sleep_for)

    def warmup(self) -> None:
        if self._cookies_loaded:
            return

        for url in WARMUP_URLS:
            try:
                logger.info("Warmup GET %s", url)
                self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                logger.warning("Warmup failed for %s: %s", url, exc)

        self._cookies_loaded = True
        logger.info("Warmup complete, cookies: %d", len(self.session.cookies))

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self.last_request_ts = time.time()
        return response

    def fetch_announcements(self, symbol: str, max_attempts: int = 3) -> list[CorpFiling]:
        last_error: Optional[Exception] = None

        self.warmup()

        params = {
            "index": "equities",
            "symbol": symbol,
            "reqXbrl": "false",
        }

        for attempt in range(1, max_attempts + 1):
            try:
                response = self._get(ANNOUNCEMENTS_URL, params=params)
                status = response.status_code

                logger.info("API GET status=%s for symbol=%s", status, symbol)

                if status in (401, 403, 429, 500, 502, 503, 504):
                    self._cookies_loaded = False
                    raise TemporaryNseApiError(f"NSE API temporary failure: HTTP {status}")

                if status >= 400:
                    raise NseApiError(f"NSE API request failed: HTTP {status}")

                if not response.text.strip():
                    return []

                data = response.json()
                return self._parse_filings(data, symbol)

            except TemporaryNseApiError as exc:
                last_error = exc
                sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
                logger.warning("Temporary failure on attempt %d/%d: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)

            except json.JSONDecodeError as exc:
                last_error = exc
                sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
                logger.warning("JSON decode error on attempt %d/%d: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)

            except requests.RequestException as exc:
                last_error = exc
                sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
                logger.warning("Network failure on attempt %d/%d: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)

        raise NseApiError(f"Failed to fetch NSE API after {max_attempts} attempts: {last_error}")

    def _parse_filings(self, data: list, symbol: str) -> list[CorpFiling]:
        filings = []
        for item in data:
            filing = CorpFiling(
                filing_id=str(item.get("id", "")),
                symbol=symbol,
                company_name=item.get("attnFileDesc", ""),
                filing_type=item.get("announcementType", ""),
                filing_date=self._parse_date(item.get("annDateTime")),
                description=item.get("subject", ""),
                attachment_url=item.get("pdfUrl"),
                category=item.get("category", ""),
                raw=item,
            )
            filings.append(filing)

        return filings

    @staticmethod
    def _parse_date(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(value)
            except Exception:
                return datetime.now(timezone.utc)

    def collect_for_symbols(self, symbols: list[str]) -> list[CorpFiling]:
        all_filings = []
        for symbol in symbols:
            try:
                filings = self.fetch_announcements(symbol)
                all_filings.extend(filings)
                logger.info("Fetched %d filings for %s", len(filings), symbol)
            except NseApiError as exc:
                logger.error("Failed to fetch announcements for %s: %s", symbol, exc)

        return all_filings

    def collect(self, symbols: Optional[list[str]] = None) -> list[CorpFiling]:
        if symbols is None:
            symbols = []
        return self.collect_for_symbols(symbols)