from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements"


@dataclass
class ApiItem:
    symbol: str
    company_name: str
    subject: str
    attachment_url: str | None
    announce_date: datetime
    seq_no: str
    category: str | None
    raw: dict[str, Any]


class NseApiError(Exception):
    pass


class TemporaryNseApiError(NseApiError):
    pass


class NseApiClient:
    def __init__(
        self,
        session: Session | None = None,
        throttle_sec: float = 1.5,
        timeout: tuple[float, float] = (10.0, 30.0),
    ):
        self.throttle_sec = throttle_sec
        self.timeout = timeout
        self.session = session or self._build_session()
        self.last_request_ts = 0.0

    def _build_session(self) -> Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _throttle(self) -> None:
        import random
        elapsed = time.time() - self.last_request_ts
        if elapsed < self.throttle_sec:
            time.sleep(self.throttle_sec - elapsed + random.uniform(0.1, 0.3))
        self.last_request_ts = time.time()

    def _get(self, url: str, **kwargs: Any) -> Response:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self.last_request_ts = time.time()
        return response

    def fetch_window(
        self,
        from_date: date,
        to_date: date,
        symbol: str | None = None,
        category: str | None = None,
    ) -> list[ApiItem]:
        params = {
            "indexStart": 1,
            "indexEnd": 50,
            "fromDate": from_date.strftime("%Y-%m-%d"),
            "toDate": to_date.strftime("%Y-%m-%d"),
        }
        
        if symbol:
            params["symbol"] = symbol.upper()
        if category:
            params["category"] = category

        try:
            response = self._get(NSE_API_URL, params=params)
            
            if response.status_code == 429:
                raise TemporaryNseApiError("Rate limited - retry later")
            if response.status_code >= 500:
                raise TemporaryNseApiError(f"NSE API error: {response.status_code}")
            if response.status_code != 200:
                raise NseApiError(f"API returned {response.status_code}")
            
            data = response.json()
            return self._parse_items(data)
            
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise NseApiError(f"API request failed: {e}")

    def fetch_latest(self, lookback_hours: int = 2) -> list[ApiItem]:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        from_dt = now - timedelta(hours=lookback_hours)
        to_dt = now
        
        return self.fetch_window(from_dt.date(), to_dt.date())

    def _parse_items(self, data: list[dict]) -> list[ApiItem]:
        items = []
        for row in data:
            try:
                item = ApiItem(
                    symbol=row.get("symbol", "").strip(),
                    company_name=row.get("companyName", "").strip(),
                    subject=row.get("subject", "").strip(),
                    attachment_url=row.get("attchmentURL") or row.get("pdfLink"),
                    announce_date=self._parse_date(row.get("announcementDate")),
                    seq_no=str(row.get("seqNo", "")),
                    category=row.get("category"),
                    raw=row,
                )
                items.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse item: {e}")
                continue
        
        return items

    def _parse_date(self, date_str: str | None) -> datetime:
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)