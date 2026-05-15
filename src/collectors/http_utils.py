"""Shared HTTP session / throttle / retry helpers for all collectors.

Factored out of ``nse_rss.py`` so every new collector (bulk-deals, BSE corp,
SAST, insider, credit-rating) gets the same retry-with-backoff, polite
rate-limiting, and browser-like headers.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

DEFAULT_TIMEOUT: tuple[float, float] = (10.0, 25.0)


class CollectorHttpError(Exception):
    """Raised when an HTTP collector cannot complete its fetch."""


class TemporaryHttpError(CollectorHttpError):
    """Retryable failure (5xx, 429, empty body, parse error)."""


def build_session(
    *,
    extra_headers: dict[str, str] | None = None,
    total_retries: int = 3,
    backoff_factor: float = 1.5,
) -> Session:
    session = requests.Session()
    headers = dict(DEFAULT_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    session.headers.update(headers)

    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class ThrottledHttpClient:
    """Mixin-friendly polite HTTP client with min-gap pacing.

    Subclasses or composers call ``self._get(url)`` to honour throttling.
    Designed for the NSE/BSE pattern where ≥1.5 s between requests is
    required to avoid 403/429 lockouts.
    """

    def __init__(
        self,
        *,
        session: Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        min_request_gap_sec: float = 1.5,
        warmup_urls: tuple[str, ...] = (),
        extra_headers: dict[str, str] | None = None,
    ):
        self.session = session or build_session(extra_headers=extra_headers)
        self.timeout = timeout
        self.min_request_gap_sec = min_request_gap_sec
        self.warmup_urls = warmup_urls
        self._last_request_ts = 0.0
        self._warmed_up = False

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.min_request_gap_sec:
            sleep_for = self.min_request_gap_sec - elapsed + random.uniform(0.1, 0.4)
            time.sleep(sleep_for)

    def _get(self, url: str, **kwargs: Any) -> Response:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self._last_request_ts = time.time()
        return response

    def warmup(self, force: bool = False) -> None:
        if self._warmed_up and not force:
            return
        for url in self.warmup_urls:
            try:
                logger.info("Warmup GET %s", url)
                self._get(url)
            except requests.RequestException as exc:
                logger.warning("Warmup failed for %s: %s", url, exc)
        self._warmed_up = True

    def get_or_raise(self, url: str, **kwargs: Any) -> Response:
        """GET with status checking. Raises ``TemporaryHttpError`` on 4xx/5xx."""
        try:
            response = self._get(url, **kwargs)
        except requests.RequestException as exc:
            raise TemporaryHttpError(f"Request to {url} failed: {exc}") from exc

        status = response.status_code
        if status in (401, 403, 429, 500, 502, 503, 504):
            raise TemporaryHttpError(f"{url}: temporary HTTP {status}")
        if status >= 400:
            raise CollectorHttpError(f"{url}: HTTP {status}")
        return response


def fetch_with_retries(
    fetch_fn,
    *,
    max_attempts: int = 3,
    label: str = "fetch",
):
    """Run ``fetch_fn()`` retrying on TemporaryHttpError with exp backoff.

    Returns whatever fetch_fn returns; raises after exhausting attempts.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_fn(attempt)
        except TemporaryHttpError as exc:
            last_error = exc
            sleep_for = min(2**attempt, 10) + random.uniform(0.3, 0.9)
            logger.warning(
                "%s: temporary failure attempt %d/%d: %s",
                label, attempt, max_attempts, exc,
            )
            time.sleep(sleep_for)
    raise CollectorHttpError(
        f"{label}: failed after {max_attempts} attempts: {last_error}"
    )
