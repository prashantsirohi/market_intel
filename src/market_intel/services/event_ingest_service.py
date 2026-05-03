from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EventIngestService:
    def __init__(self, raw_repo, analysis_service) -> None:
        self.raw_repo = raw_repo
        self.analysis_service = analysis_service

    def process_rss_item(self, item: dict) -> dict:
        from market_intel.processing.deduper import build_event_hash as build_hash

        source = item.get("source") or "nse"
        source_type = item.get("source_type") or "official"
        pub_date = item.get("pub_date")
        if hasattr(pub_date, "isoformat"):
            event_date_key = pub_date.isoformat()
        else:
            event_date_key = str(pub_date or "")
        
        try:
            event_hash = build_hash(
                source=source,
                symbol=item.get("symbol") or "",
                title=item.get("title") or "",
                event_date=event_date_key,
                attachment_url=item.get("attachment_url"),
                external_id=item.get("guid"),
            )
        except Exception as e:
            logger.warning(f"Failed to build hash: {e}")
            return {"status": "error", "error": str(e)}
        
        try:
            existing = self.raw_repo.get_by_hash(event_hash) if hasattr(self.raw_repo, 'get_by_hash') else None
            if existing:
                return {"status": "duplicate", "raw_event_id": existing.get("raw_event_id", 0), "event_hash": event_hash}
        except Exception as e:
            logger.warning(f"Check existing failed: {e}")
        
        try:
            inserted = self.raw_repo.upsert_event(
                source=source,
                source_type=source_type,
                external_id=item.get("guid"),
                symbol=item.get("symbol"),
                title=item.get("title"),
                event_date=item.get("pub_date"),
                link=item.get("link"),
                attachment_url=item.get("attachment_url"),
                description=item.get("description"),
                raw_payload=item,
            )
        except Exception as e:
            logger.error(f"Insert failed: {e}")
            return {"status": "error", "error": str(e)}
        
        if not inserted:
            return {"status": "error", "error": "No inserted result"}
        
        seen = 1
        if hasattr(inserted, 'seen_count'):
            seen = inserted.seen_count or 1
        
        if seen > 1:
            return {"status": "duplicate", "raw_event_id": inserted.raw_event_id if inserted else 0, "event_hash": event_hash}
        
        try:
            raw_event = {
                "source": source,
                "source_type": source_type,
                "source_event_type": "rss_official",
                "title": item.get("title"),
                "description": item.get("description"),
                "symbol": item.get("symbol"),
            }
            resolved = self.analysis_service.process_raw_event(raw_event, inserted.raw_event_id)
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {"status": "error", "error": str(e)}
        
        return {
            "status": "new",
            "raw_event_id": inserted.raw_event_id,
            "resolved_event_id": resolved["resolved_event_id"],
            "alert_level": resolved["alert_level"],
            "resolved": resolved,
        }
