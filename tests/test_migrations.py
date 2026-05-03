from __future__ import annotations

from market_intel.storage.migrations import apply_migrations


def test_apply_migrations_idempotent(in_memory_db):
    with in_memory_db.get_connection() as conn:
        first = apply_migrations(conn)
        second = apply_migrations(conn)
        versions = conn.execute("SELECT version FROM schema_version").fetchall()
    assert first == []  # Database initialization already applied packaged migrations.
    assert second == []
    assert versions
