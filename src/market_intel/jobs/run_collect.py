"""Standalone one-shot collection job.

Runs all enabled collectors once and prints a stats summary.  Designed to
be invoked directly (``python -m market_intel.jobs.run_collect``) or via the
systemd/launchd wrapper that calls it on a cron-style schedule.

Environment overrides:
  MARKET_INTEL_DB_PATH   — path to market_intel.duckdb (default from settings)
  MARKET_INTEL_SOURCES   — comma-separated source list, e.g. "nse_rss,nse_bulk_block"
                           omit to run all sources
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from market_intel.settings import settings
from market_intel.storage.db import Database
from market_intel.services.collection_service import CollectionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one collection cycle for all market_intel sources")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path),
        help="Path to market_intel.duckdb",
    )
    parser.add_argument(
        "--sources",
        default=os.environ.get("MARKET_INTEL_SOURCES", ""),
        help="Comma-separated source names to run (default: all)",
    )
    parser.add_argument(
        "--dry-run-alerts",
        action="store_true",
        help="Print alerts without sending to Telegram",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Explicitly reset and recreate the DuckDB store before collection.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    Path("./data/cache").mkdir(parents=True, exist_ok=True)
    Path("./data/exports").mkdir(parents=True, exist_ok=True)

    db = Database(args.db_path, fresh=bool(args.fresh))
    svc = CollectionService(db)

    sources: list[str] | None = None
    if args.sources:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    try:
        logger.info("Starting collection run (sources=%s)", sources or "all")
        summary = svc.run_collection(sources=sources)

        logger.info(
            "Collection complete: total=%d  rss=%d(new %d)  bulk_deal=%d  "
            "sast=%d  insider=%d  rating=%d  bse_corp=%d  failed=%d",
            summary["total"],
            summary["rss_processed"],
            summary["rss_new"],
            summary["bulk_deal_new"],
            summary["sast_new"],
            summary["insider_new"],
            summary["rating_new"],
            summary["bse_corp_new"],
            summary["failed"],
        )
        print(summary)
        try:
            state_repo = db.scheduler_state_repo()
            state_repo.get_or_create()
            state_repo.update_heartbeat(summary)
        except Exception as exc:
            logger.warning("Failed to update scheduler heartbeat: %s", exc)
        return 0
    except Exception as exc:
        logger.error("Collection run failed: %s", exc, exc_info=True)
        try:
            state_repo = db.scheduler_state_repo()
            state_repo.get_or_create()
            state_repo.increment_error()
        except Exception:
            pass
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
