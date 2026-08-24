"""Persistence for immutable high-value-filter shadow evidence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from processing.high_value_filter import FilterDecision, attachment_filename
from storage.db import Database


class HighValueShadowRepository:
    def __init__(self, db: Database):
        self.db = db

    def start_run(
        self,
        *,
        collection_run_id: str,
        source: str,
        requested_from: datetime | None,
        requested_to: datetime | None,
        started_at: datetime,
        policy_version: str,
        policy_hash: str,
    ) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO announcement_collection_run (
                    collection_run_id, source, requested_from, requested_to,
                    started_at, status, policy_version, policy_hash
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, ?)
                """,
                [collection_run_id, source, requested_from, requested_to, started_at, policy_version, policy_hash],
            )

    def record_decision(
        self,
        *,
        collection_run_id: str,
        announcement_key: str,
        raw_event_id: int | None,
        source: str,
        external_id: str | None,
        symbol: str | None,
        isin: str | None,
        listing_membership: str | None,
        exchange_security_id: str | None,
        subject: str | None,
        details: str | None,
        attachment_url: str | None,
        result: FilterDecision,
    ) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO announcement_filter_decision (
                    collection_run_id, announcement_key, raw_event_id, source,
                    external_id, symbol, isin, listing_membership,
                    exchange_security_id, subject, details, attachment_url,
                    attachment_filename, decision, attachment_eligible,
                    reason_codes_json, matched_signals_json, policy_version,
                    policy_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    collection_run_id, announcement_key, raw_event_id, source,
                    external_id, symbol, isin, listing_membership,
                    exchange_security_id, subject, details, attachment_url,
                    attachment_filename(attachment_url), result.decision,
                    result.attachment_eligible, json.dumps(result.reason_codes),
                    json.dumps(result.matched_signals), result.policy_version,
                    result.policy_hash,
                ],
            )

    def finish_run(
        self,
        *,
        collection_run_id: str,
        completed_at: datetime,
        status: str,
        page_count: int,
        pages_complete: bool,
        item_count: int,
        new_count: int,
        selected_count: int,
        attachment_eligible_count: int,
        response_hashes: list[str],
        failures: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE announcement_collection_run SET
                    completed_at = ?, status = ?, page_count = ?,
                    pages_complete = ?, item_count = ?, new_count = ?,
                    selected_count = ?, attachment_eligible_count = ?,
                    failure_count = ?, response_hashes_json = ?, failures_json = ?,
                    summary_json = ?
                WHERE collection_run_id = ?
                """,
                [
                    completed_at, status, page_count, pages_complete, item_count,
                    new_count, selected_count, attachment_eligible_count,
                    len(failures), json.dumps(response_hashes),
                    json.dumps(failures, default=str), json.dumps(summary, default=str),
                    collection_run_id,
                ],
            )

    def load_run(self, collection_run_id: str) -> dict[str, Any] | None:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM announcement_collection_run WHERE collection_run_id = ?",
                [collection_run_id],
            ).fetchone()
            if not row:
                return None
            columns = [column[0] for column in conn.description]
        return dict(zip(columns, row))

    def load_decisions(self, collection_run_id: str) -> list[dict[str, Any]]:
        with self.db.get_connection(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT announcement_key, raw_event_id, source, external_id, symbol,
                       isin, listing_membership, exchange_security_id, subject,
                       attachment_filename, decision, attachment_eligible,
                       reason_codes_json, matched_signals_json, policy_version, policy_hash
                FROM announcement_filter_decision
                WHERE collection_run_id = ?
                ORDER BY decision_id
                """,
                [collection_run_id],
            ).fetchall()
        return [
            {
                "announcement_key": row[0], "raw_event_id": row[1], "source": row[2],
                "external_id": row[3], "symbol": row[4],
                "isin": row[5], "listing_membership": row[6],
                "exchange_security_id": row[7], "subject": row[8],
                "attachment_filename": row[9], "decision": row[10],
                "attachment_eligible": bool(row[11]),
                "reason_codes": json.loads(row[12]), "matched_signals": json.loads(row[13]),
                "policy_version": row[14], "policy_hash": row[15],
            }
            for row in rows
        ]
