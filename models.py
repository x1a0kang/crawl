from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


LEAD_FIELDS = [
    "lead_id",
    "source_name",
    "source_url",
    "raw_title",
    "event_name",
    "event_date",
    "province",
    "city",
    "event_items",
    "discovered_at",
    "raw_hash",
]

CANDIDATE_FIELDS = [
    "candidate_id",
    "lead_id",
    "normalized_name",
    "event_date",
    "province",
    "city",
    "event_items",
    "registration_start_at",
    "registration_end_at",
    "fee",
    "start_point",
    "finish_point",
    "official_site_url",
    "official_registration_url",
    "route_image_url",
    "confidence_score",
    "review_status",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Lead:
    lead_id: str
    source_name: str
    source_url: str
    raw_title: str
    event_name: str
    event_date: str
    province: str
    city: str
    event_items: str
    discovered_at: str
    raw_hash: str

    def to_row(self) -> Dict[str, str]:
        return {field: str(asdict(self).get(field, "")) for field in LEAD_FIELDS}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    lead_id: str
    normalized_name: str
    event_date: str
    province: str
    city: str
    event_items: str
    registration_start_at: str = ""
    registration_end_at: str = ""
    fee: str = ""
    start_point: str = ""
    finish_point: str = ""
    official_site_url: str = ""
    official_registration_url: str = ""
    route_image_url: str = ""
    confidence_score: str = "0.50"
    review_status: str = "pending_review"

    def to_row(self) -> Dict[str, str]:
        return {field: str(asdict(self).get(field, "")) for field in CANDIDATE_FIELDS}


@dataclass(frozen=True)
class Evidence:
    candidate_id: str
    field_name: str
    field_value: str
    source_type: str
    source_url: str
    extracted_at: str
    confidence: str

    def to_row(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ExtractResult:
    candidates: List[Candidate]
    evidence: List[Evidence]


class SourceConnector:
    name = "source"

    def discover(self) -> Iterable[Lead]:
        raise NotImplementedError

