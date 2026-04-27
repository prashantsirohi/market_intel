from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from market_intel.storage.repositories import RawEvent, RawEventRepository
from market_intel.processing.deduper import build_event_hash

logger = logging.getLogger(__name__)


@dataclass
class RssItem:
    external_id: str
    title: str
    link: str
    published: Optional[datetime]
    symbol: Optional[str]
    company_name: Optional[str]
    category: Optional[str]
    description: Optional[str]
    attachment_url: Optional[str]


class EventIngestService:
    def __init__(self, raw_event_repo: RawEventRepository):
        self.raw_event_repo = raw_event_repo

    def process_rss_item(self, item: RssItem) -> Optional[RawEvent]:
        event_hash = build_event_hash(
            source="nse_rss",
            symbol=item.symbol,
            title=item.title,
            event_date=item.published.isoformat() if item.published else None,
            attachment_url=item.attachment_url,
            external_id=item.external_id,
        )

        raw_payload = {
            "external_id": item.external_id,
            "title": item.title,
            "link": item.link,
            "published": item.published.isoformat() if item.published else None,
            "symbol": item.symbol,
            "company_name": item.company_name,
            "category": item.category,
            "description": item.description,
            "attachment_url": item.attachment_url,
        }

        result = self.raw_event_repo.upsert_event(
            source="nse_rss",
            source_type="rss",
            external_id=item.external_id,
            symbol=item.symbol,
            company_name=item.company_name,
            title=item.title,
            category_desc=item.category,
            event_date=item.published,
            published_at=item.published,
            link=item.link,
            attachment_url=item.attachment_url,
            description=item.description,
            raw_payload=raw_payload,
        )

        if result and result.seen_count > 1:
            logger.debug(f"Duplicate event: {event_hash[:12]} (seen {result.seen_count}x)")

        return result

    def process_rss_feed(
        self, items: list[RssItem], source: str = "nse_rss"
    ) -> dict[str, int]:
        stats = {"new": 0, "duplicates": 0, "errors": 0}

        for item in items:
            try:
                result = self.process_rss_item(item)
                if result:
                    if result.seen_count == 1:
                        stats["new"] += 1
                    else:
                        stats["duplicates"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error processing RSS item: {e}")
                stats["errors"] += 1

        return stats


def rss_item_to_dataclass(
    item: dict[str, Any], published: Optional[datetime] = None
) -> RssItem:
    return RssItem(
        external_id=item.get("id", item.get("link", "")),
        title=item.get("title", ""),
        link=item.get("link", ""),
        published=published,
        symbol=item.get("symbol"),
        company_name=item.get("company_name"),
        category=item.get("category"),
        description=item.get("description"),
        attachment_url=item.get("attachment_url"),
    )