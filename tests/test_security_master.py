from datetime import date, datetime, timezone

import pytest

from collectors.base import CollectorItem
from collectors.security_master import (
    ListingDataset,
    ListedSecurityRecord,
    parse_bse_active_equity,
    parse_nse_equity_csv,
)
from jobs.run_high_value_v1 import _enrich_listing_identity, main as high_value_main
from storage.security_master_repository import SecurityMasterRepository


def _record(exchange: str, security_id: str, symbol: str, isin: str) -> ListedSecurityRecord:
    return ListedSecurityRecord(
        exchange=exchange,
        exchange_security_id=security_id,
        symbol=symbol,
        isin=isin,
        company_name="Example Limited",
        series="EQ" if exchange == "NSE" else "A",
        board="MAIN",
        listing_date=date(2020, 1, 1) if exchange == "NSE" else None,
        active_flag=True,
        instrument_type="CORPORATE_EQUITY",
        identity_status="VALID_ISIN",
        source_row_hash=f"hash-{exchange}",
    )


def _persist(repo, exchange: str, record: ListedSecurityRecord):
    now = datetime.now(timezone.utc)
    return repo.persist_dataset(
        sync_run_id=f"run-{exchange}",
        dataset=ListingDataset(
            exchange=exchange,
            source_url=f"https://example.test/{exchange}",
            source_hash=f"source-{exchange}",
            effective_date=date(2026, 8, 21),
            records=(record,),
        ),
        started_at=now,
        completed_at=now,
    )


def test_parse_official_nse_and_bse_identity_contracts():
    nse = parse_nse_equity_csv(
        b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\nABC,Example Limited,EQ,01-Jan-2020,INE000A01001\n"
    )
    bse = parse_bse_active_equity([{
        "SCRIP_CD": 500001,
        "scrip_id": "ABC",
        "Scrip_Name": "Example Limited",
        "ISIN_NUMBER": "INE000A01001",
        "GROUP": "A",
        "Status": "Active",
    }])

    assert nse[0].exchange_security_id == "ABC:EQ"
    assert nse[0].identity_status == "VALID_ISIN"
    assert bse[0].exchange_security_id == "500001"
    assert bse[0].instrument_type == "CORPORATE_EQUITY"


def test_repository_builds_exact_dual_listing_membership(in_memory_db):
    repo = SecurityMasterRepository(in_memory_db)
    _persist(repo, "NSE", _record("NSE", "ABC:EQ", "ABC", "INE000A01001"))
    _persist(repo, "BSE", _record("BSE", "500001", "ABC", "INE000A01001"))

    report = repo.report()
    resolved = repo.resolve_current(exchange="BSE", exchange_security_id="500001")

    assert report["membership_counts"] == {"DUAL": 1}
    assert report["ambiguous_identity_count"] == 0
    assert resolved is not None
    assert resolved["isin"] == "INE000A01001"
    assert resolved["nse_symbol"] == "ABC"
    assert resolved["listing_membership"] == "DUAL"


def test_bse_announcement_is_enriched_with_canonical_identity(in_memory_db):
    repo = SecurityMasterRepository(in_memory_db)
    _persist(repo, "NSE", _record("NSE", "ABC:EQ", "ABC", "INE000A01001"))
    _persist(repo, "BSE", _record("BSE", "500001", "ABCBSE", "INE000A01001"))
    item = CollectorItem(
        source="bse_corp", source_type="api", external_id="news-1",
        symbol="500001", title="Capacity expansion", raw_payload={"SCRIP_CD": 500001},
    )

    enriched = _enrich_listing_identity([item], exchange="BSE", repository=repo)[0]

    assert enriched.symbol == "ABC"
    assert enriched.isin == "INE000A01001"
    assert enriched.raw_payload["_listing_master"]["listing_membership"] == "DUAL"
    assert enriched.raw_payload["_listing_master"]["exchange_security_id"] == "500001"


def test_latest_completed_run_is_current_per_exchange(in_memory_db):
    repo = SecurityMasterRepository(in_memory_db)
    first = _record("NSE", "OLD:EQ", "OLD", "INE000A01001")
    second = _record("NSE", "NEW:EQ", "NEW", "INE000B01009")
    now = datetime.now(timezone.utc)
    repo.persist_dataset(
        sync_run_id="older", dataset=ListingDataset(
            exchange="NSE", source_url="https://example.test/old", source_hash="old",
            effective_date=date(2026, 8, 20), records=(first,),
        ), started_at=now, completed_at=now,
    )
    repo.persist_dataset(
        sync_run_id="newer", dataset=ListingDataset(
            exchange="NSE", source_url="https://example.test/new", source_hash="new",
            effective_date=date(2026, 8, 21), records=(second,),
        ), started_at=now, completed_at=now,
    )

    assert repo.resolve_current(exchange="NSE", symbol="OLD") is None
    assert repo.resolve_current(exchange="NSE", symbol="NEW") is not None


def test_high_value_collection_requires_completed_exchange_master(tmp_path):
    with pytest.raises(SystemExit, match="completed security-master snapshot required"):
        high_value_main([
            "collect", "--db-path", str(tmp_path / "market-intel.duckdb"),
            "--from-date", "2026-08-21", "--to-date", "2026-08-21",
            "--sources", "nse_api",
        ])
