"""Deterministic, auditable review exports for high-value-filter calibration."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


REVIEW_EXPORT_VERSION = "market-intel-high-value-review-v1"
_DECISIONS = ("KEEP", "FETCH_ATTACHMENT", "DROP_METADATA_ONLY")


def _stable_score(seed: str, announcement_key: str) -> str:
    return hashlib.sha256(f"{seed}|{announcement_key}".encode()).hexdigest()


def _load_cohort(path: Path | None) -> tuple[set[str], dict[str, Any] | None]:
    if path is None:
        return set(), None
    payload = json.loads(path.read_text(encoding="utf-8"))
    members = payload.get("members") if isinstance(payload, dict) else None
    if not isinstance(members, list):
        raise ValueError("cohort file must contain a members array")
    isins = {str(member.get("isin") or "").strip().upper() for member in members}
    isins.discard("")
    if not isins:
        raise ValueError("cohort file contains no usable ISIN values")
    return isins, {
        "cohort_version": payload.get("cohort_version"),
        "cohort_file": str(path.resolve()),
        "cohort_isin_count": len(isins),
    }


def _rows(connection, run_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    receipts = connection.execute(
        """
        SELECT collection_run_id, source, requested_from, requested_to, status,
               pages_complete, item_count, selected_count,
               attachment_eligible_count, failure_count, policy_version,
               policy_hash
        FROM announcement_collection_run
        WHERE collection_run_id IN (SELECT UNNEST(?))
        ORDER BY source, collection_run_id
        """,
        [run_ids],
    ).fetchall()
    receipt_columns = [column[0] for column in connection.description]
    receipt_rows = [dict(zip(receipt_columns, row)) for row in receipts]

    decisions = connection.execute(
        """
        SELECT d.collection_run_id, d.announcement_key, d.raw_event_id,
               d.source, d.external_id, d.symbol, d.isin,
               coalesce(d.listing_membership, 'UNRESOLVED') AS listing_membership,
               d.exchange_security_id, coalesce(r.company_name, '') AS company_name,
               d.subject, d.details, r.published_at, d.attachment_url,
               d.attachment_filename, d.decision, d.attachment_eligible,
               d.reason_codes_json, d.matched_signals_json,
               d.policy_version, d.policy_hash
        FROM announcement_filter_decision d
        LEFT JOIN raw_event r ON r.raw_event_id = d.raw_event_id
        WHERE d.collection_run_id IN (SELECT UNNEST(?))
        ORDER BY d.source, d.decision, d.announcement_key
        """,
        [run_ids],
    ).fetchall()
    decision_columns = [column[0] for column in connection.description]
    decision_rows = [dict(zip(decision_columns, row)) for row in decisions]
    return receipt_rows, decision_rows


def _round_robin_stratified(
    rows: list[dict[str, Any]], *, decision: str, quota: int, seed: str,
) -> list[dict[str, Any]]:
    if quota <= 0:
        return []
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["decision"] == decision:
            strata[(row["source"], row["listing_membership"])].append(row)
    for stratum_rows in strata.values():
        stratum_rows.sort(key=lambda row: _stable_score(seed, row["announcement_key"]))
    selected: list[dict[str, Any]] = []
    ordered_keys = sorted(strata)
    while len(selected) < quota:
        progressed = False
        for key in ordered_keys:
            if strata[key] and len(selected) < quota:
                selected.append(strata[key].pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def _case(row: dict[str, Any], sample_reasons: set[str]) -> dict[str, Any]:
    published = row.get("published_at")
    return {
        "case_id": row["announcement_key"],
        "collection_run_id": row["collection_run_id"],
        "raw_event_id": row.get("raw_event_id"),
        "source": row["source"],
        "external_id": row.get("external_id"),
        "symbol": row.get("symbol"),
        "isin": row.get("isin"),
        "listing_membership": row["listing_membership"],
        "exchange_security_id": row.get("exchange_security_id"),
        "company_name": row.get("company_name") or None,
        "published_at": published.isoformat() if hasattr(published, "isoformat") else published,
        "subject": row.get("subject"),
        "details": row.get("details"),
        "attachment_url": row.get("attachment_url"),
        "attachment_filename": row.get("attachment_filename"),
        "predicted_decision": row["decision"],
        "predicted_attachment_eligible": bool(row["attachment_eligible"]),
        "reason_codes": json.loads(row["reason_codes_json"]),
        "matched_signals": json.loads(row["matched_signals_json"]),
        "sample_reasons": sorted(sample_reasons),
        "expected": None,
        "reviewer_note": None,
    }


def export_review_set(
    *,
    db_path: Path,
    output_path: Path,
    collection_run_ids: list[str],
    keep_sample: int = 50,
    fetch_sample: int = 50,
    drop_sample: int = 100,
    cohort_file: Path | None = None,
    seed: str = REVIEW_EXPORT_VERSION,
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"review export already exists: {output_path}")
    if not collection_run_ids or len(collection_run_ids) != len(set(collection_run_ids)):
        raise ValueError("collection run IDs must be non-empty and unique")
    if any(value < 0 for value in (keep_sample, fetch_sample, drop_sample)):
        raise ValueError("sample quotas must not be negative")
    cohort_isins, cohort_metadata = _load_cohort(cohort_file)

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        receipts, rows = _rows(connection, collection_run_ids)
    finally:
        connection.close()
    observed_run_ids = {row["collection_run_id"] for row in receipts}
    missing_runs = sorted(set(collection_run_ids) - observed_run_ids)
    if missing_runs:
        raise ValueError(f"collection run IDs not found: {missing_runs}")
    invalid_receipts = [
        row["collection_run_id"] for row in receipts
        if row["status"] != "COMPLETED" or not row["pages_complete"] or row["failure_count"]
    ]
    if invalid_receipts:
        raise ValueError(f"review export requires complete source receipts: {invalid_receipts}")

    quotas = {
        "KEEP": keep_sample,
        "FETCH_ATTACHMENT": fetch_sample,
        "DROP_METADATA_ONLY": drop_sample,
    }
    selected: dict[str, tuple[dict[str, Any], set[str]]] = {}
    for decision in _DECISIONS:
        for row in _round_robin_stratified(rows, decision=decision, quota=quotas[decision], seed=seed):
            selected[row["announcement_key"]] = (row, {f"STRATIFIED_{decision}"})
    if cohort_isins:
        for row in rows:
            if str(row.get("isin") or "").upper() not in cohort_isins:
                continue
            existing = selected.get(row["announcement_key"])
            if existing:
                existing[1].add("COHORT_ALL")
            else:
                selected[row["announcement_key"]] = (row, {"COHORT_ALL"})

    cases = [
        _case(row, reasons)
        for row, reasons in sorted(
            selected.values(),
            key=lambda item: (item[0]["source"], item[0]["decision"], item[0]["announcement_key"]),
        )
    ]
    population_counts = Counter((row["source"], row["decision"], row["listing_membership"]) for row in rows)
    sample_counts = Counter((case["source"], case["predicted_decision"], case["listing_membership"]) for case in cases)
    unresolved_count = sum(row["listing_membership"] == "UNRESOLVED" for row in rows)
    payload: dict[str, Any] = {
        "review_export_version": REVIEW_EXPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "collection_run_ids": collection_run_ids,
        "source_receipts": receipts,
        "selection_policy": {
            "quotas": quotas,
            "strata": ["source", "listing_membership"],
            "cohort": cohort_metadata,
        },
        "population_summary": {
            "announcement_count": len(rows),
            "unresolved_identity_count": unresolved_count,
            "unresolved_identity_rate": unresolved_count / len(rows) if rows else None,
            "counts": [
                {"source": key[0], "decision": key[1], "listing_membership": key[2], "count": count}
                for key, count in sorted(population_counts.items())
            ],
        },
        "sample_summary": {
            "case_count": len(cases),
            "unlabeled_count": len(cases),
            "counts": [
                {"source": key[0], "decision": key[1], "listing_membership": key[2], "count": count}
                for key, count in sorted(sample_counts.items())
            ],
        },
        "cases": cases,
    }
    payload["dataset_hash"] = hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return {
        "output_path": str(output_path.resolve()),
        "dataset_hash": payload["dataset_hash"],
        "population_count": len(rows),
        "case_count": len(cases),
        "unresolved_identity_count": unresolved_count,
        "unresolved_identity_rate": payload["population_summary"]["unresolved_identity_rate"],
        "cohort_case_count": sum("COHORT_ALL" in case["sample_reasons"] for case in cases),
        "status": "COMPLETED",
    }
