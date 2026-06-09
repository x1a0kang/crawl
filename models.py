from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional


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


def default_last_years_window(years: int = 3, today: Optional[date] = None) -> tuple[str, str]:
    """Compute an inclusive (date_from, date_to) window for the last N years.

    The window ends at the running day (`today` if provided, otherwise the
    current local date) and goes back `years` years. Returned strings follow
    the ``YYYY-MM-DD`` format so they can be compared against ``event_date``.
    """
    end = today or date.today()
    try:
        start = end.replace(year=end.year - int(years))
    except ValueError:
        # Handle Feb 29 edge case by clamping to Feb 28.
        start = end.replace(year=end.year - int(years), day=28)
    return start.isoformat(), end.isoformat()


@dataclass(frozen=True)
class DiscoverContext:
    """Per-run context passed to ``SourceConnector.discover``.

    The connector is free to read whichever fields it needs; ``date_from`` /
    ``date_to`` describe the inclusive event-date window the caller is
    interested in, and ``max_pages`` caps how many paginated requests the
    connector is allowed to issue before giving up. ``rendered_fetcher`` is
    a callable that returns rendered HTML (or raw text) for a URL, used by
    sources that need a JavaScript-capable fetcher.
    """

    date_from: str = ""
    date_to: str = ""
    max_pages: int = 120
    rendered_fetcher: Optional[Callable[[str, int], str]] = None
    warnings: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


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

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        raise NotImplementedError
