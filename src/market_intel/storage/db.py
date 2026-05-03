from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from market_intel.storage.repositories import (
        TrackedEntityRepository,
        RawEventRepository,
        ResolvedEventRepository,
        AlertLogRepository,
        BulkDealRepository,
        InsiderTradeRepository,
        RatingChangeRepository,
        SastFilingRepository,
    )


class Database:
    _instance_lock = threading.Lock()
    _connection: duckdb.DuckDBPyConnection | None = None
    
    def __init__(
        self,
        db_path: str = "./data/market_intel.duckdb",
        fresh: bool = False,
        *,
        read_only: bool = False,
    ):
        self.db_path = db_path
        self._repos: dict[str, object] = {}
        self._write_lock = threading.Lock()
        self._read_only = read_only
        if read_only:
            return
        if db_path == ":memory:":
            self._connection = duckdb.connect(db_path)
            self._init_schema()
        else:
            self._ensure_directories()
            self._init_db(fresh=fresh)

    @classmethod
    def open_readonly(cls, db_path: str) -> "Database":
        """Open an existing DuckDB for reads without creating or migrating it."""
        return cls(db_path=db_path, read_only=True)

    def _ensure_directories(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        if self._read_only and not read_only:
            raise RuntimeError("Database was opened read-only; write connection requested")
        if self._connection is not None:
            return self._connection
        with self._write_lock:
            if self._connection is not None:
                return self._connection
            conn = duckdb.connect(self.db_path, read_only=read_only)
            if not read_only:
                self._connection = conn
            return conn

    def _init_schema(self) -> None:
        import market_intel
        from market_intel.storage.migrations import apply_migrations
        schema_path = Path(market_intel.__file__).parent / "storage" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        self._connection.execute(schema_sql)
        apply_migrations(self._connection)

    def _init_db(self, fresh: bool = False) -> None:
        import market_intel
        from market_intel.storage.migrations import apply_migrations
        if fresh and Path(self.db_path).exists():
            Path(self.db_path).unlink()
        db_exists = Path(self.db_path).exists()
        schema_path = Path(market_intel.__file__).parent / "storage" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        conn = self._connect()
        try:
            if fresh or not db_exists:
                conn.execute(schema_sql)
            apply_migrations(conn)
        finally:
            # Drop the cached writable connection so that a subsequent
            # get_connection(read_only=True) call can open a fresh handle.
            # Previously this closed the conn but left self._connection
            # pointing at the closed handle, causing "Connection already closed".
            conn.close()
            self._connection = None

    @contextmanager
    def get_connection(self, read_only: bool = False):
        conn = self._connect(read_only=read_only)
        try:
            yield conn
        finally:
            if read_only and self._connection is None:
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

    def bulk_deal_repo(self) -> "BulkDealRepository":
        from market_intel.storage.repositories import BulkDealRepository
        if "bulk_deal" not in self._repos:
            self._repos["bulk_deal"] = BulkDealRepository(self)
        return self._repos["bulk_deal"]

    def insider_trade_repo(self) -> "InsiderTradeRepository":
        from market_intel.storage.repositories import InsiderTradeRepository
        if "insider_trade" not in self._repos:
            self._repos["insider_trade"] = InsiderTradeRepository(self)
        return self._repos["insider_trade"]

    def rating_change_repo(self) -> "RatingChangeRepository":
        from market_intel.storage.repositories import RatingChangeRepository
        if "rating_change" not in self._repos:
            self._repos["rating_change"] = RatingChangeRepository(self)
        return self._repos["rating_change"]

    def sast_filing_repo(self) -> "SastFilingRepository":
        from market_intel.storage.repositories import SastFilingRepository
        if "sast_filing" not in self._repos:
            self._repos["sast_filing"] = SastFilingRepository(self)
        return self._repos["sast_filing"]

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
