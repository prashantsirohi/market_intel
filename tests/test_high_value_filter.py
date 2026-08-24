from processing.high_value_filter import (
    DROP_METADATA_ONLY,
    FETCH_ATTACHMENT,
    KEEP,
    POLICY_HASH,
    POLICY_VERSION,
    route_announcement,
)


def test_keeps_capex_and_successful_bidder_metadata():
    capex = route_announcement(
        subject="Outcome of Board Meeting",
        details="Board approved capex of INR 600 crore for a new manufacturing facility.",
        attachment_url="https://example.test/capex.pdf",
    )
    bidder = route_announcement(
        subject="General Updates",
        details="The company was declared successful bidder under TBCB.",
        attachment_url="https://example.test/loi.pdf",
    )
    assert capex.decision == KEEP
    assert set(capex.matched_signals) >= {"CAPEX", "NEW_FACILITY"}
    assert bidder.decision == KEEP
    assert "ORDER_AWARD" in bidder.matched_signals


def test_routine_subject_rejects_override_incidental_words():
    result = route_announcement(
        subject="Allotment of Securities",
        details="Allotment under employee stock option plan for employees at the new plant.",
        attachment_url="https://example.test/allotment.pdf",
    )
    assert result.decision == DROP_METADATA_ONLY
    assert result.reason_codes == ("ROUTINE_ALLOTMENT",)


def test_generic_subject_fetches_attachment_without_claiming_keep():
    result = route_announcement(
        subject="General Updates",
        details="The company has informed the exchange about General Updates",
        attachment_url="https://example.test/APOLLO_update_on_Acquisition.pdf",
    )
    assert result.decision == FETCH_ATTACHMENT
    assert "CORPORATE_TRANSACTION" in result.matched_signals


def test_generic_subject_without_attachment_is_metadata_only():
    result = route_announcement(subject="General Updates", details="General Updates")
    assert result.decision == DROP_METADATA_ONLY
    assert result.reason_codes == ("NO_HIGH_VALUE_SIGNAL",)


def test_generic_subject_with_esos_filename_is_suppressed():
    result = route_announcement(
        subject="General Updates", details="General Updates",
        attachment_url="https://example.test/ApprovalofESOS2026.pdf",
    )
    assert result.decision == DROP_METADATA_ONLY
    assert result.reason_codes == ("ROUTINE_EMPLOYEE_EQUITY_FILENAME",)


def test_policy_identity_is_frozen():
    assert POLICY_VERSION == "market-intel-high-value-filter-v1"
    assert len(POLICY_HASH) == 64
