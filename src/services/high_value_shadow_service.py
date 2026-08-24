"""Shadow-only high-value announcement collection and routing."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Iterable

from collectors.base import CollectorItem
from processing.high_value_filter import POLICY_HASH, POLICY_VERSION, route_announcement
from services.collection_service import CollectionService, _route_rss_event
from storage.high_value_repository import HighValueShadowRepository


def _announcement_key(source: str, item: CollectorItem) -> str:
    key_seed = item.external_id or "|".join([
        item.symbol or "", item.title or "",
        item.event_date.isoformat() if item.event_date else "",
        item.attachment_url or "",
    ])
    return f"{source}:{hashlib.sha256(key_seed.encode()).hexdigest()[:24]}"


class HighValueShadowService:
    def __init__(self, db):
        self.db = db
        self.repo = HighValueShadowRepository(db)
        self.collection = CollectionService(db)

    def run_source(
        self,
        *,
        source: str,
        items: Iterable[CollectorItem],
        requested_from: datetime,
        requested_to: datetime,
        response_hashes: list[str],
        failures: list[dict[str, Any]],
        page_count: int,
        pages_complete: bool,
        download_selected: bool = False,
        session: Any = None,
        source_item_count: int | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = datetime.now(UTC)
        run_material = f"{source}|{requested_from.isoformat()}|{requested_to.isoformat()}|{started.isoformat()}|{POLICY_HASH}"
        run_id = f"high-value-v1-{hashlib.sha256(run_material.encode()).hexdigest()[:20]}"
        self.repo.start_run(
            collection_run_id=run_id, source=source,
            requested_from=requested_from, requested_to=requested_to,
            started_at=started, policy_version=POLICY_VERSION, policy_hash=POLICY_HASH,
        )
        counts: Counter[str] = Counter()
        listing_counts: Counter[str] = Counter()
        ingest = self.collection._ingest_svc()
        item_count = 0
        unique_item_count = 0
        duplicate_source_count = 0
        seen_announcement_keys: set[str] = set()
        new_count = 0
        runtime_failures = list(failures)
        attachment_failures: list[dict[str, Any]] = []
        for item in items:
            item_count += 1
            announcement_key = _announcement_key(source, item)
            if announcement_key in seen_announcement_keys:
                duplicate_source_count += 1
                continue
            seen_announcement_keys.add(announcement_key)
            unique_item_count += 1
            listing_membership = (item.raw_payload.get("_listing_master") or {}).get("listing_membership")
            listing_counts[listing_membership or "UNRESOLVED"] += 1
            decision = route_announcement(
                subject=item.title, details=item.description,
                attachment_url=item.attachment_url,
            )
            counts[decision.decision] += 1
            try:
                ingested = _route_rss_event(item, ingest)
                if ingested.get("status") == "new":
                    new_count += 1
                if ingested.get("status") == "error":
                    raise RuntimeError(str(ingested.get("error") or "ingest failed"))
                raw_event_id = ingested.get("raw_event_id")
                self.repo.record_decision(
                    collection_run_id=run_id, announcement_key=announcement_key,
                    raw_event_id=int(raw_event_id) if raw_event_id else None,
                    source=source, external_id=item.external_id, symbol=item.symbol,
                    isin=item.isin,
                    listing_membership=(item.raw_payload.get("_listing_master") or {}).get("listing_membership"),
                    exchange_security_id=(item.raw_payload.get("_listing_master") or {}).get("exchange_security_id"),
                    subject=item.title, details=item.description,
                    attachment_url=item.attachment_url, result=decision,
                )
            except Exception as exc:
                runtime_failures.append({"announcement": item.external_id or item.title, "error": str(exc)})
                continue
            if download_selected and decision.attachment_eligible and item.attachment_url and raw_event_id:
                try:
                    raw_event = type(
                        "RawEvent", (),
                        {"raw_event_id": raw_event_id, "attachment_url": item.attachment_url},
                    )()
                    pdf_summary = {"pdf_fetched": 0, "pdf_extracted": 0}
                    self.collection._process_pdf(
                        raw_event, pdf_summary, session=session, enrich_llm=False,
                    )
                    counts["PDF_FETCHED"] += pdf_summary["pdf_fetched"]
                    counts["PDF_EXTRACTED"] += pdf_summary["pdf_extracted"]
                except Exception as exc:
                    attachment_failures.append({
                        "announcement": item.external_id or item.title,
                        "error": str(exc),
                    })
                    counts["PDF_FAILED"] += 1

        completed = datetime.now(UTC)
        complete = pages_complete and not runtime_failures
        status = "COMPLETED" if complete else "DEGRADED"
        selected_count = counts["KEEP"]
        attachment_eligible = counts["KEEP"] + counts["FETCH_ATTACHMENT"]
        reduction = 1.0 - (attachment_eligible / unique_item_count) if unique_item_count else None
        fetched_source_item_count = item_count if source_item_count is None else int(source_item_count)
        summary = {
            "policy_version": POLICY_VERSION, "policy_hash": POLICY_HASH,
            "decision_counts": dict(counts),
            "fetched_item_count": fetched_source_item_count,
            "target_item_count": item_count,
            "unique_item_count": unique_item_count,
            "duplicate_source_count": duplicate_source_count,
            "listing_identity_counts": dict(listing_counts),
            "attachment_download_reduction_estimate": reduction,
            "download_selected": download_selected,
            "attachment_failure_count": len(attachment_failures),
            "attachment_failures": attachment_failures,
            "audit_context": audit_context or {},
        }
        self.repo.finish_run(
            collection_run_id=run_id, completed_at=completed, status=status,
            page_count=page_count, pages_complete=pages_complete,
            item_count=fetched_source_item_count, new_count=new_count,
            selected_count=selected_count,
            attachment_eligible_count=attachment_eligible,
            response_hashes=response_hashes, failures=runtime_failures, summary=summary,
        )
        return {
            "collection_run_id": run_id, "source": source, "status": status,
            "pages_complete": pages_complete, "item_count": fetched_source_item_count,
            "target_item_count": item_count,
            "unique_item_count": unique_item_count,
            "duplicate_source_count": duplicate_source_count,
            "listing_identity_counts": dict(listing_counts),
            "new_count": new_count, "selected_count": selected_count,
            "attachment_eligible_count": attachment_eligible,
            "attachment_download_reduction_estimate": reduction,
            "attachment_failure_count": len(attachment_failures),
            "failure_count": len(runtime_failures),
            "policy_version": POLICY_VERSION, "policy_hash": POLICY_HASH,
        }
