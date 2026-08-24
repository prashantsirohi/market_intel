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
