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

EVENT_FIELDS = [
    "name",
    "province",
    "city",
    "district",
    "event_date",
    "item_types",
    "start_time",
    "registration_start_at",
    "registration_end_at",
    "lottery_result_date",
    "registration_status",
    "race_status",
    "level_label",
    "certification_label",
    "organizer",
    "start_point",
    "finish_point",
    "packet_pickup_location",
    "address_text",
    "official_site_url",
    "description",
    "status",
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


def pg_array_literal(values: Iterable[str]) -> str:
    items = []
    for value in values:
        text = str(value or "").strip()
        if text:
            items.append(text.replace('"', '\\"'))
    return "{" + ",".join(items) + "}"


@dataclass(frozen=True)
class EventCandidate:
    candidate_id: str
    lead_id: str
    name: str
    province: str
    city: str
    district: str
    event_date: str
    item_types: List[str]
    start_time: str = ""
    registration_start_at: str = ""
    registration_end_at: str = ""
    lottery_result_date: str = ""
    registration_status: str = "not_started"
    race_status: str = "upcoming"
    level_label: str = ""
    certification_label: str = ""
    organizer: str = ""
    start_point: str = ""
    finish_point: str = ""
    packet_pickup_location: str = ""
    address_text: str = ""
    official_site_url: str = ""
    description: str = ""
    status: str = "draft"

    def to_row(self) -> Dict[str, str]:
        row = {field: str(asdict(self).get(field, "")) for field in EVENT_FIELDS}
        row["item_types"] = pg_array_literal(self.item_types)
        return row


@dataclass(frozen=True)
class Evidence:
    candidate_id: str
    field_name: str
    field_value: str
    source_type: str
    source_url: str
    extracted_at: str
    confidence: str
    source_title: str = ""
    extracted_text: str = ""

    def to_row(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ExtractResult:
    candidates: List[EventCandidate]
    evidence: List[Evidence]


class SourceConnector:
    name = "source"

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        raise NotImplementedError
