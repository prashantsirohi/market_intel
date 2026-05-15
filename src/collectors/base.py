"""Common collector contract.

Every collector (NSE RSS, BSE corp, bulk/block deals, SAST, insider trades,
credit-rating feeds) returns a uniform CollectorItem so the downstream ingest
service can stay source-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional


@dataclass
class CollectorItem:
    """Source-agnostic event payload."""

    source: str                       # e.g. "nse_rss", "bse_corp", "nse_bulk_deal"
    source_type: str                  # "rss" | "api" | "scrape" | "csv"
    external_id: Optional[str]        # source-side primary key if available
    symbol: Optional[str]             # NSE/BSE ticker
    title: str
    description: Optional[str] = None
    event_date: Optional[datetime] = None
    published_at: Optional[datetime] = None
    link: Optional[str] = None
    attachment_url: Optional[str] = None
    company_name: Optional[str] = None
    isin: Optional[str] = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """All collectors implement fetch_all().

    Implementations are responsible for:
    - HTTP session management + retries (helpers in market_intel.collectors.http_utils)
    - Rate-limit politeness (≥1.5s between NSE requests)
    - Returning *only* well-formed items (drop unparseable rows; log warnings)
    """

    source_name: str = ""
    source_type: str = "scrape"

    @abstractmethod
    def fetch_all(self) -> Iterable[CollectorItem]:
        """Yield all current items from this source."""
        raise NotImplementedError
