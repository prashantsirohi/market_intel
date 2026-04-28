from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


ALERT_STATUS = {
    "pending": "pending",
    "critical_sent": "critical_sent", 
    "enriched_queued": "enriched_queued",
    "enriched_sent": "enriched_sent",
    "failed": "failed",
    "skipped": "skipped",
}


@dataclass
class AlertPayload:
    resolved_event_id: int
    raw_event_id: int
    symbol: str | None = None
    title: str = ""
    category: str = "general"
    tier: str = "GENERAL"
    importance_score: float = 5.0
    alert_level: str = "info"
    trust_score: float = 50.0
    is_official: bool = False
    
    summary: str = ""
    
    attachment_url: str = ""
    pdf_local_path: str | None = None
    pdf_status: str = "pending"
    
    llm_enriched: bool = False
    llm_summary: str = ""
    llm_relevance_score: float | None = None
    
    final_importance_score: float | None = None
    
    created_at: datetime = field(default_factory=datetime.now)
    enriched_at: datetime | None = None
    
    def to_telegram_text(self) -> str:
        tier_emoji = {"A": "🔴", "B": "🟠", "C": "🟡", "GENERAL": "⚪", "IGNORE": "❌"}
        
        header = f"{tier_emoji.get(self.tier, '⚪')} <b>{self.alert_level.upper()}</b>"
        
        if self.symbol:
            header += f" | {self.symbol}"
        
        body = f"\n{self.title[:200]}"
        
        if self.pdf_local_path and self.pdf_status == "ok":
            body += f"\n📎 PDF attached"
        
        if self.llm_enriched and self.llm_summary:
            body += f"\n\n💡 <b>LLM Insight:</b>\n{self.llm_summary[:300]}"
        
        footer = f"\n\n_imp:{self.importance_score}_ | trust:{self.trust_score}_"
        
        return header + body + footer
    
    def to_enriched_text(self) -> str:
        if not self.llm_enriched:
            return ""
        
        tier_emoji = {"A": "🔴", "B": "🟠", "C": "🟡"}
        
        header = f"{tier_emoji.get(self.tier, '⚪')} <b>ENRICHED</b> | {self.symbol or 'N/A'}"
        header += f"\n_imp: {self.final_importance_score or self.importance_score}_"
        
        body = f"\n{self.llm_summary[:500]}"
        
        return header + body


class TwoPassAlerter:
    def __init__(
        self,
        telegram_client=None,
        pdf_fetcher=None,
        llm_analyser=None,
        batch_interval_sec: int = 900,
    ):
        self.telegram = telegram_client
        self.pdf_fetcher = pdf_fetcher
        self.llm_analyser = llm_analyser
        self.batch_interval_sec = batch_interval_sec
        
        self._pending_enriched: list[AlertPayload] = []

    def process_alert(self, resolved_event: dict, raw_event: dict) -> dict:
        category = resolved_event.get("primary_category", "general")
        alert_level = resolved_event.get("alert_level", "info")
        
        payload = AlertPayload(
            resolved_event_id=resolved_event.get("resolved_event_id", 0),
            raw_event_id=resolved_event.get("raw_event_id", 0),
            symbol=raw_event.get("symbol"),
            title=raw_event.get("title", ""),
            attachment_url=raw_event.get("attachment_url", ""),
            category=category,
            tier=resolved_event.get("event_tier", "GENERAL"),
            importance_score=resolved_event.get("importance_score", 5.0),
            alert_level=alert_level,
            trust_score=resolved_event.get("trust_score", 50.0),
            is_official=resolved_event.get("is_official", False),
            summary=raw_event.get("title", "")[:120],
        )
        
        if alert_level == "critical":
            self._send_critical_alert(payload)
            return {"status": "critical_sent", "payload": payload.to_telegram_text()}
        
        if alert_level == "important":
            self._queue_for_enrichment(payload)
            return {"status": "enriched_queued", "payload": "Queued for LLM enrichment"}
        
        return {"status": "skipped", "reason": "info level"}

    def _send_critical_alert(self, payload: AlertPayload) -> bool:
        if not self.telegram:
            logger.warning("No Telegram client configured")
            return False
        
        try:
            self.telegram.send(payload.to_telegram_text())
            logger.info(f"Critical alert sent for {payload.symbol}: {payload.title[:50]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send critical alert: {e}")
            return False

    def _queue_for_enrichment(self, payload: AlertPayload) -> None:
        from market_intel.processing.taxonomy import needs_pdf_llm
        
        if needs_pdf_llm(payload.category):
            payload.pdf_status = "needs_download"
        
        self._pending_enriched.append(payload)
        logger.info(f"Queued for enrichment: {payload.category} - {payload.title[:30]}")

    def process_enrichment_batch(self, batch_size: int = 10) -> dict:
        stats = {
            "processed": 0,
            "pdf_downloaded": 0,
            "llm_enriched": 0,
            "sent": 0,
            "failed": 0,
        }
        
        batch = self._pending_enriched[:batch_size]
        
        for payload in batch:
            try:
                if payload.pdf_status == "pending" and self.pdf_fetcher and payload.attachment_url:
                    result = self.pdf_fetcher.fetch(payload.attachment_url)
                    if result.status == "ok":
                        payload.pdf_local_path = result.local_path
                        payload.pdf_status = "downloaded"
                        stats["pdf_downloaded"] += 1
                
                if self.llm_analyser and payload.pdf_local_path:
                    from market_intel.processing.pdf_extractor import PdfExtractor
                    
                    extractor = PdfExtractor()
                    doc = extractor.extract(payload.pdf_local_path)
                    
                    insight = self.llm_analyser.analyse(
                        extracted_text=doc.full_text,
                        filing_title=payload.title,
                        symbol=payload.symbol or "",
                    )
                    
                    payload.llm_enriched = True
                    payload.llm_summary = insight.one_line_summary
                    payload.enriched_at = datetime.now()
                    
                    new_importance = insight.importance_score
                    if new_importance > payload.importance_score:
                        payload.final_importance_score = new_importance
                    
                    stats["llm_enriched"] += 1
                
                if self.telegram:
                    enriched_text = payload.to_enriched_text()
                    if enriched_text:
                        self.telegram.send(enriched_text)
                        stats["sent"] += 1
                
                stats["processed"] += 1
                
            except Exception as e:
                logger.error(f"Enrichment failed: {e}")
                stats["failed"] += 1
        
        self._pending_enriched = self._pending_enriched[batch_size:]
        
        return stats

    def get_pending_count(self) -> int:
        return len(self._pending_enriched)

    def flush(self) -> dict:
        return self.process_enrichment_batch(batch_size=100)