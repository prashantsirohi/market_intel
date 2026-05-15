"""Read-side query API for downstream consumers (e.g. trading systems).

This is the only public surface external systems should depend on. Returns
plain dataclasses (no DuckDB types leak out) so callers can be tested without
a live database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Optional

from processing.taxonomy import category_tier
from storage.db import Database


@dataclass(frozen=True)
class ResolvedEventRecord:
    """Projection of resolved_event JOIN raw_event for external consumers."""

    raw_event_id: int
    resolved_event_id: int
    symbol: Optional[str]
    company_name: Optional[str]
    title: str
    description: Optional[str]
    primary_category: Optional[str]
    event_tier: str
    importance_score: float
    trust_score: float
    alert_level: Optional[str]
    is_official: Optional[bool]
    event_date: Optional[datetime]
    published_at: Optional[datetime]
    source: str
    link: Optional[str]
    attachment_url: Optional[str]
    one_line_summary: Optional[str]
    event_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BulkDealRecord:
    bulk_deal_id: int
    trade_date: date
    symbol: str
    exchange: str
    client_name: Optional[str]
    side: str
    quantity: Optional[int]
    avg_price: Optional[float]
    deal_value_cr: Optional[float]
    is_block: bool
    deal_hash: str


@dataclass(frozen=True)
class InsiderTradeRecord:
    insider_trade_id: int
    symbol: str
    person_name: Optional[str]
    designation: Optional[str]
    txn_type: Optional[str]
    quantity: Optional[int]
    value_cr: Optional[float]
    txn_date: Optional[date]
    disclosed_date: Optional[date]
    txn_hash: str


@dataclass(frozen=True)
class RatingChangeRecord:
    rating_change_id: int
    symbol: Optional[str]
    agency: str
    instrument: Optional[str]
    old_rating: Optional[str]
    new_rating: Optional[str]
    action: Optional[str]
    dated: Optional[date]
    change_hash: str


def _normalize_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class EventQueryService:
    """Read-only query layer over the market_intel DuckDB store.

    Construct with an existing Database (preferred for tests/in-memory) or pass
    a db_path. Methods are pure reads — never mutate state.
    """

    def __init__(self, db: Database | None = None, *, db_path: str | None = None):
        if db is None and db_path is None:
            raise ValueError("Provide either `db` or `db_path`")
        self._db = db or Database(db_path=db_path)  # type: ignore[arg-type]

    @classmethod
    def from_readonly_path(cls, db_path: str) -> "EventQueryService":
        """Construct a read-only service without creating or migrating the DB."""
        return cls(db=Database.open_readonly(db_path))

    # ------------------------------------------------------------------ events

    def get_events_for_symbol(
        self,
        symbol: str,
        *,
        since: datetime,
        until: datetime | None = None,
        categories: Iterable[str] | None = None,
        tiers: Iterable[str] = ("A", "B"),
        min_importance: float = 0.0,
        min_trust: float = 80.0,
        limit: int = 50,
    ) -> list[ResolvedEventRecord]:
        rows = self._query_events(
            symbols=[symbol],
            since=since,
            until=until,
            categories=categories,
            min_importance=min_importance,
            min_trust=min_trust,
            limit=limit,
        )
        tier_set = set(tiers)
        return [r for r in rows if r.event_tier in tier_set]

    def get_events_for_universe(
        self,
        symbols: Iterable[str],
        *,
        since: datetime,
        until: datetime | None = None,
        categories: Iterable[str] | None = None,
        tiers: Iterable[str] = ("A", "B"),
        min_importance: float = 0.0,
        min_trust: float = 80.0,
        per_symbol_limit: int = 20,
    ) -> dict[str, list[ResolvedEventRecord]]:
        out: dict[str, list[ResolvedEventRecord]] = {}
        for sym in symbols:
            out[sym] = self.get_events_for_symbol(
                sym,
                since=since,
                until=until,
                categories=categories,
                tiers=tiers,
                min_importance=min_importance,
                min_trust=min_trust,
                limit=per_symbol_limit,
            )
        return out

    def get_important_events(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        categories: Iterable[str] | None = None,
        tiers: Iterable[str] = ("A", "B"),
        min_importance: float = 0.0,
        min_trust: float = 80.0,
        limit: int = 500,
    ) -> list[ResolvedEventRecord]:
        """Return market-wide important events for daily snapshot consumers."""
        rows = self._query_events(
            symbols=None,
            since=since,
            until=until,
            categories=categories,
            min_importance=min_importance,
            min_trust=min_trust,
            limit=limit,
        )
        tier_set = set(tiers)
        return [r for r in rows if r.event_tier in tier_set]


    def _query_events(
        self,
        *,
        symbols: list[str] | None,
        since: datetime,
        until: datetime | None,
        categories: Iterable[str] | None,
        min_importance: float,
        min_trust: float,
        limit: int,
    ) -> list[ResolvedEventRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if symbols:
            clauses.append("r.symbol IN ({})".format(",".join("?" for _ in symbols)))
            params.extend(symbols)
        else:
            clauses.append("r.symbol IS NOT NULL")
        clauses.append("(r.event_date >= ? OR r.published_at >= ?)")
        params.extend([since, since])
        if until is not None:
            clauses.append("(r.event_date <= ? OR r.published_at <= ?)")
            params.extend([until, until])
        if categories:
            cat_list = list(categories)
            clauses.append(
                "re.primary_category IN ({})".format(",".join("?" for _ in cat_list))
            )
            params.extend(cat_list)
        clauses.append("re.importance_score >= ?")
        params.append(min_importance)
        clauses.append("re.trust_score >= ?")
        params.append(min_trust)

        sql = f"""
            SELECT r.raw_event_id, re.resolved_event_id, r.symbol, r.company_name,
                   r.title, r.description, re.primary_category,
                   re.importance_score, re.trust_score, re.alert_level,
                   re.is_official, r.event_date, r.published_at, r.source,
                   r.link, r.attachment_url, re.one_line_summary, r.event_hash
            FROM resolved_event re
            JOIN raw_event r ON re.raw_event_id = r.raw_event_id
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(r.event_date, r.published_at, r.ingested_at) DESC
            LIMIT ?
        """
        params.append(limit)

        with self._db.get_connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()

        out: list[ResolvedEventRecord] = []
        for row in rows:
            primary = row[6]
            out.append(
                ResolvedEventRecord(
                    raw_event_id=row[0],
                    resolved_event_id=row[1],
                    symbol=row[2],
                    company_name=row[3],
                    title=row[4] or "",
                    description=row[5],
                    primary_category=primary,
                    event_tier=category_tier(primary or ""),
                    importance_score=float(row[7] or 0.0),
                    trust_score=float(row[8] or 0.0),
                    alert_level=row[9],
                    is_official=bool(row[10]) if row[10] is not None else None,
                    event_date=_normalize_dt(row[11]),
                    published_at=_normalize_dt(row[12]),
                    source=row[13] or "",
                    link=row[14],
                    attachment_url=row[15],
                    one_line_summary=row[16],
                    event_hash=row[17] or "",
                )
            )
        return out

    # ------------------------------------------------------------- bulk deals

    def get_bulk_deals(
        self,
        symbols: Iterable[str] | None = None,
        *,
        since: date,
        until: date | None = None,
        min_value_cr: float = 0.0,
        block_only: bool = False,
        limit: int = 1000,
    ) -> list[BulkDealRecord]:
        clauses = ["trade_date >= ?"]
        params: list[Any] = [since]
        if until is not None:
            clauses.append("trade_date <= ?")
            params.append(until)
        sym_list = list(symbols or [])
        if sym_list:
            clauses.append("symbol IN ({})".format(",".join("?" for _ in sym_list)))
            params.extend(sym_list)
        if min_value_cr > 0:
            clauses.append("deal_value_cr >= ?")
            params.append(min_value_cr)
        if block_only:
            clauses.append("is_block = TRUE")

        sql = f"""
            SELECT bulk_deal_id, trade_date, symbol, exchange, client_name,
                   side, quantity, avg_price, deal_value_cr, is_block, deal_hash
            FROM bulk_deal
            WHERE {" AND ".join(clauses)}
            ORDER BY trade_date DESC, deal_value_cr DESC NULLS LAST
            LIMIT ?
        """
        params.append(limit)

        with self._db.get_connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            BulkDealRecord(
                bulk_deal_id=row[0],
                trade_date=row[1],
                symbol=row[2],
                exchange=row[3],
                client_name=row[4],
                side=row[5],
                quantity=int(row[6]) if row[6] is not None else None,
                avg_price=float(row[7]) if row[7] is not None else None,
                deal_value_cr=float(row[8]) if row[8] is not None else None,
                is_block=bool(row[9]),
                deal_hash=row[10],
            )
            for row in rows
        ]

    # ------------------------------------------------------- insider / rating

    def get_insider_trades(
        self,
        symbols: Iterable[str] | None = None,
        *,
        since: date,
        until: date | None = None,
        min_value_cr: float = 0.0,
        limit: int = 1000,
    ) -> list[InsiderTradeRecord]:
        clauses = ["(disclosed_date >= ? OR txn_date >= ?)"]
        params: list[Any] = [since, since]
        if until is not None:
            clauses.append("(disclosed_date <= ? OR txn_date <= ?)")
            params.extend([until, until])
        sym_list = list(symbols or [])
        if sym_list:
            clauses.append("symbol IN ({})".format(",".join("?" for _ in sym_list)))
            params.extend(sym_list)
        if min_value_cr > 0:
            clauses.append("value_cr >= ?")
            params.append(min_value_cr)

        sql = f"""
            SELECT insider_trade_id, symbol, person_name, designation,
                   txn_type, quantity, value_cr, txn_date, disclosed_date, txn_hash
            FROM insider_trade
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(disclosed_date, txn_date) DESC
            LIMIT ?
        """
        params.append(limit)

        with self._db.get_connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            InsiderTradeRecord(
                insider_trade_id=row[0], symbol=row[1], person_name=row[2],
                designation=row[3], txn_type=row[4],
                quantity=int(row[5]) if row[5] is not None else None,
                value_cr=float(row[6]) if row[6] is not None else None,
                txn_date=row[7], disclosed_date=row[8], txn_hash=row[9],
            )
            for row in rows
        ]

    def get_rating_changes(
        self,
        symbols: Iterable[str] | None = None,
        *,
        since: date,
        until: date | None = None,
        agencies: Iterable[str] | None = None,
        limit: int = 1000,
    ) -> list[RatingChangeRecord]:
        clauses = ["dated >= ?"]
        params: list[Any] = [since]
        if until is not None:
            clauses.append("dated <= ?")
            params.append(until)
        sym_list = list(symbols or [])
        if sym_list:
            clauses.append("symbol IN ({})".format(",".join("?" for _ in sym_list)))
            params.extend(sym_list)
        agency_list = list(agencies or [])
        if agency_list:
            clauses.append("agency IN ({})".format(",".join("?" for _ in agency_list)))
            params.extend(agency_list)

        sql = f"""
            SELECT rating_change_id, symbol, agency, instrument, old_rating,
                   new_rating, action, dated, change_hash
            FROM rating_change
            WHERE {" AND ".join(clauses)}
            ORDER BY dated DESC
            LIMIT ?
        """
        params.append(limit)

        with self._db.get_connection(read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            RatingChangeRecord(
                rating_change_id=row[0], symbol=row[1], agency=row[2],
                instrument=row[3], old_rating=row[4], new_rating=row[5],
                action=row[6], dated=row[7], change_hash=row[8],
            )
            for row in rows
        ]

    def get_market_caps(self, symbols: Iterable[str]) -> dict[str, float]:
        """Return market caps in INR keyed by symbol from tracked_entity."""
        sym_list = [str(sym).upper() for sym in symbols if str(sym or "").strip()]
        if not sym_list:
            return {}
        sql = """
            SELECT symbol, market_cap_cr
            FROM tracked_entity
            WHERE symbol IN ({}) AND market_cap_cr IS NOT NULL
        """.format(",".join("?" for _ in sym_list))
        with self._db.get_connection(read_only=True) as conn:
            rows = conn.execute(sql, sym_list).fetchall()
        return {
            str(row[0]).upper(): float(row[1]) * 1e7
            for row in rows
            if row[1] is not None
        }

    # -------------------------------------------------------------- health

    def scheduler_health(self) -> dict[str, Any]:
        """Last-heartbeat & cycle-stats for the host healthcheck."""
        sql = """
            SELECT last_heartbeat, last_cycle_at, cycle_stats_json, error_count
            FROM scheduler_state
            ORDER BY state_id DESC
            LIMIT 1
        """
        with self._db.get_connection(read_only=True) as conn:
            row = conn.execute(sql).fetchone()
        if not row:
            return {"status": "unknown", "last_heartbeat": None}
        stats = {}
        if row[2]:
            try:
                stats = json.loads(row[2])
            except (TypeError, ValueError):
                stats = {}
        return {
            "status": "ok",
            "last_heartbeat": row[0],
            "last_cycle_at": row[1],
            "cycle_stats": stats,
            "error_count": int(row[3] or 0),
        }

    def get_collector_health(self) -> dict[str, Any]:
        """Alias for downstream clients that use EventQueryService as API."""
        return self.scheduler_health()
