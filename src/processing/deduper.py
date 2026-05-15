from __future__ import annotations

import hashlib

from processing.utils import normalize_text_for_hash


def build_event_hash(
    *,
    source: str,
    symbol: str | None,
    title: str | None,
    event_date: str | None,
    attachment_url: str | None = None,
    external_id: str | None = None,
) -> str:
    base = "|".join(
        [
            source or "",
            symbol or "",
            normalize_text_for_hash(title),
            event_date or "",
            attachment_url or "",
            external_id or "",
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()