"""Calibration metrics for reviewed high-value-filter labels."""

from __future__ import annotations

from typing import Any

from processing.high_value_filter import route_announcement


_EXPECTED_LABELS = {"HIGH_VALUE", "NOT_HIGH_VALUE"}


def calibrate_cases(
    cases: list[dict[str, Any]], *, allow_partial: bool = False,
) -> dict[str, Any]:
    if not cases:
        raise ValueError("calibration cases must not be empty")
    unlabeled: list[tuple[int, dict[str, Any]]] = []
    labeled: list[tuple[int, dict[str, Any]]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be a JSON object")
        expected = case.get("expected")
        if expected is None or expected == "":
            unlabeled.append((index, case))
        elif expected not in _EXPECTED_LABELS:
            case_id = case.get("case_id") or index
            raise ValueError(
                f"case {case_id} expected must be HIGH_VALUE or NOT_HIGH_VALUE"
            )
        else:
            labeled.append((index, case))

    if unlabeled and not allow_partial:
        sample = [str(case.get("case_id") or index) for index, case in unlabeled[:5]]
        raise ValueError(
            f"{len(unlabeled)} of {len(cases)} calibration cases are unlabeled "
            "(expected is null); label every case as HIGH_VALUE or NOT_HIGH_VALUE, "
            "or use --allow-partial after labeling at least one case. "
            f"First unlabeled case IDs: {', '.join(sample)}"
        )
    if not labeled:
        raise ValueError(
            "no labeled calibration cases; set expected to HIGH_VALUE or "
            "NOT_HIGH_VALUE for at least one case"
        )

    tp = fp = fn = tn = 0
    misses: list[str] = []
    rows = []
    for index, case in labeled:
        expected = case.get("expected")
        result = route_announcement(
            subject=case.get("subject"), details=case.get("details"),
            attachment_url=case.get("attachment_url"),
        )
        predicted = result.attachment_eligible
        actual = expected == "HIGH_VALUE"
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
            misses.append(str(case.get("case_id") or index))
        else:
            tn += 1
        rows.append({
            "case_id": case.get("case_id") or str(index), "expected": expected,
            "decision": result.decision, "reason_codes": list(result.reason_codes),
            "matched_signals": list(result.matched_signals),
        })
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    attachment_reduction = (tn + fn) / len(labeled)
    return {
        "case_count": len(labeled),
        "total_case_count": len(cases),
        "labeled_case_count": len(labeled),
        "unlabeled_case_count": len(unlabeled),
        "label_coverage": len(labeled) / len(cases),
        "calibration_status": "PARTIAL" if unlabeled else "COMPLETE",
        "true_positive": tp, "false_positive": fp,
        "false_negative": fn, "true_negative": tn, "recall": recall,
        "precision": precision, "attachment_reduction": attachment_reduction,
        "missed_case_ids": misses,
        "unlabeled_case_id_sample": [
            str(case.get("case_id") or index) for index, case in unlabeled[:20]
        ],
        "cases": rows,
    }
