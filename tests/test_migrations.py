from __future__ import annotations

import duckdb

from storage.db import Database
from storage.migrations import apply_migrations


def test_apply_migrations_idempotent(in_memory_db):
    with in_memory_db.get_connection() as conn:
        first = apply_migrations(conn)
        second = apply_migrations(conn)
        versions = conn.execute("SELECT version FROM schema_version").fetchall()
    assert first == []  # Database initialization already applied packaged migrations.
    assert second == []
    assert versions


def test_existing_resolved_event_table_gains_tier_columns(tmp_path):
    db_path = tmp_path / "legacy_market_intel.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SEQUENCE resolved_event_seq")
    conn.execute(
        """
        CREATE TABLE schema_version (
            version VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )
    conn.execute("INSERT INTO schema_version(version) VALUES ('0001_market_event_sources')")
    conn.execute("INSERT INTO schema_version(version) VALUES ('0002_llm_insight_current')")
    conn.execute(
        """
        CREATE TABLE resolved_event (
            resolved_event_id BIGINT PRIMARY KEY DEFAULT nextval('resolved_event_seq'),
            raw_event_id BIGINT NOT NULL,
            insight_id BIGINT,
            entity_id BIGINT,
            primary_category VARCHAR,
            secondary_category VARCHAR,
            sentiment_label VARCHAR,
            sentiment_score DOUBLE,
            importance_score DOUBLE,
            trust_score DOUBLE,
            parser_confidence DOUBLE,
            novelty_score DOUBLE,
            alert_level VARCHAR,
            is_official BOOLEAN,
            summary_text VARCHAR,
            one_line_summary VARCHAR,
            financials_json VARCHAR,
            risk_flags_json VARCHAR,
            period_label VARCHAR,
            key_facts_json VARCHAR,
            status VARCHAR NOT NULL DEFAULT 'pending',
            resolved_at TIMESTAMP,
            acknowledged_at TIMESTAMP,
            UNIQUE(raw_event_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO resolved_event (
            raw_event_id, primary_category, importance_score, trust_score,
            alert_level, is_official, status
        ) VALUES (1, 'capex_expansion', 8.5, 95.0, 'critical', TRUE, 'pending')
        """
    )
    conn.close()

    db = Database(str(db_path))
    try:
        with db.get_connection() as migrated:
            columns = {
                row[1]
                for row in migrated.execute("PRAGMA table_info('resolved_event')").fetchall()
            }
            tier = migrated.execute(
                "SELECT event_tier FROM resolved_event WHERE raw_event_id = 1"
            ).fetchone()[0]
        assert {"event_tier", "ignored_reason"} <= columns
        assert tier == "A"

        resolved = db.resolved_event_repo().upsert(
            raw_event_id=2,
            primary_category="investor_meet",
            alert_level="info",
            importance_score=2.0,
            trust_score=95.0,
            event_tier="IGNORE",
            ignored_reason="ignored:investor_meet",
        )
        assert resolved.event_tier == "IGNORE"
        assert resolved.ignored_reason == "ignored:investor_meet"
    finally:
        db.close()
