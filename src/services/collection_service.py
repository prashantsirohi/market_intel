"""CollectionService — orchestrates all collectors and routes items to storage.

Each collector emits ``CollectorItem`` rows; this service inspects the
``source`` field to decide which repository receives each item.  The
routing table is:

  nse_rss / bse_corp / nse_api   → raw_event → resolved_event  (EventIngestService)
  nse_bulk_block / *_deal        → bulk_deal  (BulkDealRepository)
  nse_sast                       → sast_filing (SastFilingRepository)
  nse_pit (insider)              → insider_trade (InsiderTradeRepository)
  rating_*                       → rating_change (RatingChangeRepository)

``AlertScheduler`` is a thin wrapper used by ``cli/main.py`` to dispatch
pending Telegram alerts in one call.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from collectors.base import CollectorItem

if TYPE_CHECKING:
    from storage.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deal_hash(item: CollectorItem) -> str:
    """Stable dedup hash for a bulk/block deal item."""
    p = item.raw_payload
    key = "|".join(
        str(v)
        for v in [
            p.get("trade_date") or item.event_date,
            (item.symbol or "").upper(),
            (p.get("exchange") or "").upper(),
            (p.get("side") or "").upper(),
            p.get("client_name") or "",
            p.get("quantity") or "",
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _sast_hash(item: CollectorItem) -> str:
    key = "|".join(
        str(v)
        for v in [
            (item.symbol or "").upper(),
            item.raw_payload.get("acqName") or item.raw_payload.get("acquirerName") or "",
            item.raw_payload.get("date") or item.raw_payload.get("disclosureDate") or "",
            item.raw_payload.get("afterAcqSharesPer") or item.raw_payload.get("postPct") or "",
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _insider_hash(item: CollectorItem) -> str:
    key = "|".join(
        str(v)
        for v in [
            (item.symbol or "").upper(),
            item.raw_payload.get("personName") or item.raw_payload.get("acqName") or "",
            item.raw_payload.get("acquisitionDate") or item.raw_payload.get("dateOfTransaction") or "",
            item.raw_payload.get("securitiesAcquired") or item.raw_payload.get("noOfSecAcq") or "",
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _rating_hash(item: CollectorItem) -> str:
    p = item.raw_payload
    key = "|".join(
        str(v)
        for v in [
            p.get("agency") or "",
            (item.company_name or item.symbol or "").upper(),
            p.get("new_rating") or "",
            str(item.event_date.date() if isinstance(item.event_date, datetime) else item.event_date or ""),
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)).date()
    except ValueError:
        pass
    # Try DD-Mon-YYYY or DD/MM/YYYY
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Source-to-repo routing
# ---------------------------------------------------------------------------


def _route_bulk_deal(item: CollectorItem, db: "Database") -> bool:
    """Insert one bulk/block deal into bulk_deal table. Returns True if new."""
    p = item.raw_payload
    deal_hash = _deal_hash(item)
    trade_date = _parse_date(p.get("trade_date") or item.event_date)
    if not trade_date or not item.symbol:
        return False

    is_block = str(p.get("deal_kind") or "").lower() == "block"
    exchange = (
        p.get("exchange")
        or ("NSE" if "nse" in item.source else "BSE")
    ).upper()
    deal = db.bulk_deal_repo().upsert(
        trade_date=trade_date,
        symbol=item.symbol,
        exchange=exchange,
        side=(p.get("side") or "").upper(),
        client_name=p.get("client_name"),
        quantity=_to_int(p.get("quantity")),
        avg_price=_to_float(p.get("avg_price")),
        deal_value_cr=_to_float(p.get("deal_value_cr")),
        is_block=is_block,
        source_url=item.link,
        deal_hash=deal_hash,
    )
    return deal.bulk_deal_id is not None


def _route_sast(item: CollectorItem, db: "Database") -> bool:
    p = item.raw_payload
    filing_hash = _sast_hash(item)
    if not item.symbol:
        return False

    pre_pct = _to_float(p.get("befAcqSharesPer") or p.get("prePct"))
    post_pct = _to_float(p.get("afterAcqSharesPer") or p.get("postPct"))
    qty = _to_int(p.get("noOfShareAcq") or p.get("noOfShare"))

    filing = db.sast_filing_repo().upsert(
        symbol=item.symbol,
        filing_hash=filing_hash,
        acquirer_name=(p.get("acqName") or p.get("acquirerName") or "").strip() or None,
        regulation=(p.get("regulation") or p.get("regNo") or "").strip() or None,
        txn_type=(p.get("typeOfTransaction") or p.get("acqMode") or "").strip() or None,
        pre_acquisition_pct=pre_pct,
        post_acquisition_pct=post_pct,
        quantity=qty,
        txn_date=_parse_date(p.get("date") or p.get("disclosureDate") or p.get("acqDate")),
        disclosed_date=_parse_date(p.get("disclosureDate") or p.get("date")),
        source_url=item.link,
    )
    return filing.sast_filing_id is not None


def _route_insider(item: CollectorItem, db: "Database") -> bool:
    p = item.raw_payload
    txn_hash = _insider_hash(item)
    if not item.symbol:
        return False

    txn_type = p.get("_normalized_txn_type") or p.get("acqMode") or p.get("buyOrSell")
    qty = _to_int(p.get("securitiesAcquired") or p.get("noOfSecAcq"))
    value_raw = _to_float(p.get("securityValue") or p.get("transactionValue"))
    value_cr = (value_raw / 1e7) if value_raw and value_raw > 1e5 else value_raw

    trade = db.insider_trade_repo().upsert(
        symbol=item.symbol,
        txn_hash=txn_hash,
        person_name=(p.get("personName") or p.get("acqName") or p.get("nameOfPerson") or "").strip() or None,
        designation=(p.get("personCategory") or p.get("designation") or "").strip() or None,
        txn_type=str(txn_type).upper() if txn_type else None,
        quantity=qty,
        value_cr=value_cr,
        txn_date=_parse_date(p.get("acquisitionDate") or p.get("dateOfTransaction")),
        disclosed_date=_parse_date(p.get("date") or p.get("disclosureDate")),
        holding_pre_pct=_to_float(p.get("befAcqSharesPer") or p.get("preHoldingPct")),
        holding_post_pct=_to_float(p.get("afterAcqSharesPer") or p.get("postHoldingPct")),
        source_url=item.link,
    )
    return trade.insider_trade_id is not None


def _route_rating(item: CollectorItem, db: "Database") -> bool:
    p = item.raw_payload
    change_hash = _rating_hash(item)

    change = db.rating_change_repo().upsert(
        change_hash=change_hash,
        agency=p.get("agency") or item.source.replace("rating_", "").upper(),
        symbol=item.symbol,
        company_name=item.company_name,
        instrument=p.get("instrument"),
        old_rating=p.get("old_rating"),
        new_rating=p.get("new_rating"),
        action=p.get("action"),
        rationale_excerpt=(item.description or "")[:500] or None,
        dated=_parse_date(item.event_date),
        source_url=item.link,
    )
    return change.rating_change_id is not None


_RSS_SYMBOL_RE = re.compile(
    r"""
    (?:^|\s|\[|\()          # word boundary or bracket
    ([A-Z][A-Z0-9&]{1,19})  # ticker: 2–20 uppercase chars
    (?:\s*[-:]\s*EQ\b|\]|\)|$|\s)   # suffix: -EQ, :EQ, ], ), end, or space
    """,
    re.VERBOSE,
)


def _extract_rss_symbol(title: str, description: str) -> str | None:
    """Best-effort symbol extraction from an NSE RSS title/description.

    NSE titles commonly look like:
      "Board Meeting - RELIANCE - Results"
      "RELIANCE: Disclosure under Reg 30"
      "[INFY] Analyst meet outcome"
    """
    text = (title or "") + " " + (description or "")
    m = _RSS_SYMBOL_RE.search(text)
    if m:
        return m.group(1).upper()
    return None


def _route_rss_event(item: CollectorItem, ingest_svc: Any) -> dict:
    """Route an RSS/API corp-announcement item through EventIngestService."""
    record = {
        "source": item.source,
        "source_type": "official",
        "title": item.title,
        "link": item.link,
        "pub_date": item.published_at or item.event_date,
        "description": item.description,
        "guid": item.external_id,
        "symbol": item.symbol,
        "isin": item.isin,
        "company_name": item.company_name,
        "category_desc": item.raw_payload.get("category") or item.raw_payload.get("announcementType"),
        "attachment_url": item.attachment_url,
        "raw_payload": item.raw_payload,
    }
    result = ingest_svc.process_rss_item(record)
    if result.get("status") == "new" and not result.get("raw_event"):
        raw_event_id = result.get("raw_event_id")
        if raw_event_id:
            result["raw_event"] = type("RawEvent", (), {
                "raw_event_id": raw_event_id,
                "attachment_url": item.attachment_url,
            })()
    return result


# ---------------------------------------------------------------------------
# CollectionService
# ---------------------------------------------------------------------------


class CollectionService:
    """Runs all collectors and routes items to the appropriate repositories.

    Collectors are imported lazily so missing optional dependencies (e.g.
    requests) don't crash the import of the service module.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    # -- public entry point --------------------------------------------------

    def run_collection(self, *, sources: list[str] | None = None) -> dict:
        """Run all (or a subset of) collectors and return a summary dict.

        ``sources`` is an optional allowlist of source names, e.g.
        ``["nse_rss", "nse_bulk_block"]``.  Pass ``None`` to run all.
        """
        summary: dict[str, int] = {
            "rss_processed": 0,
            "rss_new": 0,
            "bulk_deal_new": 0,
            "sast_new": 0,
            "insider_new": 0,
            "rating_new": 0,
            "bse_corp_new": 0,
            "pdf_fetched": 0,
            "pdf_extracted": 0,
            "failed": 0,
        }

        def _want(name: str) -> bool:
            return sources is None or name in sources

        if _want("nse_rss"):
            self._run_nse_rss(summary)

        if _want("bse_corp"):
            self._run_bse_corp(summary)

        if _want("nse_bulk_block"):
            self._run_bulk_block(summary)

        if _want("nse_sast"):
            self._run_sast(summary)

        if _want("nse_pit"):
            self._run_insider(summary)

        if _want("credit_rating"):
            self._run_credit_rating(summary)

        summary["total"] = (
            summary["rss_processed"]
            + summary["bulk_deal_new"]
            + summary["sast_new"]
            + summary["insider_new"]
            + summary["rating_new"]
            + summary["bse_corp_new"]
        )
        return summary

    # -- per-source runners --------------------------------------------------

    def _run_nse_rss(self, summary: dict) -> None:
        try:
            from collectors.nse_rss import NseRssClient
        except ImportError:
            logger.warning("nse_rss collector not available")
            return

        ingest_svc = self._ingest_svc()
        try:
            items = list(NseRssClient().fetch_all())
        except Exception as exc:
            logger.error("NSE RSS fetch failed: %s", exc)
            summary["failed"] += 1
            return

        for item in items:
            # NseRssClient returns RssItem (title/link/description/pub_date/guid),
            # not CollectorItem — build the ingest record directly.
            summary["rss_processed"] += 1
            symbol = _extract_rss_symbol(item.title or "", item.description or "")
            record = {
                "source": "nse_rss",
                "source_type": "official",
                "title": item.title,
                "link": item.link,
                "pub_date": item.pub_date,
                "description": item.description,
                "guid": getattr(item, "guid", getattr(item, "raw_guid", None)),
                "symbol": symbol,
                "attachment_url": getattr(item, "attachment_url", None),
                "raw_payload": getattr(item, "raw", {}),
            }
            try:
                result = ingest_svc.process_rss_item(record)
                if result.get("status") == "new":
                    summary["rss_new"] += 1
                    raw_event = result.get("raw_event")
                    if raw_event and getattr(raw_event, "attachment_url", None):
                        from processing.taxonomy import needs_pdf_llm
                        resolved = result.get("resolved") or {}
                        category = resolved.get("primary_category") or "general"
                        if needs_pdf_llm(category):
                            self._process_pdf(raw_event, summary)
            except Exception as exc:
                logger.warning("NSE RSS ingest failed for %s: %s", symbol, exc)
                summary["failed"] += 1

    def _run_bse_corp(self, summary: dict) -> None:
        try:
            from collectors.bse_corp import BseCorporateCollector
        except ImportError:
            logger.warning("bse_corp collector not available")
            return

        ingest_svc = self._ingest_svc()
        collector = BseCorporateCollector()
        try:
            items = list(collector.fetch_all())
        except Exception as exc:
            logger.error("BSE Corp fetch failed: %s", exc)
            summary["failed"] += 1
            return

        bse_session = getattr(collector, "session", None)

        for item in items:
            try:
                result = _route_rss_event(item, ingest_svc)
                if result.get("status") == "new":
                    summary["bse_corp_new"] += 1
                    raw_event = result.get("raw_event")
                    if raw_event and getattr(raw_event, "attachment_url", None):
                        from processing.taxonomy import needs_pdf_llm
                        resolved = result.get("resolved") or {}
                        category = resolved.get("primary_category") or "general"
                        if needs_pdf_llm(category):
                            self._process_pdf(raw_event, summary, session=bse_session)
            except Exception as exc:
                logger.warning("BSE Corp ingest failed for %s: %s", item.symbol, exc)
                summary["failed"] += 1

    def _run_bulk_block(self, summary: dict) -> None:
        try:
            from collectors.bulk_block import NseBulkBlockCollector
        except ImportError:
            logger.warning("bulk_block collector not available")
            return

        try:
            items = list(NseBulkBlockCollector().fetch_all())
        except Exception as exc:
            logger.error("Bulk/block deal fetch failed: %s", exc)
            summary["failed"] += 1
            return

        for item in items:
            try:
                is_new = _route_bulk_deal(item, self.db)
                if is_new:
                    summary["bulk_deal_new"] += 1
            except Exception as exc:
                logger.warning("Bulk deal ingest failed for %s: %s", item.symbol, exc)
                summary["failed"] += 1

    def _run_sast(self, summary: dict) -> None:
        try:
            from collectors.sast import NseSastCollector
        except ImportError:
            logger.warning("sast collector not available")
            return

        try:
            items = list(NseSastCollector().fetch_all())
        except Exception as exc:
            logger.error("SAST fetch failed: %s", exc)
            summary["failed"] += 1
            return

        for item in items:
            try:
                is_new = _route_sast(item, self.db)
                if is_new:
                    summary["sast_new"] += 1
            except Exception as exc:
                logger.warning("SAST ingest failed for %s: %s", item.symbol, exc)
                summary["failed"] += 1

    def _run_insider(self, summary: dict) -> None:
        try:
            from collectors.insider import NseInsiderCollector
        except ImportError:
            logger.warning("insider collector not available")
            return

        try:
            items = list(NseInsiderCollector().fetch_all())
        except Exception as exc:
            logger.error("Insider trade fetch failed: %s", exc)
            summary["failed"] += 1
            return

        for item in items:
            try:
                is_new = _route_insider(item, self.db)
                if is_new:
                    summary["insider_new"] += 1
            except Exception as exc:
                logger.warning("Insider ingest failed for %s: %s", item.symbol, exc)
                summary["failed"] += 1

    def _run_credit_rating(self, summary: dict) -> None:
        try:
            from collectors.credit_rating import CreditRatingCollector
        except ImportError:
            logger.warning("credit_rating collector not available")
            return

        try:
            items = list(CreditRatingCollector().fetch_all())
        except Exception as exc:
            logger.error("Credit rating fetch failed: %s", exc)
            summary["failed"] += 1
            return

        for item in items:
            try:
                is_new = _route_rating(item, self.db)
                if is_new:
                    summary["rating_new"] += 1
            except Exception as exc:
                logger.warning("Rating ingest failed for %s: %s", item.symbol, exc)
                summary["failed"] += 1

    # -- PDF fetch & extract ---------------------------------------------------

    def _process_pdf(
        self,
        raw_event: Any,
        summary: dict,
        *,
        session: Any = None,
        enrich_llm: bool = True,
    ) -> None:
        """Fetch PDF from attachment_url, extract text, store in filing_document."""
        attachment_url = getattr(raw_event, "attachment_url", None)
        if not attachment_url:
            return

        raw_event_id = getattr(raw_event, "raw_event_id", None)
        if raw_event_id is None:
            return

        try:
            from collectors.pdf_fetcher import PdfFetcher
            from processing.pdf_extractor import PdfExtractor
            from processing.llm_analyser import LlmAnalyser, enrich_event_with_llm
            from settings import settings
        except ImportError:
            logger.warning("PDF fetcher/extractor/LLM not available")
            return

        try:
            fetcher = PdfFetcher(cache_dir="./data/pdfs", session=session)
            fetch_result = fetcher.fetch(attachment_url)

            if fetch_result.status not in ("ok", "cached"):
                self.db.filing_document_repo().upsert(
                    raw_event_id=raw_event_id,
                    source_url=attachment_url,
                    pdf_status="failed",
                    download_attempts=fetch_result.attempts,
                    error_message=fetch_result.error,
                )
                logger.warning(
                    "PDF fetch failed for event %s: %s", raw_event_id, fetch_result.error
                )
                return

            summary["pdf_fetched"] += 1

            doc_record = self.db.filing_document_repo().upsert(
                raw_event_id=raw_event_id,
                source_url=attachment_url,
                local_path=fetch_result.local_path,
                content_hash=fetch_result.content_hash,
                file_size=fetch_result.size_bytes,
                pdf_status="downloaded",
                download_attempts=fetch_result.attempts,
            )

            extractor = PdfExtractor()
            extracted = extractor.extract(fetch_result.local_path)

            self.db.filing_document_repo().upsert(
                raw_event_id=raw_event_id,
                source_url=attachment_url,
                local_path=fetch_result.local_path,
                content_hash=fetch_result.content_hash,
                file_size=fetch_result.size_bytes,
                pdf_status="ok",
                extraction_method=extracted.extraction_method,
                extracted_text=extracted.full_text,
                download_attempts=fetch_result.attempts,
            )
            summary["pdf_extracted"] += 1
            logger.info(
                "PDF extracted for event %s: %d chars via %s",
                raw_event_id, extracted.char_count, extracted.extraction_method,
            )

            # Trigger inline LLM enrichment immediately
            if enrich_llm:
                analyser = None
                if settings.openrouter_configured:
                    analyser = LlmAnalyser(
                        api_key=settings.openrouter_api_key,
                        model=settings.openrouter_model,
                        base_url=settings.openrouter_base_url,
                        max_tokens=settings.openrouter_max_tokens,
                    )
                enrich_event_with_llm(self.db, raw_event_id, analyser=analyser)

        except Exception as exc:
            logger.error("PDF processing failed for event %s: %s", raw_event_id, exc)
            try:
                self.db.filing_document_repo().upsert(
                    raw_event_id=raw_event_id,
                    source_url=attachment_url,
                    pdf_status="error",
                    error_message=str(exc),
                )
            except Exception:
                pass

    # -- helpers -------------------------------------------------------------

    def _ingest_svc(self) -> Any:
        from processing.entity_resolver import EntityResolver
        from services.event_analysis_service import EventAnalysisService
        from services.event_ingest_service import EventIngestService

        raw_repo = self.db.raw_event_repo()
        resolved_repo = self.db.resolved_event_repo()
        tracked_entities = self.db.tracked_entity_repo().list_active()
        resolver = EntityResolver(tracked_entities)
        analysis_svc = EventAnalysisService(raw_repo, resolved_repo, resolver)
        return EventIngestService(raw_repo, analysis_svc)


# ---------------------------------------------------------------------------
# AlertScheduler — thin wrapper for CLI
# ---------------------------------------------------------------------------


class AlertScheduler:
    """Dispatches pending Telegram/webhook alerts via AlertService."""

    def __init__(self, db: "Database") -> None:
        self.db = db

    def check_and_send(self) -> dict:
        from services.alert_service import AlertService
        from settings import settings

        telegram = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            try:
                from alerts.telegram import TelegramAlert
                telegram = TelegramAlert(
                    settings.telegram_bot_token,
                    settings.telegram_chat_id,
                )
            except Exception as exc:
                logger.warning("Telegram not configured: %s", exc)

        alert_repo = self.db.alert_log_repo()
        svc = AlertService(alert_repo, telegram, dry_run=(telegram is None), db=self.db)

        resolved_repo = self.db.resolved_event_repo()
        criticals = resolved_repo.list_by_alert_level("critical", limit=50)
        importants = resolved_repo.list_by_alert_level("important", limit=50)

        stats = {"critical": 0, "important": 0, "failed": 0}
        for ev in criticals:
            try:
                svc.route({"resolved_event_id": ev.resolved_event_id, "alert_level": "critical", **ev.__dict__})
                stats["critical"] += 1
            except Exception as exc:
                logger.warning("Alert route failed: %s", exc)
                stats["failed"] += 1

        for ev in importants:
            try:
                svc.route({"resolved_event_id": ev.resolved_event_id, "alert_level": "important", **ev.__dict__})
                stats["important"] += 1
            except Exception as exc:
                logger.warning("Alert route failed: %s", exc)
                stats["failed"] += 1

        svc.flush_batched()
        return stats
