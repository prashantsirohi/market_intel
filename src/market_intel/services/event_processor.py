from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from market_intel.storage import Database, RawEventRepository, ResolvedEventRepository
from market_intel.processing.deduper import build_event_hash
from market_intel.processing.trust import compute_trust_score
from market_intel.processing.entity_resolver import resolve_entity_id


logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    raw_event_id: int
    resolved_event_id: Optional[int]
    alert_level: str
    is_new: bool


class EventProcessor:
    def __init__(self, db: Database):
        self.db = db
        self.raw_repo = RawEventRepository(db)
        self.resolved_repo = ResolvedEventRepository(db)

    def process_rss_item(
        self,
        item: Any,
    ) -> Optional[ProcessingResult]:
        from market_intel.collectors import RssItem

        if not isinstance(item, RssItem):
            logger.warning("Invalid item type: %s", type(item))
            return None

        symbol = item.raw.get("symbol")
        if not symbol:
            symbol = self._extract_symbol(item.title, item.description)

        raw = self.raw_repo.upsert_event(
            source="nse_rss",
            source_type="rss_feed",
            external_id=item.guid,
            symbol=symbol,
            title=item.title,
            description=item.description,
            event_date=item.pub_date,
            link=item.link,
            raw_payload=item.raw,
        )

        if not raw:
            return None

        trust = compute_trust_score(source="nse_rss", source_type="rss_feed")
        importance = self._compute_importance(item)
        alert_level = self._determine_alert_level(importance, trust)

        entity_id = resolve_entity_id(self.db, symbol) if symbol else None

        resolved = self.resolved_repo.upsert(
            raw_event_id=raw.raw_event_id,
            entity_id=entity_id,
            primary_category=self._categorize(item.title),
            importance_score=importance,
            trust_score=trust,
            alert_level=alert_level,
            is_official=False,
        )

        return ProcessingResult(
            raw_event_id=raw.raw_event_id,
            resolved_event_id=resolved.resolved_event_id if resolved else None,
            alert_level=alert_level,
            is_new=raw.processed is False,
        )

    def process_api_filing(
        self,
        filing: Any,
    ) -> Optional[ProcessingResult]:
        from market_intel.collectors import CorpFiling

        if not isinstance(filing, CorpFiling):
            logger.warning("Invalid filing type: %s", type(filing))
            return None

        raw = self.raw_repo.upsert_event(
            source="nse_api",
            source_type="corporate_filing",
            external_id=filing.filing_id,
            symbol=filing.symbol,
            company_name=filing.company_name,
            title=filing.filing_type,
            category_desc=filing.category,
            event_date=filing.filing_date,
            description=filing.description,
            attachment_url=filing.attachment_url,
            raw_payload=filing.raw,
        )

        if not raw:
            return None

        trust = compute_trust_score(source="nse_api", source_type="corporate_filing")
        importance = self._compute_importance_from_filing(filing)
        alert_level = self._determine_alert_level(importance, trust)

        entity_id = resolve_entity_id(self.db, filing.symbol)

        resolved = self.resolved_repo.upsert(
            raw_event_id=raw.raw_event_id,
            entity_id=entity_id,
            primary_category=filing.category,
            importance_score=importance,
            trust_score=trust,
            alert_level=alert_level,
            is_official=True,
        )

        return ProcessingResult(
            raw_event_id=raw.raw_event_id,
            resolved_event_id=resolved.resolved_event_id if resolved else None,
            alert_level=alert_level,
            is_new=raw.processed is False,
        )

    @staticmethod
    def _extract_symbol(title: str, description: Optional[str] = None) -> Optional[str]:
        import re
        text = f"{title} {description or ''}"
        patterns = [
            r"\b([A-Z]{2,5})\b(?=\s+(?:Ltd|PLC|Inc|Limited|Corporationshare|stocks|shares|announces|declares|reports))",
            r"Announcement\s+for\s+([A-Z]{2,5})\b",
            r"\b([A-Z]{2,5})\b\s+(?:announces|declares|reports)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1)
                if candidate.lower() not in ("ltd", "inc", "plc", "net", "com", "org", "pdf", "www", "nse", "bse"):
                    return candidate
        return None

    @staticmethod
    def _compute_importance(item: Any) -> float:
        title_lower = item.title.lower()
        description_lower = (item.description or "").lower()

        if any(kw in title_lower for kw in ["result", "quarterly", "q1", "q2", "q3", "q4", "fyear"]):
            return 8.5
        if any(kw in title_lower for kw in ["dividend", "bonus", "split", "consolidation"]):
            return 8.0
        if any(kw in title_lower for kw in ["agm", "egm", "meeting", "court"]):
            return 7.5
        if any(kw in title_lower for kw in ["annual", "report"]):
            return 6.0

        return 5.0

    @staticmethod
    def _compute_importance_from_filing(filing: Any) -> float:
        category_lower = filing.category.lower()
        filing_type_lower = filing.filing_type.lower()

        if "result" in category_lower or "result" in filing_type_lower:
            return 9.0
        if "dividend" in category_lower or "dividend" in filing_type_lower:
            return 8.5
        if "allotment" in category_lower or "bonus" in filing_type_lower:
            return 8.0
        if "agm" in category_lower or "egm" in category_lower:
            return 7.5

        return 6.0

    @staticmethod
    def _determine_alert_level(importance: float, trust: float) -> str:
        if importance >= 8.5 and trust >= 80:
            return "critical"
        if importance >= 7.0 and trust >= 60:
            return "important"
        return "info"

    @staticmethod
    def _categorize(title: str) -> str:
        title_lower = title.lower()
        if "result" in title_lower or "quarterly" in title_lower:
            return "financial_results"
        if "dividend" in title_lower:
            return "dividend"
        if "bonus" in title_lower or "split" in title_lower:
            return "capital_reorganization"
        if "agm" in title_lower or "egm" in title_lower:
            return "meeting"
        if "buyback" in title_lower:
            return "buyback"
        return "corporate_action"


class CollectionService:
    def __init__(self, db: Database):
        self.db = db
        self.processor = EventProcessor(db)

    def collect_rss(self) -> list[ProcessingResult]:
        from market_intel.collectors import NseRssClient

        client = NseRssClient()
        items = client.collect()

        results = []
        for item in items:
            result = self.processor.process_rss_item(item)
            if result:
                results.append(result)

        return results

    def collect_api(self, symbols: Optional[list[str]] = None) -> list[ProcessingResult]:
        from market_intel.collectors import NseApiClient

        if symbols is None:
            symbols = []

        if not symbols:
            logger.info("No symbols provided for API collection, skipping")
            return []

        client = NseApiClient()
        filings = client.collect(symbols=symbols)

        results = []
        for filing in filings:
            result = self.processor.process_api_filing(filing)
            if result:
                results.append(result)

        return results

    def run_collection(self, symbols: Optional[list[str]] = None) -> dict[str, int]:
        rss_results = self.collect_rss()
        api_results = self.collect_api(symbols=symbols)

        return {
            "rss_processed": len(rss_results),
            "api_processed": len(api_results),
            "total": len(rss_results) + len(api_results),
        }