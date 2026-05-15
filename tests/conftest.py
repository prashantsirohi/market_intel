"""Shared pytest fixtures for market_intel tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from storage.db import Database


@pytest.fixture
def in_memory_db() -> Database:
    """Fresh in-memory DuckDB with full schema applied."""
    return Database(db_path=":memory:")


@pytest.fixture
def seeded_db(in_memory_db: Database) -> Database:
    """In-memory DB pre-populated with one resolved event and one bulk deal."""
    db = in_memory_db
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO raw_event (
                source, source_type, symbol, title, description,
                event_date, published_at, link, raw_payload_json, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "nse_rss", "rss", "RELIANCE",
                "Capex announcement: ₹15,000 crore Jamnagar expansion",
                "Reliance announces capacity expansion at Jamnagar refinery",
                datetime(2026, 4, 28, tzinfo=timezone.utc),
                datetime(2026, 4, 28, tzinfo=timezone.utc),
                "https://example.com/r1",
                "{}", "hash-reliance-001",
            ],
        )
        raw_id = conn.execute(
            "SELECT raw_event_id FROM raw_event WHERE event_hash = ?",
            ["hash-reliance-001"],
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO resolved_event (
                raw_event_id, primary_category, importance_score, trust_score,
                alert_level, is_official, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [raw_id, "capex_expansion", 8.5, 95.0, "critical", True, "resolved"],
        )
        conn.execute(
            """
            INSERT INTO bulk_deal (
                trade_date, symbol, exchange, client_name, side,
                quantity, avg_price, deal_value_cr, is_block, deal_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "2026-04-28", "RELIANCE", "NSE", "ICICI Pru MF", "BUY",
                500_000, 2400.0, 120.0, False, "bulk-hash-001",
            ],
        )
    return db
