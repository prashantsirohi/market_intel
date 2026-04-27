from __future__ import annotations


def compute_trust_score(source: str, source_type: str) -> float:
    src = (source or "").lower()
    kind = (source_type or "").lower()

    if src in {"nse", "bse"}:
        return 95.0
    if kind == "official_company":
        return 85.0
    if kind == "news":
        return 70.0
    if kind == "aggregator":
        return 50.0
    if kind == "social":
        return 25.0
    return 40.0


def is_official_source(source: str, source_type: str, source_event_type: str | None = None) -> bool:
    src = (source or "").lower()
    kind = (source_type or "").lower()
    evt = (source_event_type or "").lower()
    return src in {"nse", "bse"} or kind in {"official_company", "official_exchange", "official"} or evt == "rss_official"