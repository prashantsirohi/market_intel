from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .db import Database
from ..processing.deduper import build_event_hash


def _v(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, datetime):
        return repr(val.isoformat())
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(val, (list, dict)):
        return repr(json.dumps(val, default=str))
    return repr(val)


def _dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _safe_json_loads(val: Any, default: Any = None) -> Any:
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(str(val)) if val else default
    except Exception:
        return default


def _v_raw(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, datetime):
        return repr(val.isoformat())
    if isinstance(val, (int, float)):
        return str(val)
    return repr(val)


@dataclass
class UpsertRawEventResult:
    raw_event_id: int
    is_new: bool
    event_hash: str


@dataclass
class TrackedEntity:
    entity_id: Optional[int] = None
    symbol: str = ""
    isin: Optional[str] = None
    company_name: Optional[str] = None
    entity_type: str = "stock"
    sector: Optional[str] = None
    source_list: Optional[str] = None
    priority: int = 0
    is_active: bool = True
    aliases: list[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []


@dataclass
class RawEvent:
    raw_event_id: Optional[int] = None
    source: str = ""
    source_type: str = ""
    external_id: Optional[str] = None
    symbol: Optional[str] = None
    isin: Optional[str] = None
    company_name: Optional[str] = None
    title: Optional[str] = None
    category_desc: Optional[str] = None
    event_date: Optional[datetime] = None
    published_at: Optional[datetime] = None
    link: Optional[str] = None
    attachment_url: Optional[str] = None
    description: Optional[str] = None
    raw_payload_json: str = "{}"
    event_hash: str = ""
    ingested_at: Optional[datetime] = None
    seen_count: int = 1
    processing_status: str = "new"
    status: str = "pending"
    error_message: Optional[str] = None


@dataclass
class ResolvedEvent:
    resolved_event_id: Optional[int] = None
    raw_event_id: int = 0
    entity_id: Optional[int] = None
    primary_category: Optional[str] = None
    secondary_category: Optional[str] = None
    sentiment_label: Optional[str] = None
    sentiment_score: Optional[float] = None
    importance_score: Optional[float] = None
    trust_score: Optional[float] = None
    parser_confidence: Optional[float] = None
    novelty_score: Optional[float] = None
    alert_level: Optional[str] = None
    is_official: bool = False
    summary_text: Optional[str] = None
    key_facts: list[str] = None
    status: str = "pending"
    resolved_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None

    def __post_init__(self):
        if self.key_facts is None:
            self.key_facts = []


@dataclass
class AlertLog:
    alert_id: Optional[int] = None
    resolved_event_id: int = 0
    channel: str = ""
    alert_status: str = "pending"
    sent_at: Optional[datetime] = None
    payload_json: Optional[str] = None


@dataclass
class LlmInsight:
    insight_id: Optional[int] = None
    raw_event_id: int = 0
    document_id: Optional[int] = None
    model_used: str = ""
    provider: str = ""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    insight_json: str = "{}"
    created_at: Optional[datetime] = None


@dataclass
class SchedulerState:
    state_id: Optional[int] = None
    last_heartbeat: Optional[datetime] = None
    last_cycle_at: Optional[datetime] = None
    cycle_stats_json: Optional[str] = None
    error_count: int = 0
    created_at: Optional[datetime] = None


class TrackedEntityRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        symbol: str,
        isin: Optional[str] = None,
        company_name: Optional[str] = None,
        source_list: Optional[str] = None,
        priority: int = 0,
        sector: Optional[str] = None,
        aliases: Optional[list[str]] = None,
    ) -> TrackedEntity:
        aliases_json = json.dumps(aliases or [])
        symbol_upper = symbol.upper()

        with self.db.get_connection() as conn:
            max_result = conn.execute("SELECT COALESCE(MAX(entity_id), 0) FROM tracked_entity").fetchone()
            next_id = (max_result[0] if max_result[0] else 0) + 1
            conn.execute(
                """
                INSERT INTO tracked_entity(entity_id, symbol, isin, company_name, source_list, priority, sector, aliases_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    isin = COALESCE(excluded.isin, tracked_entity.isin),
                    company_name = COALESCE(excluded.company_name, tracked_entity.company_name),
                    source_list = COALESCE(excluded.source_list, tracked_entity.source_list),
                    priority = GREATEST(tracked_entity.priority, excluded.priority),
                    sector = COALESCE(excluded.sector, tracked_entity.sector),
                    aliases_json = CASE
                        WHEN excluded.aliases_json IS NOT NULL AND excluded.aliases_json != '[]' THEN excluded.aliases_json
                        ELSE tracked_entity.aliases_json
                    END
                """,
                [next_id, symbol_upper, isin, company_name, source_list, priority, sector, aliases_json],
            )

            row = conn.execute(
                "SELECT * FROM tracked_entity WHERE symbol = ?",
                [symbol_upper]
            ).fetchone()

            return self._row_to_entity(row)

    def get_by_symbol(self, symbol: str) -> Optional[TrackedEntity]:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM tracked_entity WHERE symbol = ?",
                [symbol.upper()]
            ).fetchone()
            return self._row_to_entity(row) if row else None

    def list_active(self) -> list[TrackedEntity]:
        with self.db.get_connection(read_only=True) as conn:
            rows = conn.execute(
                "SELECT * FROM tracked_entity WHERE is_active = TRUE ORDER BY priority DESC, symbol"
            ).fetchall()
            return [self._row_to_entity(row) for row in rows]

    def _row_to_entity(self, row: Any) -> Optional[TrackedEntity]:
        if row is None:
            return None
        aliases = _safe_json_loads(row[7], [])
        return TrackedEntity(
            entity_id=row[0],
            symbol=row[1],
            isin=row[2],
            company_name=row[3],
            entity_type=row[4],
            sector=row[5],
            source_list=row[6],
            priority=row[7] if isinstance(row[7], int) else row[7],
            is_active=row[8] if isinstance(row[8], bool) else bool(row[8]),
            aliases=aliases,
            created_at=_dt(row[9]),
            updated_at=_dt(row[10]),
        )


class RawEventRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert_event(
        self,
        *,
        source: str,
        source_type: str,
        external_id: Optional[str] = None,
        symbol: Optional[str] = None,
        isin: Optional[str] = None,
        company_name: Optional[str] = None,
        title: Optional[str] = None,
        category_desc: Optional[str] = None,
        event_date: Optional[datetime] = None,
        published_at: Optional[datetime] = None,
        link: Optional[str] = None,
        attachment_url: Optional[str] = None,
        description: Optional[str] = None,
        raw_payload: Optional[dict[str, Any]] = None,
    ) -> Optional[RawEvent]:
        raw_payload = raw_payload or {}
        event_hash = build_event_hash(
            source=source,
            symbol=symbol,
            title=title,
            event_date=event_date.isoformat() if event_date else None,
            attachment_url=attachment_url,
            external_id=external_id,
        )

        def _v(val):
            if val is None:
                return "NULL"
            if isinstance(val, datetime):
                return repr(val.isoformat())
            if isinstance(val, str):
                escaped = val.replace("'", "''")
                return f"'{escaped}'"
            return repr(val)

        with self.db.get_connection() as conn:
            existing = conn.execute(
                f"SELECT * FROM raw_event WHERE event_hash = {_v(event_hash)}"
            ).fetchone()
            if existing:
                conn.execute(
                    f"UPDATE raw_event SET seen_count = seen_count + 1, ingested_at = CURRENT_TIMESTAMP WHERE event_hash = {_v(event_hash)}"
                )
                # Re-fetch AFTER the update so seen_count reflects the new value.
                # The pre-update snapshot always had seen_count=1, causing
                # process_rss_item to treat every re-seen event as new.
                updated = conn.execute(
                    "SELECT * FROM raw_event WHERE event_hash = ?", [event_hash]
                ).fetchone()
                return self._row_to_event(updated)

            max_result = conn.execute("SELECT COALESCE(MAX(raw_event_id), 0) FROM raw_event").fetchone()
            next_id = (max_result[0] if max_result[0] else 0) + 1
            conn.execute(
                f"INSERT INTO raw_event(raw_event_id, source, source_type, external_id, symbol, isin, company_name, title, category_desc, event_date, published_at, link, attachment_url, description, raw_payload_json, event_hash, processing_status, status) "
                f"VALUES ({next_id}, {_v(source)}, {_v(source_type)}, {_v(external_id)}, {_v(symbol)}, "
                f"{_v(isin)}, {_v(company_name)}, {_v(title)}, {_v(category_desc)}, "
                f"{_v(event_date)}, {_v(published_at)}, {_v(link)}, {_v(attachment_url)}, "
                f"{_v(description)}, {_v(json.dumps(raw_payload, default=str))}, {_v(event_hash)}, 'new', 'pending')",
            )

            row = conn.execute(
                "SELECT * FROM raw_event WHERE event_hash = ?",
                [event_hash]
            ).fetchone()

            return self._row_to_event(row) if row else None

    def get_by_hash(self, event_hash: str) -> Optional[dict]:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT raw_event_id, event_hash, seen_count, processing_status FROM raw_event WHERE event_hash = ?",
                [event_hash]
            ).fetchone()
            if row:
                return {"raw_event_id": row[0], "event_hash": row[1], "seen_count": row[2], "processing_status": row[3]}
            return None

    def list_unprocessed(self, limit: int = 100) -> list[RawEvent]:
        with self.db.get_connection(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM raw_event
                WHERE processing_status = 'new'
                ORDER BY COALESCE(event_date, published_at) DESC
                LIMIT ?
                """,
                [limit]
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def mark_processed(self, raw_event_id: int) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE raw_event SET processing_status = 'completed', status = 'done' WHERE raw_event_id = ?",
                [raw_event_id],
            )

    def count(self) -> int:
        with self.db.get_connection(read_only=True) as conn:
            result = conn.execute("SELECT COUNT(*) FROM raw_event").fetchone()
            return result[0] if result else 0

    def _row_to_event(self, row: Any) -> Optional[RawEvent]:
        if row is None:
            return None
        return RawEvent(
            raw_event_id=row[0],
            source=row[1],
            source_type=row[2],
            external_id=row[3],
            symbol=row[4],
            isin=row[5],
            company_name=row[6],
            title=row[7],
            category_desc=row[8],
            event_date=_dt(row[9]),
            published_at=_dt(row[10]),
            link=row[11],
            attachment_url=row[12],
            description=row[13],
            raw_payload_json=row[14],
            event_hash=row[15],
            ingested_at=_dt(row[16]) if len(row) > 16 else None,
            seen_count=row[17] if len(row) > 17 else 1,
            processing_status=row[18] if len(row) > 18 else "new",
            status=row[19] if len(row) > 19 else "pending",
            error_message=row[20] if len(row) > 20 else None,
        )


class ResolvedEventRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        raw_event_id: int,
        entity_id: Optional[int] = None,
        primary_category: Optional[str] = None,
        secondary_category: Optional[str] = None,
        sentiment_label: Optional[str] = None,
        sentiment_score: Optional[float] = None,
        importance_score: Optional[float] = None,
        trust_score: Optional[float] = None,
        parser_confidence: Optional[float] = None,
        novelty_score: Optional[float] = None,
        alert_level: Optional[str] = None,
        is_official: bool = False,
        summary_text: Optional[str] = None,
        key_facts: Optional[list[str]] = None,
        status: str = "pending",
        event_tier: Optional[str] = None,
        ignored_reason: Optional[str] = None,
    ) -> ResolvedEvent:
        key_facts_json = json.dumps(key_facts or [])

        def _v(val):
            if val is None:
                return "NULL"
            if isinstance(val, bool):
                return "TRUE" if val else "FALSE"
            if isinstance(val, (int, float)):
                return str(val)
            # Use proper SQL single-quote escaping (not repr which can produce
            # double-quoted Python literals that DuckDB treats as identifiers).
            escaped = str(val).replace("'", "''")
            return f"'{escaped}'"

        with self.db.get_connection() as conn:
            now = datetime.now().isoformat()

            # DuckDB refuses ON CONFLICT DO UPDATE for any indexed column
            # (alert_level, status, entity_id all have indexes).  Use an
            # explicit check-then-insert / check-then-update pattern instead.
            existing = conn.execute(
                "SELECT resolved_event_id FROM resolved_event WHERE raw_event_id = ?",
                [raw_event_id],
            ).fetchone()

            if existing:
                # Update only the non-indexed columns that carry new information.
                conn.execute(
                    f"""
                    UPDATE resolved_event SET
                        primary_category   = COALESCE({_v(primary_category)},   primary_category),
                        secondary_category = COALESCE({_v(secondary_category)}, secondary_category),
                        sentiment_label    = COALESCE({_v(sentiment_label)},    sentiment_label),
                        sentiment_score    = COALESCE({_v(sentiment_score)},    sentiment_score),
                        importance_score   = COALESCE({_v(importance_score)},   importance_score),
                        trust_score        = COALESCE({_v(trust_score)},        trust_score),
                        parser_confidence  = COALESCE({_v(parser_confidence)},  parser_confidence),
                        novelty_score      = COALESCE({_v(novelty_score)},      novelty_score),
                        is_official        = {_v(is_official)},
                        summary_text       = COALESCE({_v(summary_text)},       summary_text),
                        key_facts_json     = COALESCE({_v(key_facts_json)},     key_facts_json),
                        resolved_at        = '{now}',
                        event_tier         = COALESCE({_v(event_tier)},         event_tier),
                        ignored_reason     = COALESCE({_v(ignored_reason)},     ignored_reason)
                    WHERE raw_event_id = {raw_event_id}
                    """,
                )
            else:
                # Omit resolved_event_id — let the schema's nextval sequence assign it.
                # Using MAX+1 causes collisions when prior partial runs left gaps.
                conn.execute(
                    f"""
                    INSERT INTO resolved_event(
                        raw_event_id, entity_id,
                        primary_category, secondary_category,
                        sentiment_label, sentiment_score, importance_score,
                        trust_score, parser_confidence, novelty_score,
                        alert_level, is_official, summary_text, key_facts_json,
                        status, resolved_at, event_tier, ignored_reason
                    ) VALUES (
                        {raw_event_id}, {_v(entity_id)},
                        {_v(primary_category)}, {_v(secondary_category)},
                        {_v(sentiment_label)}, {_v(sentiment_score)}, {_v(importance_score)},
                        {_v(trust_score)}, {_v(parser_confidence)}, {_v(novelty_score)},
                        {_v(alert_level)}, {_v(is_official)}, {_v(summary_text)}, {_v(key_facts_json)},
                        '{status}', '{now}', {_v(event_tier)}, {_v(ignored_reason)}
                    )
                    """,
                )

            row = conn.execute(
                "SELECT * FROM resolved_event WHERE raw_event_id = ?",
                [raw_event_id],
            ).fetchone()
            return self._row_to_event(row) if row else None

    def get_by_raw_id(self, raw_event_id: int) -> Optional[ResolvedEvent]:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM resolved_event WHERE raw_event_id = ?",
                [raw_event_id]
            ).fetchone()
            return self._row_to_event(row) if row else None

    def list_by_alert_level(self, alert_level: str, limit: int = 100) -> list[ResolvedEvent]:
        with self.db.get_connection(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM resolved_event
                WHERE alert_level = ? AND status = 'pending'
                ORDER BY importance_score DESC, resolved_event_id DESC
                LIMIT ?
                """,
                [alert_level, limit],
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: Any) -> Optional[ResolvedEvent]:
        if row is None:
            return None
        key_facts = _safe_json_loads(row[13], [])
        return ResolvedEvent(
            resolved_event_id=row[0],
            raw_event_id=row[1],
            entity_id=row[2],
            primary_category=row[3],
            secondary_category=row[4],
            sentiment_label=row[5],
            sentiment_score=row[6],
            importance_score=row[7],
            trust_score=row[8],
            parser_confidence=row[9],
            novelty_score=row[10],
            alert_level=row[11],
            is_official=row[12],
            summary_text=row[13],
            key_facts=key_facts,
            status=row[15],
            resolved_at=_dt(row[16]) if len(row) > 16 else None,
            acknowledged_at=_dt(row[17]) if len(row) > 17 else None,
        )


class AlertLogRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        *,
        resolved_event_id: int,
        channel: str,
        alert_status: str = "pending",
        payload_json: Optional[str] = None,
    ) -> AlertLog:
        with self.db.get_connection() as conn:
            max_result = conn.execute("SELECT COALESCE(MAX(alert_id), 0) FROM alert_log").fetchone()
            next_id = (max_result[0] if max_result[0] else 0) + 1
            conn.execute(
                """
                INSERT INTO alert_log(alert_id, resolved_event_id, channel, alert_status, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [next_id, resolved_event_id, channel, alert_status, payload_json],
            )

            return AlertLog(
                alert_id=next_id,
                resolved_event_id=resolved_event_id,
                channel=channel,
                alert_status=alert_status,
                payload_json=payload_json,
            )

    def mark_sent(self, alert_id: int, payload_json: Optional[str] = None) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE alert_log
                SET alert_status = 'sent', sent_at = CURRENT_TIMESTAMP, payload_json = ?
                WHERE alert_id = ?
                """,
                [payload_json, alert_id],
            )

    def mark_failed(self, alert_id: int, error: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE alert_log
                SET alert_status = 'failed', payload_json = ?
                WHERE alert_id = ?
                """,
                [error, alert_id],
            )

    def mark_skipped(self, alert_id: int, reason: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE alert_log
                SET alert_status = 'skipped', payload_json = ?
                WHERE alert_id = ?
                """,
                [reason, alert_id],
            )

    def is_duplicate(self, resolved_event_id: int, channel: str) -> bool:
        with self.db.get_connection(read_only=True) as conn:
            count = conn.execute(
                """
                SELECT COUNT(*) FROM alert_log
                WHERE resolved_event_id = ? AND channel = ? AND alert_status = 'sent'
                """,
                [resolved_event_id, channel]
            ).fetchone()[0]
            return count > 0

    def already_sent(self, resolved_event_id: int, channel: str) -> bool:
        return self.is_duplicate(resolved_event_id, channel)

    def create_pending(self, resolved_event_id: int, channel: str, payload: dict) -> int:
        import json
        alert = self.create(
            resolved_event_id=resolved_event_id,
            channel=channel,
            alert_status="pending",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        return alert.alert_id if alert.alert_id else 0

    def list_pending(self, channel: str, limit: int = 100) -> list[AlertLog]:
        with self.db.get_connection(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM alert_log
                WHERE channel = ? AND alert_status = 'pending'
                ORDER BY alert_id
                LIMIT ?
                """,
                [channel, limit],
            ).fetchall()
            return [self._row_to_log(row) for row in rows]

    def _row_to_log(self, row: Any) -> AlertLog:
        return AlertLog(
            alert_id=row[0],
            resolved_event_id=row[1],
            channel=row[2],
            alert_status=row[3],
            sent_at=_dt(row[4]),
            payload_json=row[5],
        )


class LlmInsightRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, raw_event_id: int, insight: dict) -> int:
        with self.db.get_connection() as conn:
            insight_json = json.dumps(insight, ensure_ascii=False)
            max_result = conn.execute("SELECT COALESCE(MAX(insight_id), 0) FROM llm_insight").fetchone()
            next_id = (max_result[0] if max_result[0] else 0) + 1
            conn.execute(
                """
                INSERT INTO llm_insight(insight_id, raw_event_id, document_id, model_used, provider, prompt_tokens, completion_tokens, insight_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_event_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    model_used = excluded.model_used,
                    provider = excluded.provider,
                    prompt_tokens = excluded.prompt_tokens,
                    completion_tokens = excluded.completion_tokens,
                    insight_json = excluded.insight_json
                """,
                [next_id, raw_event_id, insight.get("document_id"), insight.get("model_used", ""), insight.get("provider", ""), insight.get("prompt_tokens", 0), insight.get("completion_tokens", 0), insight_json],
            )
            return next_id

    def get_by_raw_event(self, raw_event_id: int) -> dict | None:
        with self.db.get_connection(read_only=True) as conn:
            row = conn.execute("SELECT * FROM llm_insight WHERE raw_event_id = ?", [raw_event_id]).fetchone()
            if not row:
                return None
            return json.loads(row[7]) if row[7] else {}


class SchedulerStateRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_or_create(self) -> dict:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM scheduler_state ORDER BY state_id DESC LIMIT 1").fetchone()
            if not row:
                conn.execute("INSERT INTO scheduler_state(state_id) VALUES (1)")
                return {"last_heartbeat": None, "last_cycle_at": None, "error_count": 0}
            return {
                "last_heartbeat": _dt(row[1]),
                "last_cycle_at": _dt(row[2]),
                "cycle_stats_json": row[3],
                "error_count": row[4],
            }

    def update_heartbeat(self, stats: dict | None = None) -> None:
        with self.db.get_connection() as conn:
            stats_json = json.dumps(stats) if stats else None
            conn.execute(
                "UPDATE scheduler_state SET last_heartbeat = CURRENT_TIMESTAMP, last_cycle_at = CURRENT_TIMESTAMP, cycle_stats_json = ? WHERE state_id = 1",
                [stats_json],
            )

    def increment_error(self) -> None:
        with self.db.get_connection() as conn:
            conn.execute("UPDATE scheduler_state SET error_count = error_count + 1 WHERE state_id = 1")


# ---------------------------------------------------------------------------
# New repositories for Phase 0.1 collectors
# ---------------------------------------------------------------------------


@dataclass
class BulkDeal:
    bulk_deal_id: Optional[int] = None
    trade_date: Optional[datetime] = None
    symbol: str = ""
    exchange: str = ""
    client_name: Optional[str] = None
    side: str = ""
    quantity: Optional[int] = None
    avg_price: Optional[float] = None
    deal_value_cr: Optional[float] = None
    is_block: bool = False
    source_url: Optional[str] = None
    deal_hash: str = ""
    ingested_at: Optional[datetime] = None


@dataclass
class InsiderTrade:
    insider_trade_id: Optional[int] = None
    symbol: str = ""
    person_name: Optional[str] = None
    designation: Optional[str] = None
    relation_to_company: Optional[str] = None
    txn_type: Optional[str] = None
    quantity: Optional[int] = None
    value_cr: Optional[float] = None
    txn_date: Optional[datetime] = None
    disclosed_date: Optional[datetime] = None
    holding_pre_pct: Optional[float] = None
    holding_post_pct: Optional[float] = None
    source_url: Optional[str] = None
    txn_hash: str = ""
    ingested_at: Optional[datetime] = None


@dataclass
class RatingChange:
    rating_change_id: Optional[int] = None
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    agency: str = ""
    instrument: Optional[str] = None
    old_rating: Optional[str] = None
    new_rating: Optional[str] = None
    action: Optional[str] = None
    rationale_excerpt: Optional[str] = None
    dated: Optional[datetime] = None
    source_url: Optional[str] = None
    change_hash: str = ""
    ingested_at: Optional[datetime] = None


@dataclass
class SastFiling:
    sast_filing_id: Optional[int] = None
    symbol: str = ""
    acquirer_name: Optional[str] = None
    regulation: Optional[str] = None
    txn_type: Optional[str] = None
    pre_acquisition_pct: Optional[float] = None
    post_acquisition_pct: Optional[float] = None
    quantity: Optional[int] = None
    value_cr: Optional[float] = None
    txn_date: Optional[datetime] = None
    disclosed_date: Optional[datetime] = None
    source_url: Optional[str] = None
    filing_hash: str = ""
    ingested_at: Optional[datetime] = None


class BulkDealRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        trade_date: Any,
        symbol: str,
        exchange: str,
        side: str,
        client_name: Optional[str] = None,
        quantity: Optional[int] = None,
        avg_price: Optional[float] = None,
        deal_value_cr: Optional[float] = None,
        is_block: bool = False,
        source_url: Optional[str] = None,
        deal_hash: str,
    ) -> BulkDeal:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT bulk_deal_id FROM bulk_deal WHERE deal_hash = ?",
                [deal_hash],
            ).fetchone()
            if row:
                return BulkDeal(bulk_deal_id=row[0], deal_hash=deal_hash)

            conn.execute(
                """
                INSERT INTO bulk_deal
                    (trade_date, symbol, exchange, client_name, side, quantity,
                     avg_price, deal_value_cr, is_block, source_url, deal_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    trade_date, symbol.upper(), exchange.upper(), client_name,
                    side.upper(), quantity, avg_price, deal_value_cr,
                    is_block, source_url, deal_hash,
                ],
            )
            new_id = conn.execute(
                "SELECT bulk_deal_id FROM bulk_deal WHERE deal_hash = ?",
                [deal_hash],
            ).fetchone()[0]
        return BulkDeal(
            bulk_deal_id=new_id,
            trade_date=_dt(trade_date),
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            client_name=client_name,
            side=side.upper(),
            quantity=quantity,
            avg_price=avg_price,
            deal_value_cr=deal_value_cr,
            is_block=is_block,
            source_url=source_url,
            deal_hash=deal_hash,
        )

    def list_by_symbol(
        self,
        symbol: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[BulkDeal]:
        with self.db.get_connection(read_only=True) as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM bulk_deal WHERE symbol = ? AND trade_date >= ? ORDER BY trade_date DESC LIMIT ?",
                    [symbol.upper(), since, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bulk_deal WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?",
                    [symbol.upper(), limit],
                ).fetchall()
            return [self._row_to_deal(r) for r in rows]

    def _row_to_deal(self, row: Any) -> BulkDeal:
        return BulkDeal(
            bulk_deal_id=row[0],
            trade_date=_dt(row[1]),
            symbol=row[2],
            exchange=row[3],
            client_name=row[4],
            side=row[5],
            quantity=row[6],
            avg_price=row[7],
            deal_value_cr=row[8],
            is_block=bool(row[9]),
            source_url=row[10],
            deal_hash=row[11],
            ingested_at=_dt(row[12]) if len(row) > 12 else None,
        )


class InsiderTradeRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        symbol: str,
        txn_hash: str,
        person_name: Optional[str] = None,
        designation: Optional[str] = None,
        relation_to_company: Optional[str] = None,
        txn_type: Optional[str] = None,
        quantity: Optional[int] = None,
        value_cr: Optional[float] = None,
        txn_date: Any = None,
        disclosed_date: Any = None,
        holding_pre_pct: Optional[float] = None,
        holding_post_pct: Optional[float] = None,
        source_url: Optional[str] = None,
    ) -> InsiderTrade:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT insider_trade_id FROM insider_trade WHERE txn_hash = ?",
                [txn_hash],
            ).fetchone()
            if row:
                return InsiderTrade(insider_trade_id=row[0], symbol=symbol, txn_hash=txn_hash)

            conn.execute(
                """
                INSERT INTO insider_trade
                    (symbol, person_name, designation, relation_to_company, txn_type,
                     quantity, value_cr, txn_date, disclosed_date, holding_pre_pct,
                     holding_post_pct, source_url, txn_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    symbol.upper(), person_name, designation, relation_to_company,
                    txn_type, quantity, value_cr, txn_date, disclosed_date,
                    holding_pre_pct, holding_post_pct, source_url, txn_hash,
                ],
            )
            new_id = conn.execute(
                "SELECT insider_trade_id FROM insider_trade WHERE txn_hash = ?",
                [txn_hash],
            ).fetchone()[0]
        return InsiderTrade(
            insider_trade_id=new_id,
            symbol=symbol.upper(),
            person_name=person_name,
            designation=designation,
            txn_type=txn_type,
            quantity=quantity,
            value_cr=value_cr,
            txn_date=_dt(txn_date),
            disclosed_date=_dt(disclosed_date),
            txn_hash=txn_hash,
        )

    def list_by_symbol(
        self,
        symbol: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[InsiderTrade]:
        with self.db.get_connection(read_only=True) as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM insider_trade WHERE symbol = ? AND txn_date >= ? ORDER BY txn_date DESC LIMIT ?",
                    [symbol.upper(), since, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM insider_trade WHERE symbol = ? ORDER BY txn_date DESC LIMIT ?",
                    [symbol.upper(), limit],
                ).fetchall()
            return [self._row_to_trade(r) for r in rows]

    def _row_to_trade(self, row: Any) -> InsiderTrade:
        return InsiderTrade(
            insider_trade_id=row[0],
            symbol=row[1],
            person_name=row[2],
            designation=row[3],
            relation_to_company=row[4],
            txn_type=row[5],
            quantity=row[6],
            value_cr=row[7],
            txn_date=_dt(row[8]),
            disclosed_date=_dt(row[9]),
            holding_pre_pct=row[10],
            holding_post_pct=row[11],
            source_url=row[12],
            txn_hash=row[13],
            ingested_at=_dt(row[14]) if len(row) > 14 else None,
        )


class RatingChangeRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        change_hash: str,
        agency: str,
        symbol: Optional[str] = None,
        company_name: Optional[str] = None,
        instrument: Optional[str] = None,
        old_rating: Optional[str] = None,
        new_rating: Optional[str] = None,
        action: Optional[str] = None,
        rationale_excerpt: Optional[str] = None,
        dated: Any = None,
        source_url: Optional[str] = None,
    ) -> RatingChange:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT rating_change_id FROM rating_change WHERE change_hash = ?",
                [change_hash],
            ).fetchone()
            if row:
                return RatingChange(rating_change_id=row[0], agency=agency, change_hash=change_hash)

            conn.execute(
                """
                INSERT INTO rating_change
                    (symbol, company_name, agency, instrument, old_rating, new_rating,
                     action, rationale_excerpt, dated, source_url, change_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    symbol.upper() if symbol else None, company_name, agency,
                    instrument, old_rating, new_rating, action,
                    rationale_excerpt, dated, source_url, change_hash,
                ],
            )
            new_id = conn.execute(
                "SELECT rating_change_id FROM rating_change WHERE change_hash = ?",
                [change_hash],
            ).fetchone()[0]
        return RatingChange(
            rating_change_id=new_id,
            symbol=symbol,
            company_name=company_name,
            agency=agency,
            instrument=instrument,
            old_rating=old_rating,
            new_rating=new_rating,
            action=action,
            dated=_dt(dated),
            change_hash=change_hash,
        )

    def list_by_symbol(
        self,
        symbol: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[RatingChange]:
        with self.db.get_connection(read_only=True) as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM rating_change WHERE symbol = ? AND dated >= ? ORDER BY dated DESC LIMIT ?",
                    [symbol.upper(), since, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM rating_change WHERE symbol = ? ORDER BY dated DESC LIMIT ?",
                    [symbol.upper(), limit],
                ).fetchall()
            return [self._row_to_change(r) for r in rows]

    def _row_to_change(self, row: Any) -> RatingChange:
        return RatingChange(
            rating_change_id=row[0],
            symbol=row[1],
            company_name=row[2],
            agency=row[3],
            instrument=row[4],
            old_rating=row[5],
            new_rating=row[6],
            action=row[7],
            rationale_excerpt=row[8],
            dated=_dt(row[9]),
            source_url=row[10],
            change_hash=row[11],
            ingested_at=_dt(row[12]) if len(row) > 12 else None,
        )


class SastFilingRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(
        self,
        *,
        symbol: str,
        filing_hash: str,
        acquirer_name: Optional[str] = None,
        regulation: Optional[str] = None,
        txn_type: Optional[str] = None,
        pre_acquisition_pct: Optional[float] = None,
        post_acquisition_pct: Optional[float] = None,
        quantity: Optional[int] = None,
        value_cr: Optional[float] = None,
        txn_date: Any = None,
        disclosed_date: Any = None,
        source_url: Optional[str] = None,
    ) -> SastFiling:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT sast_filing_id FROM sast_filing WHERE filing_hash = ?",
                [filing_hash],
            ).fetchone()
            if row:
                return SastFiling(sast_filing_id=row[0], symbol=symbol, filing_hash=filing_hash)

            conn.execute(
                """
                INSERT INTO sast_filing
                    (symbol, acquirer_name, regulation, txn_type, pre_acquisition_pct,
                     post_acquisition_pct, quantity, value_cr, txn_date, disclosed_date,
                     source_url, filing_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    symbol.upper(), acquirer_name, regulation, txn_type,
                    pre_acquisition_pct, post_acquisition_pct, quantity, value_cr,
                    txn_date, disclosed_date, source_url, filing_hash,
                ],
            )
            new_id = conn.execute(
                "SELECT sast_filing_id FROM sast_filing WHERE filing_hash = ?",
                [filing_hash],
            ).fetchone()[0]
        return SastFiling(
            sast_filing_id=new_id,
            symbol=symbol.upper(),
            acquirer_name=acquirer_name,
            regulation=regulation,
            txn_type=txn_type,
            pre_acquisition_pct=pre_acquisition_pct,
            post_acquisition_pct=post_acquisition_pct,
            quantity=quantity,
            value_cr=value_cr,
            txn_date=_dt(txn_date),
            disclosed_date=_dt(disclosed_date),
            filing_hash=filing_hash,
        )

    def list_by_symbol(
        self,
        symbol: str,
        *,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[SastFiling]:
        with self.db.get_connection(read_only=True) as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM sast_filing WHERE symbol = ? AND txn_date >= ? ORDER BY txn_date DESC LIMIT ?",
                    [symbol.upper(), since, limit],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sast_filing WHERE symbol = ? ORDER BY txn_date DESC LIMIT ?",
                    [symbol.upper(), limit],
                ).fetchall()
            return [self._row_to_filing(r) for r in rows]

    def _row_to_filing(self, row: Any) -> SastFiling:
        return SastFiling(
            sast_filing_id=row[0],
            symbol=row[1],
            acquirer_name=row[2],
            regulation=row[3],
            txn_type=row[4],
            pre_acquisition_pct=row[5],
            post_acquisition_pct=row[6],
            quantity=row[7],
            value_cr=row[8],
            txn_date=_dt(row[9]),
            disclosed_date=_dt(row[10]),
            source_url=row[11],
            filing_hash=row[12],
            ingested_at=_dt(row[13]) if len(row) > 13 else None,
        )