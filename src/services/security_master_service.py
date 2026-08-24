"""Versioned official exchange-listing synchronization."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from collectors.security_master import (
    BSE_ACTIVE_EQUITY_URL,
    NSE_EQUITY_URL,
    OfficialSecurityMasterCollector,
)
from storage.security_master_repository import SecurityMasterRepository


class SecurityMasterSyncService:
    def __init__(self, db, *, collector: OfficialSecurityMasterCollector | None = None):
        self.repo = SecurityMasterRepository(db)
        self.collector = collector or OfficialSecurityMasterCollector()

    def sync(self, exchange: str, *, effective_date: date) -> dict:
        normalized = exchange.upper()
        started = datetime.now(UTC)
        material = f"{normalized}|{effective_date}|{started.isoformat()}|market-intel-security-master-v1"
        run_id = f"security-master-v1-{hashlib.sha256(material.encode()).hexdigest()[:20]}"
        try:
            dataset = self.collector.fetch(normalized, effective_date=effective_date)
            return self.repo.persist_dataset(
                sync_run_id=run_id, dataset=dataset,
                started_at=started, completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            source_url = NSE_EQUITY_URL if normalized == "NSE" else BSE_ACTIVE_EQUITY_URL
            return self.repo.persist_failure(
                sync_run_id=run_id, exchange=normalized,
                effective_date=effective_date, started_at=started,
                completed_at=datetime.now(UTC), source_url=source_url, error=exc,
            )
