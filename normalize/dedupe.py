from __future__ import annotations

from typing import Dict, Iterable, List

from crawl.models import EventCandidate


def dedupe_candidates(candidates: Iterable[EventCandidate]) -> List[EventCandidate]:
    by_key: Dict[str, EventCandidate] = {}
    for candidate in candidates:
        key = "|".join([candidate.name, candidate.event_date, candidate.city])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            continue
        if _field_count(candidate) > _field_count(existing):
            by_key[key] = candidate
    return list(by_key.values())


def _field_count(candidate: EventCandidate) -> int:
    return sum(1 for value in candidate.to_row().values() if value)
