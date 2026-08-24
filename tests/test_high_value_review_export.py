import json
from datetime import datetime

import pytest

from collectors.base import CollectorItem
from processing.high_value_review_export import export_review_set
from services.high_value_shadow_service import HighValueShadowService
from storage.db import Database


def _item(external_id: str, subject: str, details: str, isin: str) -> CollectorItem:
    return CollectorItem(
        source="nse_api", source_type="api", external_id=external_id,
        symbol=external_id.upper(), isin=isin, title=subject,
        description=details, event_date=datetime(2026, 8, 21, 12, 0),
        attachment_url=f"https://example.test/{external_id}.pdf",
        raw_payload={
            "_listing_master": {
                "listing_membership": "DUAL",
                "exchange_security_id": f"{external_id.upper()}:EQ",
            }
        },
    )


def test_export_review_is_deterministic_stratified_and_cohort_aware(tmp_path):
    db_path = tmp_path / "market-intel.duckdb"
    db = Database(str(db_path))
    service = HighValueShadowService(db)
    result = service.run_source(
        source="nse_api",
        items=[
            _item("keep-1", "Project Update", "Commercial production commenced at the new plant.", "INE000A01001"),
            _item("keep-2", "Project Update", "Capacity expansion approved by the board.", "INE000B01009"),
            _item("fetch-1", "General Updates", "General corporate update.", "INE000C01007"),
            _item("fetch-2", "General Updates", "Further company information.", "INE000D01005"),
            _item("drop-1", "Shareholders meeting", "Proceedings of annual general meeting.", "INE000E01003"),
            _item("drop-2", "Record Date", "Record date for final dividend.", "INE000F01001"),
        ],
        requested_from=datetime(2026, 8, 21),
        requested_to=datetime(2026, 8, 21, 23, 59, 59),
        response_hashes=["page-1"], failures=[], page_count=1, pages_complete=True,
    )
    db.close()
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps({
        "cohort_version": "test-cohort-v1",
        "members": [{"isin": "INE000B01009"}],
    }), encoding="utf-8")
    output = tmp_path / "review.json"

    summary = export_review_set(
        db_path=db_path, output_path=output,
        collection_run_ids=[result["collection_run_id"]],
        keep_sample=1, fetch_sample=1, drop_sample=1,
        cohort_file=cohort, seed="fixed-seed",
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert summary["population_count"] == 6
    assert summary["case_count"] == 4
    assert summary["cohort_case_count"] == 1
    assert {case["predicted_decision"] for case in payload["cases"]} == {
        "KEEP", "FETCH_ATTACHMENT", "DROP_METADATA_ONLY",
    }
    assert all(case["expected"] is None for case in payload["cases"])
    cohort_case = next(case for case in payload["cases"] if case["isin"] == "INE000B01009")
    assert "COHORT_ALL" in cohort_case["sample_reasons"]
    assert len(payload["dataset_hash"]) == 64

    with pytest.raises(FileExistsError):
        export_review_set(
            db_path=db_path, output_path=output,
            collection_run_ids=[result["collection_run_id"]],
        )


def test_export_review_rejects_unknown_run(tmp_path):
    db_path = tmp_path / "market-intel.duckdb"
    Database(str(db_path)).close()
    with pytest.raises(ValueError, match="not found"):
        export_review_set(
            db_path=db_path, output_path=tmp_path / "review.json",
            collection_run_ids=["missing-run"],
        )
