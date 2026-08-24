import json
from pathlib import Path

import pytest

from processing.high_value_calibration import calibrate_cases


def test_v1_baseline_has_no_known_misses():
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "configs/high_value_filter_baseline_v1.json").read_text())
    result = calibrate_cases(payload["cases"])
    assert result["case_count"] == 12
    assert result["false_negative"] == 0
    assert result["recall"] == 1.0
    assert result["precision"] == 1.0
    assert result["attachment_reduction"] >= 0.5
    assert result["calibration_status"] == "COMPLETE"
    assert result["label_coverage"] == 1.0


def test_unlabeled_cases_require_review_by_default():
    cases = [{"case_id": "one", "subject": "Expansion", "expected": None}]

    with pytest.raises(ValueError, match="1 of 1 calibration cases are unlabeled"):
        calibrate_cases(cases)


def test_partial_calibration_uses_only_reviewed_cases():
    cases = [
        {"case_id": "labeled", "subject": "New manufacturing plant", "expected": "HIGH_VALUE"},
        {"case_id": "pending", "subject": "Board meeting", "expected": None},
    ]

    result = calibrate_cases(cases, allow_partial=True)

    assert result["case_count"] == 1
    assert result["total_case_count"] == 2
    assert result["labeled_case_count"] == 1
    assert result["unlabeled_case_count"] == 1
    assert result["label_coverage"] == 0.5
    assert result["calibration_status"] == "PARTIAL"
    assert result["unlabeled_case_id_sample"] == ["pending"]


def test_partial_calibration_still_requires_one_label():
    cases = [{"case_id": "pending", "expected": None}]

    with pytest.raises(ValueError, match="no labeled calibration cases"):
        calibrate_cases(cases, allow_partial=True)
