from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from market_intel.storage import Database
from market_intel.services import CollectionService, AlertScheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def collect(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    service = CollectionService(db)

    try:
        logger.info("Starting collection run...")
        summary = service.run_collection()

        logger.info("Collection complete:")
        logger.info("  RSS processed: %d", summary["rss_processed"])
        logger.info("  API processed: %d", summary["api_processed"])
        logger.info("  Total: %d", summary["total"])

        return 0
    except Exception as exc:
        logger.error("Collection failed: %s", exc)
        return 1
    finally:
        db.close()


def alerts(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    scheduler = AlertScheduler(db)

    try:
        logger.info("Checking for pending alerts...")
        results = scheduler.check_and_send()

        logger.info("Alerts sent:")
        logger.info("  Critical: %d", results["critical"])
        logger.info("  Important: %d", results["important"])
        logger.info("  Failed: %d", results["failed"])

        return 0
    except Exception as exc:
        logger.error("Alert dispatch failed: %s", exc)
        return 1
    finally:
        db.close()


def run(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    service = CollectionService(db)
    scheduler = AlertScheduler(db)

    try:
        logger.info("=== Market Intel Run ===")
        summary = service.run_collection()
        logger.info("Collection: %d events processed", summary["total"])

        results = scheduler.check_and_send()
        logger.info("Alerts: %d critical, %d important, %d failed",
                    results["critical"], results["important"], results["failed"])

        return 0
    except Exception as exc:
        logger.error("Run failed: %s", exc)
        return 1
    finally:
        db.close()


def status(args: argparse.Namespace) -> int:
    db = Database(args.db_path)

    try:
        from market_intel.storage import (
            RawEventRepository,
            ResolvedEventRepository,
            AlertLogRepository,
            TrackedEntityRepository,
        )

        raw_repo = RawEventRepository(db)
        resolved_repo = ResolvedEventRepository(db)
        alert_repo = AlertLogRepository(db)
        entity_repo = TrackedEntityRepository(db)

        print("\n=== Market Intel Status ===\n")

        total_raw = raw_repo.count()
        unprocessed = raw_repo.list_unprocessed(limit=1000)
        print(f"Raw Events: {total_raw}")
        print(f"  Unprocessed: {len(unprocessed)}")

        entities = entity_repo.list_active()
        print(f"\nTracked Entities: {len(entities)}")

        critical = resolved_repo.list_by_alert_level("critical", limit=100)
        important = resolved_repo.list_by_alert_level("important", limit=100)
        print(f"\nResolved Events:")
        print(f"  Critical: {len(critical)}")
        print(f"  Important: {len(important)}")

        from market_intel.storage import AlertLogRepository
        pending = alert_repo.list_pending(channel="telegram", limit=100)
        print(f"\nPending Alerts: {len(pending)}")

        return 0
    except Exception as exc:
        logger.error("Status failed: %s", exc)
        return 1
    finally:
        db.close()


def add_entity(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    repo = db.tracked_entity_repo()

    try:
        repo.upsert(
            symbol=args.symbol,
            company_name=args.company_name,
            sector=args.sector,
            priority=args.priority or 0,
        )
        logger.info("Added entity: %s", args.symbol)
        return 0
    except Exception as exc:
        logger.error("Failed to add entity: %s", exc)
        return 1
    finally:
        db.close()


def migrate(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    try:
        from market_intel.storage.migrations import apply_migrations

        with db.get_connection() as conn:
            applied = apply_migrations(conn)
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))
        else:
            logger.info("Schema already up to date")
        return 0
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Market Intel - NSE Corporate Announcements Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--db-path",
        default="./data/market_intel.duckdb",
        help="Path to DuckDB database (default: ./data/market_intel.duckdb)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    collect_parser = subparsers.add_parser("collect", help="Collect announcements from NSE")
    collect_parser.set_defaults(func=collect)

    alerts_parser = subparsers.add_parser("alerts", help="Send pending alerts")
    alerts_parser.set_defaults(func=alerts)

    run_parser = subparsers.add_parser("run", help="Run full collection and alert cycle")
    run_parser.set_defaults(func=run)

    status_parser = subparsers.add_parser("status", help="Show system status")
    status_parser.set_defaults(func=status)

    entity_parser = subparsers.add_parser("add-entity", help="Add a tracked entity")
    entity_parser.add_argument("--symbol", required=True, help="Stock symbol")
    entity_parser.add_argument("--company-name", help="Company name")
    entity_parser.add_argument("--entity-type", help="Entity type (default: stock)")
    entity_parser.add_argument("--sector", help="Sector")
    entity_parser.add_argument("--priority", type=int, help="Priority (0-10)")
    entity_parser.set_defaults(func=add_entity)

    migrate_parser = subparsers.add_parser("migrate", help="Apply schema migrations")
    migrate_parser.set_defaults(func=migrate)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
