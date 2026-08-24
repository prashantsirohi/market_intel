from datetime import datetime, timezone

from processing.high_value_filter import POLICY_HASH, POLICY_VERSION, route_announcement
from storage.high_value_repository import HighValueShadowRepository


def test_persists_coverage_receipt_and_filter_decision(in_memory_db):
    repo = HighValueShadowRepository(in_memory_db)
    now = datetime.now(timezone.utc)
    repo.start_run(
        collection_run_id="run-1", source="nse_api", requested_from=now,
        requested_to=now, started_at=now, policy_version=POLICY_VERSION,
        policy_hash=POLICY_HASH,
    )
    decision = route_announcement(
        subject="General Updates", details="Declared successful bidder",
        attachment_url="https://example.test/loi.pdf",
    )
    repo.record_decision(
        collection_run_id="run-1", announcement_key="nse:123", raw_event_id=None,
        source="nse_api", external_id="123", symbol="POWERGRID",
        isin="INE752E01010", listing_membership="DUAL",
        exchange_security_id="POWERGRID:EQ",
        subject="General Updates", details="Declared successful bidder",
        attachment_url="https://example.test/loi.pdf", result=decision,
    )
    repo.finish_run(
        collection_run_id="run-1", completed_at=now, status="COMPLETED",
        page_count=1, pages_complete=True, item_count=1, new_count=1,
        selected_count=1, attachment_eligible_count=1,
        response_hashes=["abc"], failures=[], summary={"keep": 1},
    )

    receipt = repo.load_run("run-1")
    rows = repo.load_decisions("run-1")
    assert receipt is not None
    assert receipt["pages_complete"] is True
    assert receipt["policy_hash"] == POLICY_HASH
    assert rows[0]["decision"] == "KEEP"
    assert rows[0]["isin"] == "INE752E01010"
    assert rows[0]["listing_membership"] == "DUAL"
    assert rows[0]["exchange_security_id"] == "POWERGRID:EQ"
    assert rows[0]["matched_signals"] == ["ORDER_AWARD"]
