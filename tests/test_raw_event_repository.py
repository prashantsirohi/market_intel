from __future__ import annotations

from datetime import datetime, timezone

from market_intel.services.collection_service import CollectionService


def test_duplicate_raw_event_returns_existing_without_update_error(in_memory_db):
    repo = in_memory_db.raw_event_repo()
    event_date = datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc)

    first = repo.upsert_event(
        source="bse_corp",
        source_type="official",
        external_id="bse-1",
        symbol="RELIANCE",
        title="Audited Financial Results",
        event_date=event_date,
        raw_payload={"id": "bse-1"},
    )
    second = repo.upsert_event(
        source="bse_corp",
        source_type="official",
        external_id="bse-1",
        symbol="RELIANCE",
        title="Audited Financial Results",
        event_date=event_date,
        raw_payload={"id": "bse-1"},
    )

    assert second.raw_event_id == first.raw_event_id
    assert second.seen_count == 2
    with in_memory_db.get_connection(read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM raw_event").fetchone()[0] == 1


def test_ingest_duplicate_rss_like_event_is_idempotent(in_memory_db):
    ingest = CollectionService(in_memory_db)._ingest_svc()
    item = {
        "source": "bse_corp",
        "source_type": "official",
        "guid": "bse-1",
        "symbol": "RELIANCE",
        "title": "Audited Financial Results",
        "description": "Audited financial results for the year ended March 2026",
        "pub_date": datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc),
        "link": "https://example.com/bse-1",
    }

    first = ingest.process_rss_item(item)
    second = ingest.process_rss_item(item)

    assert first["status"] == "new"
    assert second["status"] == "duplicate"
    with in_memory_db.get_connection(read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM raw_event").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM resolved_event").fetchone()[0] == 1
