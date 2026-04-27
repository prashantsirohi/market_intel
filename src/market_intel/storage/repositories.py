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
                return self._row_to_event(existing)

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
            return repr(val)

        with self.db.get_connection() as conn:
            max_result = conn.execute("SELECT COALESCE(MAX(resolved_event_id), 0) FROM resolved_event").fetchone()
            next_id = (max_result[0] if max_result[0] else 0) + 1
            now = datetime.now().isoformat()
            conn.execute(
                f"""
                INSERT INTO resolved_event(resolved_event_id, raw_event_id, entity_id, primary_category, secondary_category, sentiment_label, sentiment_score, importance_score, trust_score, parser_confidence, novelty_score, alert_level, is_official, summary_text, key_facts_json, status, resolved_at, event_tier, ignored_reason)
                VALUES ({next_id}, {raw_event_id}, {_v(entity_id)}, {_v(primary_category)}, {_v(secondary_category)}, {_v(sentiment_label)}, {_v(sentiment_score)}, {_v(importance_score)}, {_v(trust_score)}, {_v(parser_confidence)}, {_v(novelty_score)}, {_v(alert_level)}, {_v(is_official)}, {_v(summary_text)}, {_v(key_facts_json)}, '{status}', '{now}', {_v(event_tier)}, {_v(ignored_reason)})
                ON CONFLICT(raw_event_id) DO UPDATE SET
                    entity_id = COALESCE(excluded.entity_id, resolved_event.entity_id),
                    primary_category = COALESCE(excluded.primary_category, resolved_event.primary_category),
                    secondary_category = COALESCE(excluded.secondary_category, resolved_event.secondary_category),
                    sentiment_label = COALESCE(excluded.sentiment_label, resolved_event.sentiment_label),
                    sentiment_score = COALESCE(excluded.sentiment_score, resolved_event.sentiment_score),
                    importance_score = COALESCE(excluded.importance_score, resolved_event.importance_score),
                    trust_score = COALESCE(excluded.trust_score, resolved_event.trust_score),
                    parser_confidence = COALESCE(excluded.parser_confidence, resolved_event.parser_confidence),
                    novelty_score = COALESCE(excluded.novelty_score, resolved_event.novelty_score),
                    alert_level = COALESCE(excluded.alert_level, resolved_event.alert_level),
                    is_official = excluded.is_official,
                    summary_text = COALESCE(excluded.summary_text, resolved_event.summary_text),
                    key_facts_json = COALESCE(excluded.key_facts_json, resolved_event.key_facts_json),
                    status = excluded.status,
                    resolved_at = '{now}',
                    event_tier = COALESCE(excluded.event_tier, resolved_event.event_tier),
                    ignored_reason = COALESCE(excluded.ignored_reason, resolved_event.ignored_reason)
                """,
            )

            row = conn.execute(
                "SELECT * FROM resolved_event WHERE raw_event_id = ?",
                [raw_event_id]
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