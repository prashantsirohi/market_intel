"""Versioned metadata-first routing for high-value corporate announcements.

The policy deliberately decides only whether an attachment deserves further
inspection.  It does not assert that an announcement contains a verified fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse


POLICY_VERSION = "market-intel-high-value-filter-v1"

KEEP = "KEEP"
FETCH_ATTACHMENT = "FETCH_ATTACHMENT"
DROP_METADATA_ONLY = "DROP_METADATA_ONLY"


def _compile(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{pattern})" for pattern in patterns), re.IGNORECASE)


HARD_REJECT_SUBJECTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ROUTINE_SHAREHOLDER_MEETING", _compile(r"shareholders? meeting", r"annual general meeting", r"\bagm\b", r"voting results?")),
    ("ROUTINE_NEWSPAPER_PUBLICATION", _compile(r"newspaper publication", r"publication of notice")),
    ("ROUTINE_EMPLOYEE_EQUITY", _compile(r"\besop\b", r"\besos\b", r"\besps\b", r"employee stock option")),
    ("ROUTINE_TRADING_PLAN", _compile(r"trading plan under pit", r"insider trading plan")),
    ("ROUTINE_RECORD_DATE", _compile(r"^record date$")),
    ("ROUTINE_CERTIFICATE", _compile(r"loss of share certificate", r"duplicate share certificate", r"compliance certificate")),
    ("ROUTINE_ALLOTMENT", _compile(r"^allotment of securities$", r"^allotment of shares$")),
)

HARD_REJECT_FILENAMES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ROUTINE_EMPLOYEE_EQUITY_FILENAME", _compile(r"esop(?:\d|\b)", r"esos(?:\d|\b)", r"esps(?:\d|\b)", r"employee stock option")),
    ("ROUTINE_MEETING_FILENAME", _compile(r"scrutini[sz]er", r"\bagm\b", r"voting result")),
    ("ROUTINE_NEWSPAPER_FILENAME", _compile(r"newspaper", r"publication of notice")),
    ("ROUTINE_RECORD_DATE_FILENAME", _compile(r"record date")),
    ("ROUTINE_TRADING_PLAN_FILENAME", _compile(r"trading plan", r"\bpit plan\b")),
)


STRONG_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CAPEX", _compile(r"\bcapex\b", r"capital expenditure", r"project cost")),
    ("CAPACITY", _compile(r"capacity expansion", r"capacity addition", r"installed capacity", r"production capacity", r"debottleneck")),
    ("NEW_FACILITY", _compile(r"\bgreenfield\b", r"\bbrownfield\b", r"new (?:plant|factory|manufacturing facility|production line)")),
    ("COMMERCIALISATION", _compile(r"commission(?:ed|ing)", r"commercial production", r"commencement of production", r"trial production", r"commercial operations", r"mechanical completion", r"ramp[- ]?up")),
    ("PROJECT_FINANCE", _compile(r"board approved investment", r"financial closure")),
    ("DEMAND_PATH", _compile(r"offtake agreement", r"long[- ]term supply agreement")),
    ("ORDER_AWARD", _compile(r"letter of award", r"award of (?:an? )?order", r"order received", r"work order", r"purchase order", r"successful bidder", r"\bl1 bidder\b", r"bagging (?:of )?(?:an? )?order")),
    ("PROJECT_ADVERSE", _compile(r"project delay", r"project deferr", r"project cancell", r"cost overrun", r"plant shutdown")),
    ("CORPORATE_TRANSACTION", _compile(r"\bacquisition\b", r"\bdemerger\b", r"scheme of arrangement", r"joint venture", r"stake acquisition", r"\bbuyback\b")),
    ("MATERIAL_FINANCING", _compile(r"qualified institutional placement", r"\bqip\b", r"rights issue", r"preferential issue", r"financial closure")),
    ("MATERIAL_CREDIT_EVENT", _compile(r"rating downgrade", r"downgraded to", r"payment default", r"insolvency")),
)


AMBIGUOUS_SUBJECTS = _compile(
    r"^general updates?$",
    r"^updates?$",
    r"press release",
    r"outcome of board meeting",
    r"regulation 30",
    r"investor presentation",
    r"business update",
    r"operational update",
)


POLICY_SPEC = {
    "policy_version": POLICY_VERSION,
    "decisions": [KEEP, FETCH_ATTACHMENT, DROP_METADATA_ONLY],
    "hard_rejects": [name for name, _ in HARD_REJECT_SUBJECTS],
    "hard_reject_filename_signals": [name for name, _ in HARD_REJECT_FILENAMES],
    "strong_signals": [name for name, _ in STRONG_SIGNALS],
    "precedence": ["hard_reject_subject", "strong_title_or_details", "hard_reject_attachment_filename", "strong_attachment_filename", "ambiguous_subject_with_attachment", "drop_metadata_only"],
}
POLICY_HASH = hashlib.sha256(
    json.dumps(POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


@dataclass(frozen=True)
class FilterDecision:
    decision: str
    reason_codes: tuple[str, ...]
    matched_signals: tuple[str, ...]
    policy_version: str = POLICY_VERSION
    policy_hash: str = POLICY_HASH

    @property
    def attachment_eligible(self) -> bool:
        return self.decision in {KEEP, FETCH_ATTACHMENT}


def attachment_filename(attachment_url: str | None) -> str:
    if not attachment_url:
        return ""
    path = unquote(urlparse(attachment_url).path)
    return PurePosixPath(path).name.replace("_", " ").replace("-", " ")


def route_announcement(
    *,
    subject: str | None,
    details: str | None = None,
    attachment_url: str | None = None,
) -> FilterDecision:
    """Route metadata without claiming that the underlying event is verified."""

    normalized_subject = (subject or "").strip()
    body = " ".join(part for part in (normalized_subject, details or "") if part)
    filename = attachment_filename(attachment_url)

    reject_hits = tuple(name for name, pattern in HARD_REJECT_SUBJECTS if pattern.search(normalized_subject))
    if reject_hits:
        return FilterDecision(
            decision=DROP_METADATA_ONLY,
            reason_codes=reject_hits,
            matched_signals=(),
        )

    body_hits = tuple(name for name, pattern in STRONG_SIGNALS if pattern.search(body))
    if body_hits:
        return FilterDecision(
            decision=KEEP,
            reason_codes=("STRONG_METADATA_SIGNAL",),
            matched_signals=body_hits,
        )

    filename_reject_hits = tuple(
        name for name, pattern in HARD_REJECT_FILENAMES if pattern.search(filename)
    )
    if filename_reject_hits:
        return FilterDecision(
            decision=DROP_METADATA_ONLY,
            reason_codes=filename_reject_hits,
            matched_signals=(),
        )

    filename_hits = tuple(name for name, pattern in STRONG_SIGNALS if pattern.search(filename))
    if filename_hits:
        return FilterDecision(
            decision=FETCH_ATTACHMENT,
            reason_codes=("STRONG_ATTACHMENT_FILENAME_SIGNAL",),
            matched_signals=filename_hits,
        )

    if attachment_url and AMBIGUOUS_SUBJECTS.search(normalized_subject):
        return FilterDecision(
            decision=FETCH_ATTACHMENT,
            reason_codes=("AMBIGUOUS_SUBJECT_REQUIRES_ATTACHMENT",),
            matched_signals=(),
        )

    return FilterDecision(
        decision=DROP_METADATA_ONLY,
        reason_codes=("NO_HIGH_VALUE_SIGNAL",),
        matched_signals=(),
    )
