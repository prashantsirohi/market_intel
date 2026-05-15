from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Database


class EntityResolver:
    def __init__(self, tracked_entities: list[dict]):
        self.symbol_map: dict[str, dict] = {}
        self.alias_map: dict[str, str] = {}
        self._alias_pattern: re.Pattern | None = None

        aliases_for_regex: list[str] = []
        
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
                aliases_for_regex.append(re.escape(str(alias).lower()))

            company_name = entity.get("company_name")
            if company_name:
                self.alias_map[str(company_name).lower()] = symbol
                aliases_for_regex.append(re.escape(company_name.lower()))

        if aliases_for_regex:
            pattern = "|".join(aliases_for_regex)
            self._alias_pattern = re.compile(pattern, re.IGNORECASE)

    def resolve(self, symbol: str | None, title: str | None) -> str | None:
        if symbol:
            canonical = symbol.upper()
            if canonical in self.symbol_map:
                return canonical

        if title and self._alias_pattern:
            match = self._alias_pattern.search(title)
            if match:
                matched = match.group(0).lower()
                return self.alias_map.get(matched)
        
        title_lower = (title or "").lower()
        if title_lower:
            for alias, sym in self.alias_map.items():
                if alias in title_lower:
                    return sym
        return None


def resolve_entity_id(db: Database, symbol: str | None) -> int | None:
    from storage import TrackedEntityRepository

    if not symbol:
        return None

    repo = TrackedEntityRepository(db)
    entity = repo.get_by_symbol(symbol.upper())

    if entity:
        return entity.entity_id
    return None