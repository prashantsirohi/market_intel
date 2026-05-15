"""One-shot LLM enrichment job for resolved market_intel events.

The job is intentionally idempotent: every raw_event_id has at most one current
llm_insight row, and reruns update that row instead of appending duplicates.
When no OpenRouter key is configured it still writes deterministic fallback
insights so downstream reports can cite stable summaries without making a
network call.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from processing.llm_analyser import LlmAnalyser
from processing.taxonomy import IGNORE_CATEGORIES, PDF_LLM_CATEGORIES
from settings import settings
from storage.db import Database

logger = logging.getLogger(__name__)

DEFAULT_EVENT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_CLASSIFIER_MODEL = "qwen/qwen3-235b-a22b-2507"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich resolved market_intel events with current LLM insight rows")
    parser.add_argument("--db-path", default=os.environ.get("MARKET_INTEL_DB_PATH", settings.db_path))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--model", default=os.environ.get("MARKET_INTEL_EVENT_LLM_MODEL", DEFAULT_EVENT_MODEL))
    parser.add_argument("--classifier-model", default=os.environ.get("MARKET_INTEL_CLASSIFIER_LLM_MODEL", DEFAULT_CLASSIFIER_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    parser.add_argument("--symbols", default="", help="Comma-separated portfolio/watchlist/top-ranked symbols to prioritize")
    parser.add_argument("--dry-run", action="store_true", help="Print candidate insights without writing them")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = parse_args()
    db = Database(args.db_path, fresh=False)
    api_key = settings.openrouter_api_key
    priority_symbols = _parse_symbols(args.symbols)
    try:
        candidates = _load_candidates(db, limit=args.limit, priority_symbols=priority_symbols)
        analyser = (
            LlmAnalyser(api_key=api_key, model=args.model, base_url=args.base_url, max_tokens=1200)
            if settings.openrouter_configured
            else None
        )
        stats = {"candidates": len(candidates), "written": 0, "llm_used": 0, "deterministic": 0, "skipped": 0}
        for row in candidates:
            insight = _build_insight(row, analyser=analyser)
            if insight is None:
                stats["skipped"] += 1
                continue
            if insight.get("provider") == "openrouter":
                stats["llm_used"] += 1
            else:
                stats["deterministic"] += 1
            if args.dry_run:
                print(json.dumps(insight, indent=2, default=str))
                continue
            db.llm_insight_repo().upsert(int(row["raw_event_id"]), insight)
            stats["written"] += 1
        try:
            state_repo = db.scheduler_state_repo()
            state_repo.get_or_create()
            state_repo.update_heartbeat({"llm_enrich": stats})
        except Exception as exc:
            logger.warning("Failed to update LLM heartbeat: %s", exc)
        logger.info("LLM enrich complete: %s", stats)
        print(stats)
        return 0
    except Exception as exc:
        logger.error("LLM enrichment failed: %s", exc, exc_info=True)
        try:
            state_repo = db.scheduler_state_repo()
            state_repo.get_or_create()
            state_repo.increment_error()
        except Exception:
            pass
        return 1
    finally:
        db.close()


def _parse_symbols(raw: str) -> set[str]:
    return {part.strip().upper() for part in str(raw or "").split(",") if part.strip()}


def _load_candidates(db: Database, *, limit: int, priority_symbols: set[str]) -> list[dict[str, Any]]:
    with db.get_connection(read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT
                r.raw_event_id,
                re.resolved_event_id,
                r.symbol,
                r.company_name,
                r.title,
                r.description,
                r.link,
                r.attachment_url,
                re.primary_category,
                re.event_tier,
                re.alert_level,
                re.importance_score,
                re.trust_score,
                re.novelty_score,
                re.risk_flags_json,
                fd.document_id,
                fd.extracted_text,
                li.insight_id
            FROM resolved_event re
            JOIN raw_event r ON r.raw_event_id = re.raw_event_id
            LEFT JOIN filing_document fd ON fd.raw_event_id = r.raw_event_id
            LEFT JOIN llm_insight li ON li.raw_event_id = r.raw_event_id
            WHERE COALESCE(re.primary_category, '') NOT IN (
                'nav_update',
                'newspaper_publication',
                'investor_meet',
                'agm_notice',
                'compliance_certificate',
                'loss_of_certificate',
                'analyst_call'
            )
              AND (
                    re.alert_level IN ('critical', 'important')
                 OR re.primary_category IN (
                    'results',
                    'management_change',
                    'regulatory_legal',
                    'buyback',
                    'major_order_win',
                    'capex_expansion',
                    'fundraise',
                    'mna_partnership'
                 )
                 OR UPPER(COALESCE(r.symbol, '')) IN (SELECT UNNEST(?))
              )
            ORDER BY
                CASE WHEN li.insight_id IS NULL THEN 0 ELSE 1 END,
                CASE re.alert_level WHEN 'critical' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                COALESCE(re.importance_score, 0) DESC,
                r.ingested_at DESC
            LIMIT ?
            """,
            [list(priority_symbols), int(limit)],
        ).fetchall()
        cols = [item[0] for item in conn.description]
    return [dict(zip(cols, row)) for row in rows]


def _build_insight(row: dict[str, Any], *, analyser: LlmAnalyser | None) -> dict[str, Any] | None:
    category = str(row.get("primary_category") or "general")
    if category in IGNORE_CATEGORIES:
        return None
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "").strip()
    text = str(row.get("extracted_text") or description or title)
    should_call_llm = (
        analyser is not None
        and category in PDF_LLM_CATEGORIES
        and len(text.strip()) >= 50
    )

    if should_call_llm:
        payload = analyser.analyse(
            extracted_text=text,
            filing_title=title,
            symbol=str(row.get("symbol") or ""),
            nse_category=category,
        )
        data = payload.to_dict()
        summary = data.get("one_line_summary") or title[:160]
        key_facts = data.get("key_highlights") or []
        risk_flags = data.get("risk_flags") or _parse_json_list(row.get("risk_flags_json"))
        provider = "openrouter"
        model_used = payload.model_used or analyser.model
        prompt_tokens = int(data.get("prompt_tokens") or 0)
        completion_tokens = int(data.get("completion_tokens") or 0)
    else:
        summary = _deterministic_summary(title=title, description=description, category=category)
        key_facts = [item for item in [title[:180], description[:220]] if item]
        risk_flags = _parse_json_list(row.get("risk_flags_json"))
        provider = "deterministic"
        model_used = "deterministic-event-summary"
        prompt_tokens = 0
        completion_tokens = 0

    insight_json = {
        "summary": summary,
        "key_facts": key_facts[:6],
        "sentiment": "neutral",
        "risk_flags": risk_flags[:6],
        "impact_horizon": _impact_horizon(category),
        "source_ids": {
            "raw_event_id": row.get("raw_event_id"),
            "resolved_event_id": row.get("resolved_event_id"),
            "document_id": row.get("document_id"),
        },
        "category": category,
        "alert_level": row.get("alert_level"),
        "importance_score": row.get("importance_score"),
        "trust_score": row.get("trust_score"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "document_id": row.get("document_id"),
        "model_used": model_used,
        "provider": provider,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "insight_json": insight_json,
        **insight_json,
    }


def _deterministic_summary(*, title: str, description: str, category: str) -> str:
    base = title or description or "Corporate event"
    return f"{category}: {base[:180]}"


def _impact_horizon(category: str) -> str:
    if category in {"results", "board_meeting", "dividend"}:
        return "near_term"
    if category in {"capex_expansion", "mna_partnership", "fundraise", "major_order_win"}:
        return "medium_term"
    if category in {"regulatory_legal", "management_change", "promoter_activity"}:
        return "monitor"
    return "unknown"


def _parse_json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded if item]
    return []


if __name__ == "__main__":
    sys.exit(main())
