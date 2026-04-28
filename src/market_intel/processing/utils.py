from __future__ import annotations

import hashlib
import re
from typing import Optional


def normalize_text(text: str | None) -> str:
    """Normalize text for comparison - lowercase, collapse whitespace."""
    if not text:
        return ""
    value = text.lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_text_for_hash(text: str | None) -> str:
    """Normalize text for hashing - also strip punctuation."""
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
    pub_date: Optional[str] = None,
) -> str:
    """Build deterministic hash for deduplication."""
    normalized = normalize_text_for_hash(f"{source}:{symbol or ''}:{title or ''}:{pub_date or ''}")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]