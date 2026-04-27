from __future__ import annotations

import hashlib
import re


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    value = text.lower()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^\w\s]", "", value)
    return value.strip()


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
            normalize_text(title),
            event_date or "",
            attachment_url or "",
            external_id or "",
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()