"""Credit-rating change collector (CRISIL / ICRA / CARE / India Ratings).

Each agency publishes rating actions on its own site with a different layout.
Rather than try to scrape five distinct HTML structures, this module defines:

  - ``RatingAgencyAdapter`` — a pluggable interface (one per agency)
  - ``CreditRatingCollector`` — orchestrator that runs every registered adapter

Two adapters ship today:

  - ``CrisilAdapter``  — fetches rating-rationales index page; extracts
    headlines and PDF links via heuristic parsing
  - ``IcraAdapter``    — same, against ICRA's rationale list

CARE and India Ratings are stubbed (``CareAdapterStub``, ``IndiaRatingsAdapterStub``)
with the contract in place; a follow-up commit can flesh out the parsers.
This keeps the orchestrator producible today and avoids shipping flaky parsers.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator

from collectors.base import BaseCollector, CollectorItem
from collectors.http_utils import (
    CollectorHttpError,
    ThrottledHttpClient,
    fetch_with_retries,
)

logger = logging.getLogger(__name__)


@dataclass
class RatingAction:
    """Normalized rating-action row produced by an adapter."""

    agency: str
    company_name: str
    instrument: str | None
    old_rating: str | None
    new_rating: str | None
    action: str | None  # 'upgrade' | 'downgrade' | 'reaffirm' | 'withdraw' | 'assign'
    dated: datetime | None
    source_url: str | None
    raw_text: str

    def to_collector_item(self, *, symbol_lookup: dict[str, str] | None = None) -> CollectorItem:
        symbol = None
        if symbol_lookup:
            # Best-effort match by company name → symbol
            symbol = symbol_lookup.get(_normalize_company(self.company_name))
        title = f"{self.agency} rating {self.action or 'action'}: {self.company_name}"
        if self.old_rating and self.new_rating:
            title += f" ({self.old_rating} → {self.new_rating})"
        elif self.new_rating:
            title += f" ({self.new_rating})"
        return CollectorItem(
            source=f"rating_{self.agency.lower()}",
            source_type="scrape",
            external_id=None,
            symbol=symbol,
            title=title,
            description=self.raw_text[:1500] if self.raw_text else None,
            event_date=self.dated,
            published_at=self.dated,
            link=self.source_url,
            company_name=self.company_name,
            raw_payload={
                "agency": self.agency,
                "instrument": self.instrument,
                "old_rating": self.old_rating,
                "new_rating": self.new_rating,
                "action": self.action,
            },
        )


def _normalize_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def classify_action(old: str | None, new: str | None, hint: str | None = None) -> str | None:
    """Heuristic for upgrade/downgrade/reaffirm based on rating strings.

    Indian rating agencies use letter grades like "AAA", "AA+", "AA", "AA-",
    "A+" ... "D". We map by lexicographic position; "+" outranks plain;
    "-" undershoots.
    """
    if hint:
        h = hint.lower()
        if "upgrade" in h:
            return "upgrade"
        if "downgrade" in h:
            return "downgrade"
        if "reaffirm" in h:
            return "reaffirm"
        if "withdraw" in h:
            return "withdraw"
        if "assign" in h:
            return "assign"
    if old and new and old != new:
        if _rating_score(new) > _rating_score(old):
            return "upgrade"
        if _rating_score(new) < _rating_score(old):
            return "downgrade"
        return "reaffirm"
    if old and new and old == new:
        return "reaffirm"
    return None


_RATING_ORDER = [
    "AAA", "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "C+", "C", "C-",
    "D",
]


def _rating_score(value: str | None) -> int:
    if not value:
        return -1
    upper = value.upper().strip()
    # Strip CRISIL/ICRA prefixes like "CRISIL AA+" or "[ICRA]AA+".
    # Brackets first, then the agency prefix, otherwise "[ICRA]A+" never
    # matches the prefix regex (it starts with '[').
    upper = upper.replace("[", "").replace("]", "").strip()
    upper = re.sub(r"^(CRISIL|ICRA|CARE|INDIA)\s*", "", upper)
    # Match the longest rating label that appears as a *whole token* — sorting
    # by descending length means "AA-" wins over "AA" wins over "A".
    sorted_labels = sorted(_RATING_ORDER, key=len, reverse=True)
    for label in sorted_labels:
        # Token-bounded match: rating must end the input or be followed by
        # whitespace, end-of-string, or an outlook qualifier "(stable)" etc.
        pattern = re.escape(label)
        if re.match(rf"^{pattern}(?:\s|$|\(|/|,)", upper) or upper == label:
            return len(_RATING_ORDER) - _RATING_ORDER.index(label)
    return -1


# ---------------------------------------------------------------------------- adapters


class RatingAgencyAdapter(ABC):
    agency: str = ""

    def __init__(self, http: ThrottledHttpClient | None = None):
        self.http = http or ThrottledHttpClient()

    @abstractmethod
    def fetch_actions(self) -> Iterable[RatingAction]:
        ...


_CRISIL_INDEX_URL = (
    "https://www.crisilratings.com/en/home/our-business/ratings/rating-rationales.html"
)


class CrisilAdapter(RatingAgencyAdapter):
    agency = "CRISIL"

    def fetch_actions(self) -> Iterable[RatingAction]:
        def _do(attempt: int) -> str:
            response = self.http.get_or_raise(_CRISIL_INDEX_URL)
            return response.text

        try:
            html = fetch_with_retries(_do, label="crisil_rationales")
        except CollectorHttpError as exc:
            logger.warning("CRISIL fetch failed: %s", exc)
            return []
        return list(_parse_crisil_html(html))


_ICRA_INDEX_URL = "https://www.icra.in/Rationale/Index"


class IcraAdapter(RatingAgencyAdapter):
    agency = "ICRA"

    def fetch_actions(self) -> Iterable[RatingAction]:
        def _do(attempt: int) -> str:
            response = self.http.get_or_raise(_ICRA_INDEX_URL)
            return response.text

        try:
            html = fetch_with_retries(_do, label="icra_rationales")
        except CollectorHttpError as exc:
            logger.warning("ICRA fetch failed: %s", exc)
            return []
        return list(_parse_icra_html(html))


class CareAdapterStub(RatingAgencyAdapter):
    """Stub for CARE Ratings. Wire up parser in a follow-up commit."""
    agency = "CARE"

    def fetch_actions(self) -> Iterable[RatingAction]:
        logger.debug("CareAdapterStub.fetch_actions: not yet implemented")
        return []


class IndiaRatingsAdapterStub(RatingAgencyAdapter):
    """Stub for India Ratings. Wire up parser in a follow-up commit."""
    agency = "INDIA"

    def fetch_actions(self) -> Iterable[RatingAction]:
        logger.debug("IndiaRatingsAdapterStub.fetch_actions: not yet implemented")
        return []


# ---------------------------------------------------------------------------- HTML parsers
# Heuristic regex parsers — agency sites change, so we don't depend on a heavy
# DOM library. Each parser matches the *headline* of a rating action; full
# rationale PDFs are linked but not downloaded here (the existing pdf_fetcher
# pipeline can pick them up later).

_HEADLINE_RE = re.compile(
    r"""
    (?P<company>[A-Z][A-Za-z0-9 &.,'\-]{2,120}?)
    \s*(?:[-–:]\s*)?
    (?:rating(?:\s+is)?\s+)?
    (?P<action>upgraded|downgraded|reaffirmed|withdrawn|assigned)
    [^A-Za-z0-9]+(?:to|at|from)\s*
    (?P<rating>[A-D][A-D+\-]{0,4}(?:\s*\(stable|negative|positive\))?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DATE_RE = re.compile(r"(\d{1,2}[-/\s][A-Za-z]{3,9}[-/\s]\d{4})")


def _parse_date_blob(text: str) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace("/", "-").replace("  ", " ")
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_crisil_html(html: str) -> Iterator[RatingAction]:
    return _parse_generic_html(html, agency="CRISIL")


def _parse_icra_html(html: str) -> Iterator[RatingAction]:
    return _parse_generic_html(html, agency="ICRA")


def _parse_generic_html(html: str, *, agency: str) -> Iterator[RatingAction]:
    if not html:
        return iter(())
    # Strip tags lightly to make regex matching tractable.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    actions: list[RatingAction] = []
    for match in _HEADLINE_RE.finditer(text):
        company = match.group("company").strip()
        action_word = match.group("action").lower()
        new_rating = match.group("rating").strip()
        action_normalized = {
            "upgraded": "upgrade",
            "downgraded": "downgrade",
            "reaffirmed": "reaffirm",
            "withdrawn": "withdraw",
            "assigned": "assign",
        }.get(action_word, action_word)
        # Look for an explicit "from <old> to <new>" within ±200 chars
        window_start = max(match.start() - 200, 0)
        window = text[window_start: match.end() + 200]
        from_match = re.search(
            r"from\s+([A-D][A-D+\-]{0,4})\s+to\s+([A-D][A-D+\-]{0,4})",
            window, re.IGNORECASE,
        )
        old_rating = from_match.group(1) if from_match else None
        if from_match and not new_rating:
            new_rating = from_match.group(2)
        actions.append(
            RatingAction(
                agency=agency,
                company_name=company,
                instrument=None,
                old_rating=old_rating,
                new_rating=new_rating,
                action=classify_action(old_rating, new_rating, hint=action_word),
                dated=_parse_date_blob(window),
                source_url=None,
                raw_text=window.strip(),
            )
        )
    return iter(actions)


# ---------------------------------------------------------------------------- collector


class CreditRatingCollector(BaseCollector):
    """Aggregates rating actions across all configured agency adapters."""

    source_name = "credit_rating"
    source_type = "scrape"

    def __init__(
        self,
        *,
        adapters: list[RatingAgencyAdapter] | None = None,
        symbol_lookup: dict[str, str] | None = None,
    ):
        self.adapters = adapters or [
            CrisilAdapter(),
            IcraAdapter(),
            CareAdapterStub(),
            IndiaRatingsAdapterStub(),
        ]
        self.symbol_lookup = symbol_lookup or {}

    def fetch_all(self) -> Iterable[CollectorItem]:
        items: list[CollectorItem] = []
        for adapter in self.adapters:
            try:
                actions = list(adapter.fetch_actions())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("%s adapter failed: %s", adapter.agency, exc)
                continue
            logger.info("Adapter %s produced %d actions", adapter.agency, len(actions))
            for action in actions:
                items.append(action.to_collector_item(symbol_lookup=self.symbol_lookup))
        return items
