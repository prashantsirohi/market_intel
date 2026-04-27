from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_intel.storage import Database


class EntityResolver:
    def __init__(self, tracked_entities: list[dict]):
        self.symbol_map: dict[str, dict] = {}
        self.alias_map: dict[str, str] = {}

        for entity in tracked_entities:
            symbol = (entity.get("symbol") or "").upper()
            if not symbol:
                continue
            self.symbol_map[symbol] = entity

            aliases = entity.get("aliases_json") or "[]"
            try:
                alias_items = json.loads(aliases) if isinstance(aliases, str) else aliases
            except Exception:
                alias_items = []

            for alias in alias_items or []:
                self.alias_map[str(alias).lower()] = symbol

            company_name = entity.get("company_name")
            if company_name:
                self.alias_map[str(company_name).lower()] = symbol

    def resolve(self, symbol: str | None, title: str | None) -> str | None:
        if symbol:
            canonical = symbol.upper()
            if canonical in self.symbol_map:
                return canonical

        title_lower = (title or "").lower()
        for alias, sym in self.alias_map.items():
            if alias and alias in title_lower:
                return sym
        return None


def resolve_entity_id(db: Database, symbol: str | None) -> int | None:
    from market_intel.storage import TrackedEntityRepository

    if not symbol:
        return None

    repo = TrackedEntityRepository(db)
    entity = repo.get_by_symbol(symbol.upper())

    if entity:
        return entity.entity_id
    return None