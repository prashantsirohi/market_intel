from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class PdfFetchResult:
    status: str
    local_path: str | None = None
    content_hash: str | None = None
    size_bytes: int = 0
    error: str | None = None
    attempts: int = 0
    download_time_ms: int = 0


class PdfFetcher:
    def __init__(
        self,
        cache_dir: str = "./data/pdfs",
        max_size_mb: float = 25.0,
        session: requests.Session | None = None,
        throttle_sec: float = 2.0,
        max_retries: int = 3,
        timeout: int = 30,
        backoff_sec: float = 5.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_size_mb = max_size_mb
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.throttle_sec = throttle_sec
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_sec = backoff_sec
        self.session = session or requests.Session()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, url: str) -> PdfFetchResult:
        if not url:
            return PdfFetchResult(status="error", error="Empty URL")

        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        
        if self.is_cached(url):
            cached_path = self.cache_path_from_url(url)
            if cached_path and cached_path.exists():
                size = cached_path.stat().st_size
                return PdfFetchResult(
                    status="cached",
                    local_path=str(cached_path),
                    content_hash=url_hash,
                    size_bytes=size,
                    attempts=1,
                )

        for attempt in range(1, self.max_retries + 1):
            start_time = int(time.time() * 1000)
            
            try:
                head_resp = self.session.head(url, timeout=10)
                content_length = head_resp.headers.get("Content-Length")
                if content_length:
                    size = int(content_length)
                    if size > self.max_size_bytes:
                        return PdfFetchResult(
                            status="too_large",
                            size_bytes=size,
                            error=f"File size {size} exceeds {self.max_size_mb}MB limit",
                            attempts=attempt,
                        )
                
                time.sleep(self.throttle_sec)
                
                resp = self.session.get(url, timeout=self.timeout, stream=True)
                resp.raise_for_status()
                
                content = resp.content
                if len(content) > self.max_size_bytes:
                    return PdfFetchResult(
                        status="too_large",
                        size_bytes=len(content),
                        error=f"Downloaded size exceeds {self.max_size_mb}MB limit",
                        attempts=attempt,
                    )
                
                content_hash = hashlib.sha256(content).hexdigest()
                local_path = self.cache_dir / f"{content_hash}.pdf"
                local_path.write_bytes(content)
                
                download_time = int(time.time() * 1000) - start_time
                
                return PdfFetchResult(
                    status="ok",
                    local_path=str(local_path),
                    content_hash=content_hash,
                    size_bytes=len(content),
                    attempts=attempt,
                    download_time_ms=download_time,
                )
                
            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    logger.warning(f"Timeout on attempt {attempt}, retrying...")
                    time.sleep(self.backoff_sec)
                    continue
                return PdfFetchResult(
                    status="timeout",
                    error=f"Failed after {attempt} attempts",
                    attempts=attempt,
                )
                
            except requests.RequestException as e:
                if attempt < self.max_retries:
                    logger.warning(f"Request error on attempt {attempt}: {e}, retrying...")
                    time.sleep(self.backoff_sec)
                    continue
                logger.error(f"PDF fetch failed for {url}: {e}")
                return PdfFetchResult(status="error", error=str(e), attempts=attempt)
                
            except Exception as e:
                logger.error(f"Unexpected error fetching PDF: {e}")
                return PdfFetchResult(status="error", error=str(e), attempts=attempt)

        return PdfFetchResult(status="error", error="Max retries exceeded", attempts=self.max_retries)

    def is_cached(self, url: str) -> bool:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        existing = list(self.cache_dir.glob(f"{url_hash}*.pdf"))
        return len(existing) > 0

    def cache_path(self, content_hash: str) -> str:
        return str(self.cache_dir / f"{content_hash}.pdf")

    def cache_path_from_url(self, url: str) -> Path | None:
        files = list(self.cache_dir.glob("*.pdf"))
        return files[0] if files else None

    def get_cache_dir(self) -> str:
        return str(self.cache_dir)