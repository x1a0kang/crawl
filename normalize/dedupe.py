from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from crawl.models import Candidate, Evidence


def dedupe_candidates(candidates: Iterable[Candidate]) -> List[Candidate]:
    by_key: Dict[str, Candidate] = {}
    for candidate in candidates:
        key = "|".join([candidate.normalized_name, candidate.event_date, candidate.city])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = candidate
            continue
        if float(candidate.confidence_score or 0) > float(existing.confidence_score or 0):
            by_key[key] = candidate
    return list(by_key.values())

