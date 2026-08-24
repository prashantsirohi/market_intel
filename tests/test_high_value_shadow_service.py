from datetime import datetime

from collectors.base import CollectorItem
from services.high_value_shadow_service import HighValueShadowService


def test_duplicate_source_announcement_is_audited_without_degrading(in_memory_db):
    item = CollectorItem(
        source="bse_corp",
        source_type="api",
        external_id="duplicate-news-id",
        symbol="500325",
        title="General Updates",
        description="The company approved a capacity expansion project.",
        event_date=datetime(2026, 8, 21, 10, 30),
        attachment_url="https://example.test/announcement.pdf",
    )
    result = HighValueShadowService(in_memory_db).run_source(
        source="bse_corp",
        items=[item, item],
        requested_from=datetime(2026, 8, 21),
        requested_to=datetime(2026, 8, 21, 23, 59, 59),
        response_hashes=["page-1"],
        failures=[],
        page_count=1,
        pages_complete=True,
    )

    assert result["status"] == "COMPLETED"
    assert result["item_count"] == 2
    assert result["unique_item_count"] == 1
    assert result["duplicate_source_count"] == 1
    assert result["listing_identity_counts"] == {"UNRESOLVED": 1}
    assert result["failure_count"] == 0

    receipt = HighValueShadowService(in_memory_db).repo.load_run(result["collection_run_id"])
    decisions = HighValueShadowService(in_memory_db).repo.load_decisions(result["collection_run_id"])
    assert receipt is not None
    assert receipt["failure_count"] == 0
    assert len(decisions) == 1


def test_optional_pdf_failure_does_not_invalidate_metadata_coverage(in_memory_db):
    item = CollectorItem(
        source="nse_api", source_type="api", external_id="pdf-failure",
        symbol="ABC", title="Capacity expansion", description="New plant",
        event_date=datetime(2026, 8, 21, 10, 30),
        attachment_url="https://example.test/oversized.pdf",
    )
    service = HighValueShadowService(in_memory_db)

    def fail_pdf(*_args, **_kwargs):
        raise RuntimeError("oversized PDF")

    service.collection._process_pdf = fail_pdf
    result = service.run_source(
        source="nse_api", items=[item],
        requested_from=datetime(2026, 8, 21),
        requested_to=datetime(2026, 8, 21, 23, 59, 59),
        response_hashes=["page-1"], failures=[], page_count=1,
        pages_complete=True, download_selected=True,
    )

    assert result["status"] == "COMPLETED"
    assert result["failure_count"] == 0
    assert result["attachment_failure_count"] == 1
