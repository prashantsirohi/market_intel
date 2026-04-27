from __future__ import annotations

import argparse
from pathlib import Path

from market_intel.settings import settings
from market_intel.storage.db import Database
from market_intel.processing.entity_resolver import EntityResolver
from market_intel.services.alert_service import AlertService as BaseAlertService
from market_intel.services.event_analysis_service import EventAnalysisService
from market_intel.services.event_ingest_service import EventIngestService
from market_intel.alerts.telegram import TelegramAlert
from ai_trading_system.events.collectors.nse_rss_collector import NseRssClient, extract_symbol


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run standalone market intel RSS collection")
    parser.add_argument("--db-path", default=settings.db_path)
    parser.add_argument("--dry-run-alerts", action="store_true")
    parser.add_argument("--telegram-bot-token", default=settings.telegram_bot_token)
    parser.add_argument("--telegram-chat-id", default=settings.telegram_chat_id)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Path("./data/cache").mkdir(parents=True, exist_ok=True)
    Path("./data/exports").mkdir(parents=True, exist_ok=True)

    db = Database(args.db_path, fresh=True)
    tracked_repo = db.tracked_entity_repo()
    raw_repo = db.raw_event_repo()
    resolved_repo = db.resolved_event_repo()
    alert_repo = db.alert_log_repo()

    resolver = EntityResolver(tracked_repo.list_active())
    analysis_service = EventAnalysisService(raw_repo, resolved_repo, resolver)
    ingest_service = EventIngestService(raw_repo, analysis_service)

    telegram = None
    if args.telegram_bot_token and args.telegram_chat_id:
        telegram = TelegramAlert(args.telegram_bot_token, args.telegram_chat_id)
    alert_service = BaseAlertService(alert_repo, telegram, dry_run=args.dry_run_alerts)

    client = NseRssClient()
    items = client.fetch_all()

    stats = {
        "fetched_count": len(items),
        "new_count": 0,
        "duplicate_count": 0,
        "resolved_count": 0,
        "critical_count": 0,
        "important_count": 0,
        "failed_count": 0,
    }
    for item in items:
        record = {
            "title": item.title,
            "link": item.link,
            "pub_date": item.pub_date.isoformat() if item.pub_date else None,
            "description": item.description,
            "guid": getattr(item, "guid", getattr(item, "raw_guid", None)),
            "symbol": extract_symbol(item.title, item.description),
            "attachment_url": None,
        }
        try:
            result = ingest_service.process_rss_item(record)
            if result["status"] == "duplicate":
                stats["duplicate_count"] += 1
                continue
            stats["new_count"] += 1
            stats["resolved_count"] += 1
            level = result.get("alert_level")
            if level == "critical":
                stats["critical_count"] += 1
            elif level == "important":
                stats["important_count"] += 1
            alert_service.route(result["resolved"])
        except Exception:
            stats["failed_count"] += 1
    alert_service.flush_batched()
    print(stats)
    db.close()


if __name__ == "__main__":
    main()