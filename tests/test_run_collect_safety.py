from __future__ import annotations

import sys
from pathlib import Path

from jobs import run_collect
from storage.db import Database


def _seed_db(path: Path) -> None:
    db = Database(str(path))
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO raw_event (
                source, source_type, symbol, title, raw_payload_json, event_hash
            ) VALUES ('test', 'fixture', 'SAFE', 'keep me', '{}', 'safe-hash')
            """
        )
    db.close()


def _count_raw(path: Path) -> int:
    db = Database(str(path))
    with db.get_connection(read_only=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM raw_event").fetchone()[0]
    db.close()
    return int(count)


def test_run_collect_does_not_wipe_db_by_default(monkeypatch, tmp_path):
    db_path = tmp_path / "market_intel.duckdb"
    _seed_db(db_path)
    monkeypatch.setattr(sys, "argv", ["run_collect", "--db-path", str(db_path), "--sources", "none"])
    monkeypatch.setattr(run_collect.CollectionService, "run_collection", lambda self, sources=None: {
        "total": 0,
        "rss_processed": 0,
        "rss_new": 0,
        "bulk_deal_new": 0,
        "sast_new": 0,
        "insider_new": 0,
        "rating_new": 0,
        "bse_corp_new": 0,
        "failed": 0,
    })
    assert run_collect.main() == 0
    assert _count_raw(db_path) == 1


def test_run_collect_fresh_flag_explicitly_resets_db(monkeypatch, tmp_path):
    db_path = tmp_path / "market_intel.duckdb"
    _seed_db(db_path)
    monkeypatch.setattr(sys, "argv", ["run_collect", "--db-path", str(db_path), "--sources", "none", "--fresh"])
    monkeypatch.setattr(run_collect.CollectionService, "run_collection", lambda self, sources=None: {
        "total": 0,
        "rss_processed": 0,
        "rss_new": 0,
        "bulk_deal_new": 0,
        "sast_new": 0,
        "insider_new": 0,
        "rating_new": 0,
        "bse_corp_new": 0,
        "failed": 0,
    })
    assert run_collect.main() == 0
    assert _count_raw(db_path) == 0


def test_run_collect_updates_scheduler_heartbeat(monkeypatch, tmp_path):
    db_path = tmp_path / "market_intel.duckdb"
    monkeypatch.setattr(sys, "argv", ["run_collect", "--db-path", str(db_path), "--sources", "none"])
    monkeypatch.setattr(run_collect.CollectionService, "run_collection", lambda self, sources=None: {
        "total": 0,
        "rss_processed": 0,
        "rss_new": 0,
        "bulk_deal_new": 0,
        "sast_new": 0,
        "insider_new": 0,
        "rating_new": 0,
        "bse_corp_new": 0,
        "failed": 0,
    })
    assert run_collect.main() == 0
    db = Database(str(db_path))
    state = db.scheduler_state_repo().get_or_create()
    db.close()
    assert state["last_heartbeat"] is not None
