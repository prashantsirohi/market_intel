from __future__ import annotations

import argparse
import logging
from datetime import datetime

import httpx

from market_intel.settings import get_settings
from market_intel.storage.db import Database
from market_intel.services.ingest import (
    EventIngestService,
    RssItem,
    rss_item_to_dataclass,
)
from market_intel.services.analysis import EventAnalysisService
from market_intel.services.alert import AlertService
from market_intel.collectors.nse_rss import NseRssClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NSE_RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"

WARMUP_URLS = [
    "https://www.nseindia.com/",
    "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


def fetch_rss_feed(client: NseRssClient = None) -> list[RssItem]:
    if client is None:
        client = NseRssClient(timeout=(10.0, 60.0))

    items = client.fetch_all()

    rss_items = []
    for item in items:
        rss_item = RssItem(
            external_id=item.guid or item.link or "",
            title=item.title,
            link=item.link or "",
            published=item.pub_date,
            symbol=None,
            company_name=None,
            category=None,
            description=item.description,
            attachment_url=None,
        )
        rss_items.append(rss_item)

    return rss_items


def run_collect(settings):
    logger.info("Starting collection run...")

    db = Database(settings.db_path, fresh=True)

    ingest_service = EventIngestService(db.raw_event_repo())
    analysis_service = EventAnalysisService(
        db.raw_event_repo(), db.resolved_event_repo()
    )
    alert_service = AlertService(settings, db.resolved_event_repo(), db.alert_log_repo())

    logger.info("Fetching RSS feed...")
    feed_items = fetch_rss_feed()

    if not feed_items:
        logger.warning("No items fetched")
        return {"ingested": 0, "analyzed": 0, "alerts": 0}

    ingest_stats = ingest_service.process_rss_feed(feed_items)
    logger.info(f"Ingest: {ingest_stats}")

    analysis_stats = analysis_service.analyze_pending(limit=100)
    logger.info(f"Analyze: {analysis_stats}")

    alert_stats = alert_service.route()
    logger.info(f"Alerts: {alert_stats}")

    db.close()

    return {
        "ingested": ingest_stats.get("new", 0),
        "duplicates": ingest_stats.get("duplicates", 0),
        "analyzed": analysis_stats.get("analyzed", 0),
        "critical": alert_stats.get("critical", 0),
        "important": alert_stats.get("important", 0),
    }


def run_flush(settings):
    logger.info("Flushing batched alerts...")

    db = Database(settings.db_path)
    alert_service = AlertService(settings, db.resolved_event_repo(), db.alert_log_repo())

    stats = alert_service.flush_batched()
    logger.info(f"Flushed: {stats}")

    db.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Market Intelligence Collector")
    parser.add_argument(
        "--db-path", default=None, help="DuckDB path (default: from settings)"
    )
    parser.add_argument(
        "--flush", action="store_true", help="Flush batched alerts"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Skip alerts"
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.db_path:
        settings.db_path = args.db_path
    if args.dry_run:
        settings.alerts_enabled = False

    if args.flush:
        result = run_flush(settings)
    else:
        result = run_collect(settings)

    logger.info(f"Complete: {result}")
    return result


if __name__ == "__main__":
    main()