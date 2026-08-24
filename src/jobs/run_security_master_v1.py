"""Operator CLI for the audited exchange-listing security master."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date

from services.security_master_service import SecurityMasterSyncService
from settings import settings
from storage.db import Database
from storage.security_master_repository import SecurityMasterRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain official NSE/BSE listing identity V1")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="Fetch and persist official active-equity listing masters")
    sync.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    sync.add_argument("--effective-date", type=date.fromisoformat, default=date.today())
    sync.add_argument("--exchanges", default="NSE,BSE")
    report = sub.add_parser("report", help="Report the latest completed cross-exchange identity snapshot")
    report.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = Database(args.db_path)
    try:
        if args.command == "report":
            print(json.dumps(SecurityMasterRepository(db).report(), indent=2))
            return 0
        if args.effective_date != date.today():
            raise SystemExit(
                "official NSE/BSE active-listing masters are current snapshots; "
                "--effective-date must equal today's observation date"
            )
        exchanges = [value.strip().upper() for value in args.exchanges.split(",") if value.strip()]
        unknown = set(exchanges) - {"NSE", "BSE"}
        if unknown:
            raise SystemExit(f"unsupported exchanges: {sorted(unknown)}")
        service = SecurityMasterSyncService(db)
        runs = [service.sync(exchange, effective_date=args.effective_date) for exchange in exchanges]
        report = SecurityMasterRepository(db).report()
        print(json.dumps({
            "policy": "market-intel-security-master-v1",
            "runs": runs,
            "current_snapshot": report,
        }, indent=2))
        return 0 if all(run["status"] == "COMPLETED" for run in runs) else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
