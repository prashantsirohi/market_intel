"""NSE corporate-actions (stock splits and bonus issues) collector.

Fetches historical and recent corporate actions from the NSE API:
  https://www.nseindia.com/api/corporates-corporateActions
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from collectors.base import BaseCollector, CollectorItem
from collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)

NSE_CORP_ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions"
NSE_WARMUP_URLS = (
    "https://www.nseindia.com/",
    "https://www.nseindia.com/companies-listing/corporate-filings-corporate-actions",
)


def classify_action(subject: str) -> tuple[str, str]:
    """Determine action type (Split or Bonus) and extract ratio/details."""
    sub_lower = subject.lower()
    
    # Check for Bonus
    if 'bonus' in sub_lower:
        ratio_match = re.search(r'(\d+:\d+)', subject)
        ratio = ratio_match.group(1) if ratio_match else "N/A"
        return "Bonus", ratio
        
    # Check for Split
    if 'split' in sub_lower or 'sub-division' in sub_lower or 'sub division' in sub_lower or 'subdivision' in sub_lower:
        # Try to find face value changes like "From Rs 10 to Re 1"
        from_to_match = re.search(r'from\s+rs\s*(\d+)/?.*\s+to\s+(?:re|rs)\s*(\d+)/?', sub_lower)
        if from_to_match:
            ratio = f"From Rs {from_to_match.group(1)} to Rs {from_to_match.group(2)}"
        else:
            ratio_match = re.search(r'(\d+:\d+)', subject)
            ratio = ratio_match.group(1) if ratio_match else "Sub-division"
        return "Split", ratio
        
    return "Other", "N/A"


class NseCorporateActionsCollector(BaseCollector):
    """Collector for stock splits and bonus issues from NSE India API."""

    source_name = "nse_corporate_actions"
    source_type = "api"

    def __init__(
        self,
        *,
        symbols: Optional[Iterable[str]] = None,
        isins: Optional[Iterable[str]] = None,
        start_year: int = 2000,
        end_year: Optional[int] = None,
        throttle_sec: float = 1.8,
        http: ThrottledHttpClient | None = None,
    ):
        self.symbols = set(s.strip().upper() for s in symbols) if symbols else None
        self.isins = set(i.strip().upper() for i in isins) if isins else None
        self.start_year = start_year
        self.end_year = end_year or datetime.now().year
        
        self.http = http or ThrottledHttpClient(
            warmup_urls=NSE_WARMUP_URLS,
            min_request_gap_sec=throttle_sec,
            extra_headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.nseindia.com",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-corporate-actions",
            },
        )

    def fetch_all(self) -> Iterable[CollectorItem]:
        """Fetch and filter corporate actions across the configured years."""
        # 1. Warm up the HTTP session
        self.http.warmup()

        # 2. Iterate through each year
        keywords = ["split", "bonus", "sub-division", "sub division", "subdivision"]
        years = list(range(self.start_year, self.end_year + 1))
        
        seen_keys = set()

        for year in years:
            params = {
                "index": "equities",
                "from_date": f"01-01-{year}",
                "to_date": f"31-12-{year}",
            }

            def _fetch_year(attempt: int) -> list[dict[str, Any]]:
                if attempt > 1:
                    self.http.warmup(force=True)
                response = self.http.get_or_raise(NSE_CORP_ACTIONS_URL, params=params)
                try:
                    return response.json()
                except ValueError as exc:
                    from collectors.http_utils import TemporaryHttpError
                    raise TemporaryHttpError(f"NSE returned non-JSON: {exc}") from exc

            try:
                raw_actions = fetch_with_retries(_fetch_year, label=f"nse_corporate_actions_{year}")
                logger.info("Fetched %d raw actions for year %d", len(raw_actions), year)
            except CollectorHttpError as exc:
                logger.warning("Failed to fetch corporate actions for year %d: %s", year, exc)
                continue

            for act in raw_actions:
                symbol = act.get("symbol", "").strip().upper()
                isin = act.get("isin", "").strip().upper()
                subject = act.get("subject", "").strip()
                ex_date_str = act.get("exDate", "").strip()
                
                # Check uniqueness
                dedupe_key = (symbol, isin, subject, ex_date_str)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                # Check relevance
                sub_lower = subject.lower()
                if not any(kw in sub_lower for kw in keywords):
                    continue

                action_type, ratio = classify_action(subject)
                if action_type == "Other":
                    continue

                # Filter by symbol list if provided
                if self.symbols and symbol not in self.symbols:
                    # Also check ISIN list mapping fallback
                    if not (self.isins and isin in self.isins):
                        continue
                elif self.isins and isin not in self.isins:
                    continue

                # Parse exDate
                event_date = None
                if ex_date_str:
                    try:
                        event_date = datetime.strptime(ex_date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                # Return CollectorItem
                yield CollectorItem(
                    source=self.source_name,
                    source_type=self.source_type,
                    external_id=f"{symbol}_{isin}_{ex_date_str}",
                    symbol=symbol,
                    title=f"{action_type} {ratio}",
                    description=subject,
                    event_date=event_date,
                    published_at=event_date,
                    company_name=act.get("comp", "").strip(),
                    isin=isin,
                    raw_payload=act,
                )
