"""CLI for the metadata-first high-value announcement shadow policy."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

from collectors.base import CollectorItem
from collectors.bse_corp import BseCorporateCollector
from collectors.nse_api import NseApiClient
from processing.high_value_calibration import calibrate_cases
from processing.high_value_review_export import export_review_set
from services.high_value_shadow_service import HighValueShadowService
from settings import settings
from storage.db import Database
from storage.security_master_repository import SecurityMasterRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run high-value corporate-announcement filter V1")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="Collect metadata and persist shadow decisions")
    collect.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    collect.add_argument("--from-date", required=True, type=date.fromisoformat)
    collect.add_argument("--to-date", required=True, type=date.fromisoformat)
    collect.add_argument("--sources", default="nse_api,bse_corp")
    collect.add_argument("--download-selected", action="store_true")
    calibrate = sub.add_parser("calibrate", help="Measure V1 against reviewed JSON cases")
    calibrate.add_argument("--labels", required=True, type=Path)
    calibrate.add_argument(
        "--allow-partial", action="store_true",
        help="measure only labeled cases; partial results cannot promote the policy",
    )
    review = sub.add_parser("export-review", help="Export a deterministic stratified live review set")
    review.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    review.add_argument("--collection-run-ids", required=True)
    review.add_argument("--output", required=True, type=Path)
    review.add_argument("--cohort-file", type=Path)
    review.add_argument("--keep-sample", type=int, default=50)
    review.add_argument("--fetch-sample", type=int, default=50)
    review.add_argument("--drop-sample", type=int, default=100)
    review.add_argument("--seed", default="market-intel-high-value-review-v1")
    return parser


def _nse_items(rows) -> list[CollectorItem]:
    return [
        CollectorItem(
            source="nse_api", source_type="api", external_id=row.seq_no or None,
            symbol=row.symbol or None, company_name=row.company_name or None, isin=row.isin,
            title=row.subject, description=row.details, event_date=row.announce_date,
            published_at=row.announce_date, link=row.attachment_url,
            attachment_url=row.attachment_url, raw_payload=row.raw,
        )
        for row in rows
    ]


def _enrich_listing_identity(
    items: list[CollectorItem], *, exchange: str, repository: SecurityMasterRepository,
) -> list[CollectorItem]:
    enriched: list[CollectorItem] = []
    for item in items:
        if exchange == "BSE":
            identity = repository.resolve_current(
                exchange="BSE", exchange_security_id=item.symbol,
            )
        else:
            identity = repository.resolve_current(
                exchange="NSE", symbol=item.symbol, isin=None,
            ) if item.symbol else None
            if identity is None and item.isin:
                identity = repository.resolve_current(exchange="NSE", isin=item.isin)
        if identity is None:
            enriched.append(item)
            continue
        membership = identity.get("listing_membership")
        canonical_symbol = identity.get("nse_symbol") or identity.get("symbol") or item.symbol
        listing_evidence = {
            "policy_version": "market-intel-security-master-v1",
            "exchange": exchange,
            "exchange_security_id": identity.get("exchange_security_id"),
            "listing_membership": membership,
            "identity_status": identity.get("identity_status"),
        }
        enriched.append(replace(
            item,
            symbol=canonical_symbol,
            isin=identity.get("isin") or item.isin,
            company_name=identity.get("company_name") or item.company_name,
            raw_payload={**item.raw_payload, "_listing_master": listing_evidence},
        ))
    return enriched


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "calibrate":
        payload = json.loads(args.labels.read_text(encoding="utf-8"))
        cases = payload.get("cases") if isinstance(payload, dict) else payload
        if not isinstance(cases, list):
            raise SystemExit("calibration not ready: labels JSON must contain a cases list")
        try:
            result = calibrate_cases(cases, allow_partial=args.allow_partial)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"calibration not ready: {exc}") from None
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "export-review":
        run_ids = [value.strip() for value in args.collection_run_ids.split(",") if value.strip()]
        result = export_review_set(
            db_path=Path(args.db_path), output_path=args.output,
            collection_run_ids=run_ids, keep_sample=args.keep_sample,
            fetch_sample=args.fetch_sample, drop_sample=args.drop_sample,
            cohort_file=args.cohort_file, seed=args.seed,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.from_date > args.to_date:
        raise SystemExit("--from-date must not be after --to-date")
    if (args.to_date - args.from_date).days > 31:
        raise SystemExit("V1 shadow collection is limited to 32 calendar days per run")
    # market_intel's DuckDB contract stores UTC wall-clock TIMESTAMP values
    # without timezone metadata. Keep the coverage window naive for the same
    # reason as raw_event.published_at.
    requested_from = datetime.combine(args.from_date, time.min)
    requested_to = datetime.combine(args.to_date, time.max)
    wanted = {value.strip() for value in args.sources.split(",") if value.strip()}
    unknown = wanted - {"nse_api", "bse_corp"}
    if unknown:
        raise SystemExit(f"unsupported sources: {sorted(unknown)}")
    db = Database(args.db_path)
    service = HighValueShadowService(db)
    listing_repository = SecurityMasterRepository(db)
    results = []
    try:
        listing_report = listing_repository.report()
        available_exchanges = {
            row["exchange"] for row in listing_report["latest_runs"]
        }
        required_exchanges = set()
        if "nse_api" in wanted:
            required_exchanges.add("NSE")
        if "bse_corp" in wanted:
            required_exchanges.add("BSE")
        missing_exchanges = required_exchanges - available_exchanges
        if missing_exchanges:
            raise SystemExit(
                "completed security-master snapshot required for exchanges: "
                f"{sorted(missing_exchanges)}; run jobs.run_security_master_v1 sync first"
            )
        if "nse_api" in wanted:
            client = NseApiClient()
            rows, hashes, failures = client.fetch_window_with_coverage(args.from_date, args.to_date)
            items = _enrich_listing_identity(
                _nse_items(rows), exchange="NSE", repository=listing_repository,
            )
            results.append(service.run_source(
                source="nse_api", items=items, requested_from=requested_from,
                requested_to=requested_to, response_hashes=hashes, failures=failures,
                page_count=(args.to_date - args.from_date).days + 1,
                pages_complete=not failures, download_selected=args.download_selected,
                session=client.session,
            ))
        if "bse_corp" in wanted:
            client = BseCorporateCollector()
            rows = client.fetch_window(args.from_date, args.to_date)
            items = _enrich_listing_identity(
                rows, exchange="BSE", repository=listing_repository,
            )
            results.append(service.run_source(
                source="bse_corp", items=items, requested_from=requested_from,
                requested_to=requested_to, response_hashes=client.last_response_hashes,
                failures=client.last_failures, page_count=client.last_page_count,
                pages_complete=client.last_pages_complete,
                download_selected=args.download_selected, session=client.session,
            ))
    finally:
        db.close()
    print(json.dumps({"policy": "market-intel-high-value-filter-v1", "runs": results}, indent=2))
    return 0 if all(row["status"] == "COMPLETED" for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
