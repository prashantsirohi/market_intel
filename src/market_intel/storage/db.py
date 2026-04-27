from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from market_intel.storage.repositories import (
        TrackedEntityRepository,
        RawEventRepository,
        ResolvedEventRepository,
        AlertLogRepository,
    )


class Database:
    def __init__(self, db_path: str = "./data/market_intel.duckdb", fresh: bool = False):
        self.db_path = db_path
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._repos: dict[str, object] = {}
        if db_path == ":memory:":
            self._connection = duckdb.connect(db_path)
            self._init_schema()
        else:
            self._ensure_directories()
            self._init_db(fresh=fresh)

    def _ensure_directories(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        if self._connection is not None:
            return self._connection
        return duckdb.connect(self.db_path, read_only=read_only)

    def _init_schema(self) -> None:
        import market_intel
        schema_path = Path(market_intel.__file__).parent / "storage" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        self._connection.execute(schema_sql)

    def _init_db(self, fresh: bool = False) -> None:
        import market_intel
        if fresh and Path(self.db_path).exists():
            Path(self.db_path).unlink()
        schema_path = Path(market_intel.__file__).parent / "storage" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        conn = self._connect()
        try:
            conn.execute(schema_sql)
        finally:
            conn.close()

    @contextmanager
    def get_connection(self, read_only: bool = False):
        conn = self._connect(read_only=read_only)
        try:
            yield conn
        finally:
            if self._connection is None:
                conn.close()

    def tracked_entity_repo(self) -> TrackedEntityRepository:
        from market_intel.storage.repositories import TrackedEntityRepository
        if "tracked_entity" not in self._repos:
            self._repos["tracked_entity"] = TrackedEntityRepository(self)
        return self._repos["tracked_entity"]

    def raw_event_repo(self) -> RawEventRepository:
        from market_intel.storage.repositories import RawEventRepository
        if "raw_event" not in self._repos:
            self._repos["raw_event"] = RawEventRepository(self)
        return self._repos["raw_event"]

    def resolved_event_repo(self) -> ResolvedEventRepository:
        from market_intel.storage.repositories import ResolvedEventRepository
        if "resolved_event" not in self._repos:
            self._repos["resolved_event"] = ResolvedEventRepository(self)
        return self._repos["resolved_event"]

    def alert_log_repo(self) -> AlertLogRepository:
        from market_intel.storage.repositories import AlertLogRepository
        if "alert_log" not in self._repos:
            self._repos["alert_log"] = AlertLogRepository(self)
        return self._repos["alert_log"]

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None