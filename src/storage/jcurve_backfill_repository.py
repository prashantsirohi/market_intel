"""Immutable/resumable receipts for J-curve targeted historical backfills."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any


class JCurveBackfillRepository:
    def __init__(self, db):
        self.db = db

    def start_run(self, payload: dict[str, Any], targets: list[dict[str, Any]]) -> bool:
        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT status FROM jcurve_targeted_backfill_run WHERE backfill_run_id = ?",
                [payload["backfill_run_id"]],
            ).fetchone()
            if existing:
                return False
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute(
                    """INSERT INTO jcurve_targeted_backfill_run (
                       backfill_run_id, discovery_run_id, cohort_hash,
                       requested_from, requested_to, sources_json, chunk_days,
                       download_selected, status, target_count, chunk_count, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?, ?)""",
                    [payload["backfill_run_id"], payload["discovery_run_id"],
                     payload["cohort_hash"], payload["requested_from"], payload["requested_to"],
                     json.dumps(payload["sources"]), payload["chunk_days"],
                     payload["download_selected"], len(targets), payload["chunk_count"],
                     payload["started_at"]],
                )
                for target in targets:
                    conn.execute(
                        """INSERT INTO jcurve_targeted_backfill_target VALUES
                           (?, ?, ?, ?, ?, ?)""",
                        [payload["backfill_run_id"], target["company_id"], target.get("isin"),
                         target.get("nse_symbol"), target.get("bse_code"), target["queue_rank"]],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return True

    def completed_chunk(
        self, *, backfill_run_id: str, source: str,
        requested_from: date, requested_to: date,
    ) -> bool:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT status FROM jcurve_targeted_backfill_chunk
                   WHERE backfill_run_id = ? AND source = ?
                     AND requested_from = ? AND requested_to = ?""",
                [backfill_run_id, source, requested_from, requested_to],
            ).fetchone()
        return bool(row and row[0] == "COMPLETED")

    def record_chunk(
        self, *, backfill_run_id: str, source: str,
        requested_from: date, requested_to: date, result: dict[str, Any],
    ) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO jcurve_targeted_backfill_chunk VALUES (
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (backfill_run_id, source, requested_from, requested_to)
                   DO UPDATE SET collection_run_id = excluded.collection_run_id,
                     status = excluded.status, pages_complete = excluded.pages_complete,
                     source_item_count = excluded.source_item_count,
                     target_item_count = excluded.target_item_count,
                     new_item_count = excluded.new_item_count,
                     selected_count = excluded.selected_count,
                     attachment_eligible_count = excluded.attachment_eligible_count,
                     failure_count = excluded.failure_count,
                     result_json = excluded.result_json, completed_at = excluded.completed_at""",
                [backfill_run_id, source, requested_from, requested_to,
                 result.get("collection_run_id"), result["status"], result["pages_complete"],
                 result.get("item_count", 0), result.get("target_item_count", 0),
                 result.get("new_count", 0), result.get("selected_count", 0),
                 result.get("attachment_eligible_count", 0), result.get("failure_count", 0),
                 json.dumps(result, default=str), datetime.now()],
            )
            self._refresh(conn, backfill_run_id)

    def report(self, backfill_run_id: str) -> dict[str, Any]:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM jcurve_targeted_backfill_run WHERE backfill_run_id = ?",
                [backfill_run_id],
            ).fetchone()
            if not row:
                raise ValueError(f"backfill run not found: {backfill_run_id}")
            columns = [column[0] for column in conn.description]
            chunks = conn.execute(
                """SELECT source, requested_from, requested_to, status,
                          source_item_count, target_item_count, new_item_count, failure_count
                   FROM jcurve_targeted_backfill_chunk
                   WHERE backfill_run_id = ? ORDER BY requested_from, source""",
                [backfill_run_id],
            ).fetchall()
        payload = dict(zip(columns, row))
        payload["sources"] = json.loads(payload.pop("sources_json"))
        payload["chunks"] = [
            dict(zip(
                ("source", "requested_from", "requested_to", "status", "source_item_count",
                 "target_item_count", "new_item_count", "failure_count"),
                chunk,
            ))
            for chunk in chunks
        ]
        return payload

    def start_attachment_run(self, payload: dict[str, Any]) -> bool:
        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT status FROM jcurve_attachment_ingestion_run WHERE attachment_run_id = ?",
                [payload["attachment_run_id"]],
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """INSERT INTO jcurve_attachment_ingestion_run (
                   attachment_run_id, parent_backfill_run_id, policy_version,
                   policy_hash, candidate_hash, status, candidate_count, started_at
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, ?)""",
                [payload["attachment_run_id"], payload["parent_backfill_run_id"],
                 payload["policy_version"], payload["policy_hash"],
                 payload["candidate_hash"], payload["candidate_count"],
                 payload["started_at"]],
            )
            self._refresh_attachment(conn, payload["attachment_run_id"])
        return True

    def attachment_item_complete(self, *, attachment_run_id: str, raw_event_id: int) -> bool:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                """SELECT status FROM jcurve_attachment_ingestion_item
                   WHERE attachment_run_id = ? AND raw_event_id = ?""",
                [attachment_run_id, raw_event_id],
            ).fetchone()
        return bool(row and row[0] in {"VALID", "REUSED_VALID", "FAILED"})

    def record_attachment_item(
        self, *, attachment_run_id: str, candidate: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """INSERT INTO jcurve_attachment_ingestion_item VALUES (
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (attachment_run_id, raw_event_id) DO UPDATE SET
                     status = excluded.status, document_id = excluded.document_id,
                     content_hash = excluded.content_hash, file_size = excluded.file_size,
                     error_message = excluded.error_message,
                     completed_at = excluded.completed_at""",
                [attachment_run_id, candidate["raw_event_id"], candidate["source"],
                 candidate["attachment_url"], json.dumps(candidate["matched_signals"]),
                 candidate["selection_reason"], result["status"],
                 result.get("document_id"), result.get("content_hash"),
                 result.get("file_size"), result.get("error_message"), datetime.now()],
            )
            self._refresh_attachment(conn, attachment_run_id)

    def attachment_report(self, attachment_run_id: str) -> dict[str, Any]:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM jcurve_attachment_ingestion_run WHERE attachment_run_id = ?",
                [attachment_run_id],
            ).fetchone()
            if not row:
                raise ValueError(f"attachment ingestion run not found: {attachment_run_id}")
            columns = [column[0] for column in conn.description]
            statuses = conn.execute(
                """SELECT status, count(*) FROM jcurve_attachment_ingestion_item
                   WHERE attachment_run_id = ? GROUP BY status ORDER BY status""",
                [attachment_run_id],
            ).fetchall()
        payload = dict(zip(columns, row))
        payload["status_counts"] = {status: count for status, count in statuses}
        return payload

    @staticmethod
    def _refresh(conn, backfill_run_id: str) -> None:
        counts = conn.execute(
            """SELECT count(*) FILTER (WHERE status = 'COMPLETED'),
                      count(*) FILTER (WHERE status <> 'COMPLETED'),
                      coalesce(sum(source_item_count), 0),
                      coalesce(sum(target_item_count), 0),
                      coalesce(sum(new_item_count), 0)
               FROM jcurve_targeted_backfill_chunk WHERE backfill_run_id = ?""",
            [backfill_run_id],
        ).fetchone()
        total = conn.execute(
            "SELECT chunk_count FROM jcurve_targeted_backfill_run WHERE backfill_run_id = ?",
            [backfill_run_id],
        ).fetchone()[0]
        finished = int(counts[0]) + int(counts[1])
        status = "RUNNING"
        completed_at = None
        if finished >= int(total):
            status = "COMPLETED" if int(counts[1]) == 0 else "DEGRADED"
            completed_at = datetime.now()
        conn.execute(
            """UPDATE jcurve_targeted_backfill_run SET
                 completed_chunk_count = ?, degraded_chunk_count = ?,
                 source_item_count = ?, target_item_count = ?, new_item_count = ?,
                 status = ?, completed_at = ? WHERE backfill_run_id = ?""",
            [counts[0], counts[1], counts[2], counts[3], counts[4], status,
             completed_at, backfill_run_id],
        )

    @staticmethod
    def _refresh_attachment(conn, attachment_run_id: str) -> None:
        counts = conn.execute(
            """SELECT count(*),
                      count(*) FILTER (WHERE status IN ('VALID', 'REUSED_VALID')),
                      count(*) FILTER (WHERE status = 'FAILED')
               FROM jcurve_attachment_ingestion_item WHERE attachment_run_id = ?""",
            [attachment_run_id],
        ).fetchone()
        candidate_count = conn.execute(
            """SELECT candidate_count FROM jcurve_attachment_ingestion_run
               WHERE attachment_run_id = ?""",
            [attachment_run_id],
        ).fetchone()[0]
        completed_count = int(counts[0])
        status = "RUNNING"
        completed_at = None
        if completed_count >= int(candidate_count):
            status = "COMPLETED" if int(counts[2]) == 0 else "DEGRADED"
            completed_at = datetime.now()
        conn.execute(
            """UPDATE jcurve_attachment_ingestion_run SET completed_count = ?,
                 valid_count = ?, failed_count = ?, status = ?, completed_at = ?
               WHERE attachment_run_id = ?""",
            [completed_count, counts[1], counts[2], status, completed_at,
             attachment_run_id],
        )
