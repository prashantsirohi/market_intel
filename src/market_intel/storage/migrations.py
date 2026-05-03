"""Lightweight DuckDB schema migration runner."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def migration_files() -> list[Path]:
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    if not migrations_dir.exists():
        return []
    return sorted(
        path for path in migrations_dir.glob("*.sql") if path.name[:4].isdigit()
    )


def apply_migrations(conn, *, files: Iterable[Path] | None = None) -> list[str]:
    """Apply ordered SQL migrations idempotently and return applied versions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version VARCHAR PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_version").fetchall()
    }
    applied_now: list[str] = []
    for path in files or migration_files():
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        if sql.strip():
            conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_version(version) VALUES (?)",
            [version],
        )
        applied_now.append(version)
    return applied_now
