"""Persistence and exact lookup for security-master V1."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from collectors.security_master import ListingDataset, PARSER_VERSION, SCHEMA_VERSION


class SecurityMasterRepository:
    def __init__(self, db):
        self.db = db

    def persist_dataset(
        self,
        *,
        sync_run_id: str,
        dataset: ListingDataset,
        started_at: datetime,
        completed_at: datetime,
    ) -> dict[str, Any]:
        records = list(dataset.records)
        keys = [record.exchange_security_id for record in records]
        duplicate_count = len(keys) - len(set(keys))
        valid_count = sum(record.identity_status == "VALID_ISIN" for record in records)
        invalid_count = len(records) - valid_count
        status = "COMPLETED" if records and duplicate_count == 0 else "DEGRADED"
        error_code = None if status == "COMPLETED" else "DUPLICATE_LISTING_KEY" if duplicate_count else "EMPTY_SOURCE"
        summary = {
            "exchange": dataset.exchange,
            "row_count": len(records),
            "valid_isin_count": valid_count,
            "invalid_isin_count": invalid_count,
            "duplicate_key_count": duplicate_count,
            "temporal_trust": "LATEST_ONLY_OBSERVED_AT_SYNC",
        }
        with self.db.get_connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute(
                    """
                    INSERT INTO listing_sync_run (
                        sync_run_id, exchange, effective_date, started_at,
                        completed_at, status, row_count, valid_isin_count,
                        invalid_isin_count, duplicate_key_count, source_url,
                        source_hash, parser_version, schema_version, error_code,
                        temporal_trust, summary_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        sync_run_id, dataset.exchange, dataset.effective_date,
                        started_at, completed_at, status, len(records), valid_count,
                        invalid_count, duplicate_count, dataset.source_url,
                        dataset.source_hash, PARSER_VERSION, SCHEMA_VERSION,
                        error_code, "LATEST_ONLY_OBSERVED_AT_SYNC",
                        json.dumps(summary, sort_keys=True),
                    ],
                )
                if duplicate_count == 0:
                    conn.executemany(
                        """
                        INSERT INTO listed_security_observation (
                            sync_run_id, exchange, exchange_security_id, symbol,
                            isin, company_name, series, board, listing_date,
                            active_flag, instrument_type, identity_status,
                            source_row_hash, observed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [[
                            sync_run_id, record.exchange, record.exchange_security_id,
                            record.symbol, record.isin, record.company_name,
                            record.series, record.board, record.listing_date,
                            record.active_flag, record.instrument_type,
                            record.identity_status, record.source_row_hash, completed_at,
                        ] for record in records],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {**summary, "sync_run_id": sync_run_id, "status": status, "source_hash": dataset.source_hash}

    def persist_failure(
        self,
        *,
        sync_run_id: str,
        exchange: str,
        effective_date,
        started_at: datetime,
        completed_at: datetime,
        source_url: str,
        error: Exception,
    ) -> dict[str, Any]:
        message = str(error)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO listing_sync_run (
                    sync_run_id, exchange, effective_date, started_at,
                    completed_at, status, source_url, parser_version,
                    schema_version, temporal_trust, error_code, error_message,
                    summary_json
                ) VALUES (?, ?, ?, ?, ?, 'DEGRADED', ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    sync_run_id, exchange, effective_date, started_at, completed_at,
                    source_url, PARSER_VERSION, SCHEMA_VERSION,
                    "LATEST_ONLY_OBSERVED_AT_SYNC",
                    type(error).__name__.upper(), message,
                    json.dumps({"exchange": exchange, "error": message}, sort_keys=True),
                ],
            )
        return {
            "sync_run_id": sync_run_id, "exchange": exchange,
            "status": "DEGRADED", "row_count": 0,
            "valid_isin_count": 0, "invalid_isin_count": 0,
            "duplicate_key_count": 0,
            "temporal_trust": "LATEST_ONLY_OBSERVED_AT_SYNC",
            "error": message,
        }

    def resolve_current(
        self,
        *,
        exchange: str,
        exchange_security_id: str | None = None,
        symbol: str | None = None,
        isin: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_exchange = exchange.upper()
        with self.db.get_connection(read_only=True) as conn:
            if isin:
                rows = conn.execute(
                    """
                    SELECT current.exchange_security_id, current.symbol, current.isin,
                           current.company_name, membership.nse_symbol,
                           membership.bse_symbol, membership.bse_code,
                           membership.listing_membership, membership.identity_status
                    FROM listed_security_current current
                    LEFT JOIN security_listing_membership_current membership
                      ON membership.isin = current.isin
                    WHERE current.exchange = ? AND current.isin = ?
                    ORDER BY current.exchange_security_id
                    """,
                    [normalized_exchange, isin.upper()],
                ).fetchall()
            elif exchange_security_id:
                rows = conn.execute(
                    """
                    SELECT current.exchange_security_id, current.symbol, current.isin,
                           current.company_name, membership.nse_symbol,
                           membership.bse_symbol, membership.bse_code,
                           membership.listing_membership, membership.identity_status
                    FROM listed_security_current current
                    LEFT JOIN security_listing_membership_current membership
                      ON membership.isin = current.isin
                    WHERE current.exchange = ? AND current.exchange_security_id = ?
                    """,
                    [normalized_exchange, exchange_security_id],
                ).fetchall()
            elif symbol:
                rows = conn.execute(
                    """
                    SELECT current.exchange_security_id, current.symbol, current.isin,
                           current.company_name, membership.nse_symbol,
                           membership.bse_symbol, membership.bse_code,
                           membership.listing_membership, membership.identity_status
                    FROM listed_security_current current
                    LEFT JOIN security_listing_membership_current membership
                      ON membership.isin = current.isin
                    WHERE current.exchange = ? AND upper(current.symbol) = ?
                    ORDER BY current.exchange_security_id
                    """,
                    [normalized_exchange, symbol.upper()],
                ).fetchall()
            else:
                return None
        if len(rows) != 1:
            return None
        row = rows[0]
        return {
            "exchange": normalized_exchange,
            "exchange_security_id": row[0], "symbol": row[1], "isin": row[2],
            "company_name": row[3], "nse_symbol": row[4], "bse_symbol": row[5],
            "bse_code": row[6], "listing_membership": row[7],
            "identity_status": row[8],
        }

    def report(self) -> dict[str, Any]:
        with self.db.get_connection(read_only=True) as conn:
            runs = conn.execute(
                """
                SELECT exchange, sync_run_id, effective_date, completed_at, row_count,
                       valid_isin_count, invalid_isin_count, source_hash, temporal_trust
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY exchange
                        ORDER BY effective_date DESC, completed_at DESC, sync_run_id DESC
                    ) AS ordinal
                    FROM listing_sync_run WHERE status = 'COMPLETED'
                ) WHERE ordinal = 1 ORDER BY exchange
                """
            ).fetchall()
            membership = conn.execute(
                """
                SELECT listing_membership, count(*)
                FROM security_listing_membership_current
                GROUP BY listing_membership ORDER BY listing_membership
                """
            ).fetchall()
            ambiguous = conn.execute(
                "SELECT count(*) FROM security_listing_membership_current WHERE identity_status <> 'RESOLVED'"
            ).fetchone()[0]
        payload = {
            "policy_version": "market-intel-security-master-v1",
            "latest_runs": [{
                "exchange": row[0], "sync_run_id": row[1],
                "effective_date": str(row[2]), "completed_at": str(row[3]),
                "row_count": row[4], "valid_isin_count": row[5],
                "invalid_isin_count": row[6], "source_hash": row[7],
                "temporal_trust": row[8],
            } for row in runs],
            "membership_counts": {row[0]: row[1] for row in membership},
            "ambiguous_identity_count": ambiguous,
            "temporal_trust": "LATEST_ONLY_OBSERVED_AT_SYNC",
        }
        payload["snapshot_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        return payload
