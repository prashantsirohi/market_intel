from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from collectors.base import CollectorItem
from jobs import run_jcurve_backfill_v1 as backfill


def _target() -> dict:
    return {
        "company_id": "company:abc", "isin": "INE001A01001",
        "nse_symbol": "ABC", "bse_code": "500001", "queue_rank": 1,
    }


def test_loads_only_resolved_primary_discovery_targets(tmp_path):
    path = tmp_path / "research.duckdb"
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE jcurve_discovery_run (run_id VARCHAR, status VARCHAR)")
    conn.execute(
        """CREATE TABLE jcurve_discovery_candidate (
           run_id VARCHAR, company_id VARCHAR, isin VARCHAR, nse_symbol VARCHAR,
           bse_code VARCHAR, queue_rank INTEGER, queue_disposition VARCHAR,
           identity_status VARCHAR)"""
    )
    conn.execute("INSERT INTO jcurve_discovery_run VALUES ('run-1', 'COMPLETED')")
    conn.execute(
        """INSERT INTO jcurve_discovery_candidate VALUES
           ('run-1', 'company:abc', 'INE001A01001', 'ABC', '500001', 1,
            'PRIMARY_RESEARCH', 'RESOLVED'),
           ('run-1', 'company:drop', 'INE001A01002', 'DROP', '500002', NULL,
            'DROP', 'RESOLVED')"""
    )
    conn.close()

    assert backfill.load_discovery_targets(path, "run-1") == [_target()]


def test_exact_target_retention_and_cross_listing_fingerprint():
    published = datetime(2026, 8, 1, tzinfo=timezone.utc)
    matching = CollectorItem(
        source="nse_api", source_type="api", external_id="1", symbol="ABC",
        isin="INE001A01001", company_name="ABC Ltd", title="Commercial production",
        published_at=published,
    )
    excluded = CollectorItem(
        source="nse_api", source_type="api", external_id="2", symbol="XYZ",
        isin="INE001A01009", company_name="XYZ Ltd", title="Commercial production",
        published_at=published,
    )

    retained = backfill._retain_targets([matching, excluded], [_target()], exchange="NSE")

    assert len(retained) == 1
    assert retained[0].raw_payload["_jcurve_backfill"]["identity_match"] == "ISIN"
    assert backfill._fingerprint(matching) == backfill._fingerprint(
        CollectorItem(
            source="bse_corp", source_type="api", external_id="3", symbol="500001",
            isin="INE001A01001", company_name="ABC Ltd",
            title="Commercial  Production!", published_at=published,
        )
    )


def test_attachment_selection_requires_jcurve_specific_signal():
    assert "CAPEX" in backfill.JCURVE_ATTACHMENT_SIGNALS
    assert "CORPORATE_TRANSACTION" not in backfill.JCURVE_ATTACHMENT_SIGNALS


def test_attachment_url_must_be_fetchable_http_url():
    assert backfill._is_http_url("https://example.com/filing.pdf")
    assert backfill._is_http_url("http://example.com/filing.pdf")
    assert not backfill._is_http_url("-")
    assert not backfill._is_http_url("/relative/filing.pdf")


def test_document_validation_checks_status_path_and_hash(tmp_path):
    path = tmp_path / "filing.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture")
    digest = backfill.hashlib.sha256(path.read_bytes()).hexdigest()

    assert backfill._document_is_valid({
        "pdf_status": "ok", "local_path": str(path), "content_hash": digest,
    })
    assert not backfill._document_is_valid({
        "pdf_status": "ok", "local_path": str(path), "content_hash": "0" * 64,
    })
    assert not backfill._document_is_valid({
        "pdf_status": "failed", "local_path": str(path), "content_hash": digest,
    })
    assert not backfill._document_is_valid({
        "pdf_status": "ok", "local_path": "data/pdfs/fixture.pdf", "content_hash": digest,
    })


def test_backfill_is_resumable_by_source_chunk(tmp_path, monkeypatch):
    results = []

    def collect(**kwargs):
        results.append((kwargs["source"], kwargs["chunk_from"], kwargs["chunk_to"]))
        return {
            "collection_run_id": f"collection-{len(results)}",
            "source": kwargs["source"], "status": "COMPLETED",
            "pages_complete": True, "item_count": 10, "target_item_count": 2,
            "new_count": 1, "selected_count": 1,
            "attachment_eligible_count": 1, "failure_count": 0,
        }

    monkeypatch.setattr(backfill, "_collect_chunk", collect)
    monkeypatch.setattr(backfill, "_require_security_master", lambda *_args: None)
    plan = {
        "discovery_run_id": "run-1", "cohort_hash": backfill._hash([_target()]),
        "requested_from": date(2026, 8, 1), "requested_to": date(2026, 8, 2),
        "chunk_days": 1,
    }
    kwargs = {
        "db_path": tmp_path / "market.duckdb", "targets": [_target()], "plan": plan,
        "chunks": backfill._chunks(date(2026, 8, 1), date(2026, 8, 2), 1),
        "sources": ("nse_api", "bse_corp"), "download_selected": False,
        "continue_on_degraded": False,
    }
    partial = backfill.run_backfill(**kwargs, max_chunks=1)
    completed = backfill.run_backfill(**kwargs, max_chunks=None)

    assert partial["status"] == "RUNNING"
    assert partial["completed_chunk_count"] == 1
    assert completed["status"] == "COMPLETED"
    assert completed["completed_chunk_count"] == 4
    assert completed["source_item_count"] == 40
    assert len(results) == 4
