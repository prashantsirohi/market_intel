"""Resumable, cohort-targeted historical announcement backfill for J-curve research."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

import duckdb

from collectors.base import CollectorItem
from collectors.bse_corp import BseCorporateCollector
from collectors.nse_api import NseApiClient
from jobs.run_high_value_v1 import _enrich_listing_identity, _nse_items
from processing.high_value_filter import POLICY_HASH, POLICY_VERSION
from services.high_value_shadow_service import HighValueShadowService
from settings import settings
from storage.db import Database
from storage.jcurve_backfill_repository import JCurveBackfillRepository
from storage.security_master_repository import SecurityMasterRepository


BACKFILL_POLICY_VERSION = "market-intel-jcurve-targeted-backfill-v1"
SUPPORTED_SOURCES = ("nse_api", "bse_corp")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run targeted J-curve historical backfill V1")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "collect"):
        item = sub.add_parser(command)
        item.add_argument("--research-store", required=True, type=Path)
        item.add_argument("--discovery-run-id", required=True)
        item.add_argument("--from-date", required=True, type=date.fromisoformat)
        item.add_argument("--to-date", required=True, type=date.fromisoformat)
        item.add_argument("--sources", default=",".join(SUPPORTED_SOURCES))
        item.add_argument("--chunk-days", type=int, default=31)
        if command == "collect":
            item.add_argument(
                "--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path),
            )
            item.add_argument("--download-selected", action="store_true")
            item.add_argument(
                "--max-chunks", type=int,
                help="Process at most this many source chunks, then leave the run resumable",
            )
            item.add_argument("--continue-on-degraded", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    status.add_argument("--backfill-run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "status":
        db = Database(args.db_path)
        try:
            result = JCurveBackfillRepository(db).report(args.backfill_run_id)
        finally:
            db.close()
        print(json.dumps(result, indent=2, default=str))
        return 0
    sources = _sources(args.sources)
    if args.from_date > args.to_date:
        raise SystemExit("--from-date must not be after --to-date")
    if not 1 <= args.chunk_days <= 32:
        raise SystemExit("--chunk-days must be between 1 and 32")
    targets = load_discovery_targets(args.research_store, args.discovery_run_id)
    chunks = _chunks(args.from_date, args.to_date, args.chunk_days)
    cohort_hash = _hash(targets)
    plan = {
        "policy_version": BACKFILL_POLICY_VERSION,
        "filter_policy_version": POLICY_VERSION,
        "filter_policy_hash": POLICY_HASH,
        "discovery_run_id": args.discovery_run_id,
        "cohort_hash": cohort_hash,
        "target_count": len(targets),
        "requested_from": args.from_date,
        "requested_to": args.to_date,
        "sources": list(sources),
        "chunk_days": args.chunk_days,
        "date_chunk_count": len(chunks),
        "source_chunk_count": len(chunks) * len(sources),
        "acquisition_scope": "COMPLETE_EXCHANGE_METADATA_THEN_EXACT_COHORT_RETENTION",
        "cross_listing_dedup": "EXACT_ISIN_DATE_NORMALIZED_TITLE_NSE_PREFERRED",
    }
    if args.command == "plan":
        print(json.dumps(plan, indent=2, default=str))
        return 0
    result = run_backfill(
        db_path=Path(args.db_path), targets=targets, plan=plan,
        chunks=chunks, sources=sources, download_selected=args.download_selected,
        max_chunks=args.max_chunks, continue_on_degraded=args.continue_on_degraded,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] in {"COMPLETED", "RUNNING"} else 2


def load_discovery_targets(path: Path, discovery_run_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"research store not found: {path}")
    conn = duckdb.connect(str(path), read_only=True)
    try:
        run = conn.execute(
            """SELECT status FROM jcurve_discovery_run WHERE run_id = ?""",
            [discovery_run_id],
        ).fetchone()
        if not run or run[0] != "COMPLETED":
            raise ValueError(f"completed discovery run not found: {discovery_run_id}")
        rows = conn.execute(
            """SELECT company_id, isin, nse_symbol, bse_code, queue_rank
               FROM jcurve_discovery_candidate
               WHERE run_id = ? AND queue_disposition = 'PRIMARY_RESEARCH'
                 AND identity_status = 'RESOLVED'
               ORDER BY queue_rank, company_id""",
            [discovery_run_id],
        ).fetchall()
    finally:
        conn.close()
    targets = [
        {
            "company_id": str(row[0]), "isin": str(row[1]) if row[1] else None,
            "nse_symbol": str(row[2]).upper() if row[2] else None,
            "bse_code": str(row[3]) if row[3] else None, "queue_rank": int(row[4]),
        }
        for row in rows
    ]
    if not targets:
        raise ValueError("discovery run has no resolved primary research targets")
    company_ids = [row["company_id"] for row in targets]
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("discovery queue contains duplicate company identities")
    return targets


def run_backfill(
    *, db_path: Path, targets: list[dict[str, Any]], plan: dict[str, Any],
    chunks: list[tuple[date, date]], sources: tuple[str, ...],
    download_selected: bool, max_chunks: int | None, continue_on_degraded: bool,
) -> dict[str, Any]:
    material = {
        "policy": BACKFILL_POLICY_VERSION, "filter_hash": POLICY_HASH,
        "discovery_run_id": plan["discovery_run_id"], "cohort_hash": plan["cohort_hash"],
        "from": plan["requested_from"], "to": plan["requested_to"],
        "sources": sources, "chunk_days": plan["chunk_days"],
        "download_selected": download_selected,
    }
    backfill_run_id = f"jcurve-backfill-v1-{_hash(material)[:20]}"
    db = Database(str(db_path))
    repo = JCurveBackfillRepository(db)
    service = HighValueShadowService(db)
    security = SecurityMasterRepository(db)
    started_at = datetime.now(UTC)
    payload = {
        "backfill_run_id": backfill_run_id,
        "discovery_run_id": plan["discovery_run_id"], "cohort_hash": plan["cohort_hash"],
        "requested_from": plan["requested_from"], "requested_to": plan["requested_to"],
        "sources": list(sources), "chunk_days": plan["chunk_days"],
        "download_selected": download_selected, "chunk_count": len(chunks) * len(sources),
        "started_at": started_at,
    }
    repo.start_run(payload, targets)
    _require_security_master(security, sources)
    processed = 0
    halted = False
    try:
        # Newest chunks first so a partial run is immediately useful, while the
        # deterministic chunk key still makes the full run order-independent.
        for chunk_from, chunk_to in reversed(chunks):
            for source in sources:
                if repo.completed_chunk(
                    backfill_run_id=backfill_run_id, source=source,
                    requested_from=chunk_from, requested_to=chunk_to,
                ):
                    continue
                if max_chunks is not None and processed >= max_chunks:
                    halted = True
                    break
                result = _collect_chunk(
                    source=source, chunk_from=chunk_from, chunk_to=chunk_to,
                    targets=targets, service=service, security=security,
                    db=db, download_selected=download_selected,
                    backfill_run_id=backfill_run_id,
                )
                repo.record_chunk(
                    backfill_run_id=backfill_run_id, source=source,
                    requested_from=chunk_from, requested_to=chunk_to, result=result,
                )
                processed += 1
                if result["status"] != "COMPLETED" and not continue_on_degraded:
                    halted = True
                    break
            if halted:
                break
        report = repo.report(backfill_run_id)
    finally:
        db.close()
    report["processed_this_invocation"] = processed
    report["resumable"] = report["status"] != "COMPLETED"
    return report


def _collect_chunk(
    *, source: str, chunk_from: date, chunk_to: date,
    targets: list[dict[str, Any]], service: HighValueShadowService,
    security: SecurityMasterRepository, db: Database, download_selected: bool,
    backfill_run_id: str,
) -> dict[str, Any]:
    requested_from = datetime.combine(chunk_from, time.min)
    requested_to = datetime.combine(chunk_to, time.max)
    audit_context = {
        "backfill_policy_version": BACKFILL_POLICY_VERSION,
        "backfill_run_id": backfill_run_id,
        "cohort_hash": _hash(targets),
        "target_count": len(targets),
        "retention": "EXACT_ISIN_OR_EXCHANGE_IDENTIFIER",
    }
    try:
        if source == "nse_api":
            client = NseApiClient()
            rows, hashes, failures = client.fetch_window_with_coverage(chunk_from, chunk_to)
            all_items = _enrich_listing_identity(
                _nse_items(rows), exchange="NSE", repository=security,
            )
            retained = _retain_targets(all_items, targets, exchange="NSE")
            return service.run_source(
                source=source, items=retained, requested_from=requested_from,
                requested_to=requested_to, response_hashes=hashes, failures=failures,
                page_count=(chunk_to - chunk_from).days + 1,
                pages_complete=not failures, download_selected=download_selected,
                session=client.session, source_item_count=len(all_items),
                audit_context=audit_context,
            )
        client = BseCorporateCollector()
        all_items = _enrich_listing_identity(
            client.fetch_window(chunk_from, chunk_to), exchange="BSE", repository=security,
        )
        retained = _retain_targets(all_items, targets, exchange="BSE")
        nse_fingerprints = _existing_nse_fingerprints(
            db, chunk_from=chunk_from, chunk_to=chunk_to,
            target_isins={row["isin"] for row in targets if row.get("isin")},
        )
        before_dedup = len(retained)
        retained = [item for item in retained if _fingerprint(item) not in nse_fingerprints]
        result = service.run_source(
            source=source, items=retained, requested_from=requested_from,
            requested_to=requested_to, response_hashes=client.last_response_hashes,
            failures=client.last_failures, page_count=client.last_page_count,
            pages_complete=client.last_pages_complete, download_selected=download_selected,
            session=client.session, source_item_count=len(all_items),
            audit_context=audit_context,
        )
        result["cross_listing_duplicate_count"] = before_dedup - len(retained)
        return result
    except Exception as exc:
        return {
            "collection_run_id": None, "source": source, "status": "DEGRADED",
            "pages_complete": False, "item_count": 0, "target_item_count": 0,
            "new_count": 0, "selected_count": 0, "attachment_eligible_count": 0,
            "failure_count": 1, "failures": [{"error": str(exc)}],
        }


def _retain_targets(
    items: Iterable[CollectorItem], targets: list[dict[str, Any]], *, exchange: str,
) -> list[CollectorItem]:
    isins = {str(row["isin"]).upper() for row in targets if row.get("isin")}
    symbols = {
        str(row["nse_symbol"] if exchange == "NSE" else row["bse_code"]).upper()
        for row in targets
        if row.get("nse_symbol" if exchange == "NSE" else "bse_code")
    }
    retained = []
    for item in items:
        isin = str(item.isin or "").upper()
        listing = item.raw_payload.get("_listing_master") or {}
        exchange_id = str(listing.get("exchange_security_id") or item.symbol or "").upper()
        if (isin and isin in isins) or exchange_id in symbols:
            retained.append(replace(
                item,
                raw_payload={**item.raw_payload, "_jcurve_backfill": {
                    "policy_version": BACKFILL_POLICY_VERSION,
                    "identity_match": "ISIN" if isin in isins else exchange,
                }},
            ))
    return retained


def _existing_nse_fingerprints(
    db: Database, *, chunk_from: date, chunk_to: date, target_isins: set[str],
) -> set[str]:
    if not target_isins:
        return set()
    with db.get_connection(read_only=True) as conn:
        rows = conn.execute(
            """SELECT isin, title, published_at FROM raw_event
               WHERE source = 'nse_api' AND isin IN (SELECT unnest(?))
                 AND CAST(published_at AS DATE) BETWEEN ? AND ?""",
            [sorted(target_isins), chunk_from, chunk_to],
        ).fetchall()
    return {
        _fingerprint_parts(str(isin or ""), str(title or ""), published_at.date())
        for isin, title, published_at in rows
    }


def _fingerprint(item: CollectorItem) -> str:
    published = item.published_at or item.event_date
    published_date = published.date() if hasattr(published, "date") else date.min
    return _fingerprint_parts(str(item.isin or ""), str(item.title or ""), published_date)


def _fingerprint_parts(isin: str, title: str, published_date: date) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    return _hash([isin.upper(), published_date, normalized])


def _require_security_master(repository: SecurityMasterRepository, sources: tuple[str, ...]) -> None:
    available = {row["exchange"] for row in repository.report()["latest_runs"]}
    required = {"NSE" if source == "nse_api" else "BSE" for source in sources}
    missing = required - available
    if missing:
        raise ValueError(f"completed security-master snapshot required for {sorted(missing)}")


def _chunks(from_date: date, to_date: date, chunk_days: int) -> list[tuple[date, date]]:
    chunks = []
    current = from_date
    while current <= to_date:
        end = min(to_date, current + timedelta(days=chunk_days - 1))
        chunks.append((current, end))
        current = end + timedelta(days=1)
    return chunks


def _sources(value: str) -> tuple[str, ...]:
    requested = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    unknown = set(requested) - set(SUPPORTED_SOURCES)
    if not requested or unknown:
        raise SystemExit(f"unsupported sources: {sorted(unknown)}")
    return tuple(source for source in SUPPORTED_SOURCES if source in requested)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
