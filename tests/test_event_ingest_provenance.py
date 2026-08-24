from datetime import datetime, timezone

from services.event_analysis_service import EventAnalysisService
from services.event_ingest_service import EventIngestService
from processing.entity_resolver import EntityResolver


def test_ingest_preserves_official_source_publication_and_raw_payload(in_memory_db):
    raw_repo = in_memory_db.raw_event_repo()
    service = EventIngestService(
        raw_repo,
        EventAnalysisService(raw_repo, in_memory_db.resolved_event_repo(), EntityResolver([])),
    )
    published = datetime(2026, 8, 21, 12, 30, tzinfo=timezone.utc)
    result = service.process_rss_item({
        "source": "nse_rss", "source_type": "official", "guid": "nse-1",
        "symbol": "WELCORP", "company_name": "Welspun Corp Limited",
        "title": "Capacity expansion", "description": "New production line",
        "pub_date": published, "published_at": published,
        "attachment_url": "https://example.test/welcorp.pdf",
        "raw_payload": {"exchange_payload": True},
    })
    assert result["status"] == "new"
    with in_memory_db.get_connection(read_only=True) as conn:
        row = conn.execute(
            "SELECT source, company_name, published_at, raw_payload_json FROM raw_event WHERE raw_event_id = ?",
            [result["raw_event_id"]],
        ).fetchone()
    assert row[0] == "nse_rss"
    assert row[1] == "Welspun Corp Limited"
    assert row[2] is not None
    assert '"exchange_payload": true' in row[3]
