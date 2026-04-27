from __future__ import annotations

import logging
import random
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
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
    "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


@dataclass
class RssItem:
    title: str
    link: Optional[str]
    description: Optional[str]
    pub_date: Optional[datetime]
    guid: Optional[str]
    raw: dict[str, Any]


class NseRssError(Exception):
    pass


class TemporaryNseRssError(NseRssError):
    pass


class EmptyBodyError(TemporaryNseRssError):
    pass


class XmlParseError(TemporaryNseRssError):
    pass


class NseRssClient:
    def __init__(
        self,
        timeout: tuple[float, float] = (10.0, 25.0),
        min_request_gap_sec: float = 1.5,
    ):
        self.timeout = timeout
        self.min_request_gap_sec = min_request_gap_sec
        self.session = self._build_session()
        self.last_request_ts = 0.0

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
            allowed_methods=frozenset(["GET", "HEAD"]),
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

    def _get(self, url: str, **kwargs: Any) -> Response:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self.last_request_ts = time.time()
        return response

    def warmup(self) -> None:
        for url in WARMUP_URLS:
            try:
                logger.info("Warmup GET %s", url)
                self._get(url)
            except requests.RequestException as exc:
                logger.warning("Warmup failed for %s: %s", url, exc)

    def fetch_raw_xml(self, force_warmup: bool = False) -> str:
        if force_warmup:
            self.warmup()

        response = self._get(RSS_URL)
        status = response.status_code

        logger.info("RSS GET status=%s", status)

        if status in (401, 403, 429, 500, 502, 503, 504):
            raise TemporaryNseRssError(f"NSE RSS temporary failure: HTTP {status}")

        if status >= 400:
            raise NseRssError(f"NSE RSS request failed: HTTP {status}")

        body = response.text.strip()
        if not body:
            raise EmptyBodyError("NSE RSS returned empty body")

        if body[:200].lower().lstrip().startswith("<html") or "<!doctype html" in body[:300].lower():
            raise TemporaryNseRssError("NSE RSS returned HTML instead of XML")

        return body

    def parse_items(self, xml_text: str) -> list[RssItem]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise XmlParseError(f"Could not parse RSS XML: {exc}") from exc

        items: list[RssItem] = []
        for item_el in root.findall(".//item"):
            title = self._get_text(item_el, "title") or ""
            link = self._get_text(item_el, "link")
            description = self._get_text(item_el, "description")
            pub_date_raw = self._get_text(item_el, "pubDate")
            guid = self._get_text(item_el, "guid")

            item = RssItem(
                title=title.strip(),
                link=link.strip() if link else None,
                description=description.strip() if description else None,
                pub_date=self._parse_pub_date(pub_date_raw),
                guid=guid.strip() if guid else None,
                raw={
                    "title": title,
                    "link": link,
                    "description": description,
                    "pubDate": pub_date_raw,
                    "guid": guid,
                },
            )
            items.append(item)

        return items

    @staticmethod
    def _get_text(parent: ET.Element, tag: str) -> Optional[str]:
        child = parent.find(tag)
        if child is None or child.text is None:
            return None
        return child.text

    @staticmethod
    def _parse_pub_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def fetch_all(self, max_attempts: int = 3) -> list[RssItem]:
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                xml_text = self.fetch_raw_xml(force_warmup=(attempt > 1))
                items = self.parse_items(xml_text)
                logger.info("Parsed %d RSS items", len(items))
                return items

            except TemporaryNseRssError as exc:
                last_error = exc
                sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
                logger.warning("Temporary failure on attempt %d/%d: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)

            except requests.RequestException as exc:
                last_error = exc
                sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
                logger.warning("Network failure on attempt %d/%d: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)

        raise NseRssError(f"Failed to fetch NSE RSS after {max_attempts} attempts: {last_error}")

    def collect(self) -> list[RssItem]:
        return self.fetch_all()