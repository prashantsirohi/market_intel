from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from storage import Database
from services import CollectionService, AlertScheduler


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
        logger.info("  RSS processed: %d", summary.get("rss_processed", 0))
        logger.info("  BSE Corp new: %d", summary.get("bse_corp_new", 0))
        logger.info("  Bulk Deal new: %d", summary.get("bulk_deal_new", 0))
        logger.info("  SAST new: %d", summary.get("sast_new", 0))
        logger.info("  Insider trade new: %d", summary.get("insider_new", 0))
        logger.info("  Rating change new: %d", summary.get("rating_new", 0))
        logger.info("  Total: %d", summary.get("total", 0))

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
        from storage import (
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

        from storage import AlertLogRepository
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


def parse_screener(args: argparse.Namespace) -> int:
    import json
    import traceback
    from collectors.screener import ScreenerClient
    from settings import settings

    client = ScreenerClient(
        username=args.username,
        password=args.password,
        data_dir=settings.data_dir,
    )

    try:
        if args.file:
            logger.info("Parsing local file: %s", args.file)
            data = client.parse_excel(args.file)
        elif args.ticker:
            logger.info("Downloading and parsing ticker: %s", args.ticker)
            data = client.fetch_company_data(args.ticker, force_download=args.force)
            
            # Persist to database
            from storage.financials_db import FinancialsDatabase
            db_path = str(Path(settings.data_dir) / "screener_financials.db")
            fin_db = FinancialsDatabase(db_path)
            fin_db.save_company_financials(args.ticker, data)
        else:
            logger.error("Either --ticker or --file must be specified")
            return 1

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info("Saved parsed data to %s", output_path)
        else:
            metadata = data.get("metadata", {})
            print("\n=== Company Financials Summary ===")
            print(f"Company Name: {metadata.get('company_name')}")
            print(f"Latest Version: {metadata.get('latest_version')}")
            print(f"Current Price: Rs. {metadata.get('current_price')}")
            print(f"Market Cap: Cr. {metadata.get('market_cap_cr')}")
            print(f"Face Value: {metadata.get('face_value')}")

            # Print latest years Profit & Loss
            pl = data.get("profit_loss", {})
            sales = pl.get("Sales", {})
            net_profit = pl.get("Net profit", {})
            if sales:
                sorted_dates = sorted(sales.keys())
                print("\nHistorical Annual Sales & Net Profit:")
                print(f"{'Date':<15} | {'Sales (Cr.)':<15} | {'Net Profit (Cr.)':<15}")
                print("-" * 53)
                for d in sorted_dates:
                    s_val = sales.get(d)
                    p_val = net_profit.get(d)
                    print(f"{d:<15} | {str(s_val):<15} | {str(p_val):<15}")

            # Print latest Quarters Sales
            quarters = data.get("quarters", {})
            q_sales = quarters.get("Sales", {})
            q_np = quarters.get("Net profit", {})
            if q_sales:
                sorted_q_dates = sorted(q_sales.keys())
                print("\nRecent Quarterly Sales & Net Profit:")
                print(f"{'Date':<15} | {'Sales (Cr.)':<15} | {'Net Profit (Cr.)':<15}")
                print("-" * 53)
                for d in sorted_q_dates:
                    s_val = q_sales.get(d)
                    p_val = q_np.get(d)
                    print(f"{d:<15} | {str(s_val):<15} | {str(p_val):<15}")
            print()

        return 0
    except Exception as exc:
        logger.error("Screener parsing failed: %s", exc)
        traceback.print_exc()
        return 1


def sync_screener(args: argparse.Namespace) -> int:
    from jobs.sync_screener import run_sync
    from settings import settings

    db_path = args.db_path or str(Path(settings.data_dir) / "screener_financials.db")
    master_db_path = args.master_db_path or str(Path(settings.data_dir) / "masterdata.db")

    try:
        run_sync(
            limit=args.limit,
            force=args.force,
            db_path=db_path,
            master_db_path=master_db_path,
            username=args.username,
            password=args.password,
            throttle_sec=args.throttle,
        )
        return 0
    except Exception as exc:
        logger.error("Sync screener failed: %s", exc)
        return 1


def migrate(args: argparse.Namespace) -> int:
    db = Database(args.db_path)
    try:
        from storage.migrations import apply_migrations

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

    screener_parser = subparsers.add_parser("parse-screener", help="Download and/or parse Screener.in company financials")
    screener_parser.add_argument("--ticker", help="Stock ticker (e.g. GOKEX)")
    screener_parser.add_argument("--file", help="Path to local Screener excel file to parse")
    screener_parser.add_argument("--output", help="Path to write parsed JSON output")
    screener_parser.add_argument("--force", action="store_true", help="Force download even if file exists")
    screener_parser.add_argument("--username", help="Screener.in username (overrides env / default)")
    screener_parser.add_argument("--password", help="Screener.in password (overrides env / default)")
    screener_parser.set_defaults(func=parse_screener)

    sync_screener_parser = subparsers.add_parser("sync-screener", help="Batch sync Screener.in company financials using masterdata.db")
    sync_screener_parser.add_argument("--limit", type=int, help="Limit the number of symbols to sync in this run")
    sync_screener_parser.add_argument("--force", action="store_true", help="Force re-download even if already synced")
    sync_screener_parser.add_argument("--db-path", help="Path to output SQLite financials database")
    sync_screener_parser.add_argument("--master-db-path", help="Path to input SQLite masterdata database")
    sync_screener_parser.add_argument("--username", help="Screener.in username (overrides env / default)")
    sync_screener_parser.add_argument("--password", help="Screener.in password (overrides env / default)")
    sync_screener_parser.add_argument("--throttle", type=float, default=2.0, help="Throttle delay in seconds between requests")
    sync_screener_parser.set_defaults(func=sync_screener)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
