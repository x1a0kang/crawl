from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
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
    "district",
    "level_label",
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
    "level_label",
    "organizer",
    "status",
]


def now_iso() -> str:
    """Return the current UTC time in ISO format.

    Author: juruikang
    Date: 2026-06-12
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_last_years_window(years: int = 3, today: Optional[date] = None) -> tuple[str, str]:
    """Compute an inclusive (date_from, date_to) window for the last N years.

    The window ends at the running day (`today` if provided, otherwise the
    current local date) and goes back `years` years. Returned strings follow
    the ``YYYY-MM-DD`` format so they can be compared against ``event_date``.

    Author: juruikang
    Date: 2026-06-12
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
    interested in, and ``max_pages`` caps how many official API paginated
    requests the connector is allowed to issue before giving up.

    Author: juruikang
    Date: 2026-06-12
    """

    date_from: str = ""
    date_to: str = ""
    max_pages: int = 120
    warnings: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        """Collect a non-fatal pipeline warning.

        Author: juruikang
        Date: 2026-06-12
        """
        self.warnings.append(message)


@dataclass(frozen=True)
class Lead:
    """Discovered race lead persisted to leads.csv.

    Author: juruikang
    Date: 2026-06-12
    """

    lead_id: str
    source_name: str
    source_url: str
    raw_title: str
    event_name: str
    event_date: str
    province: str
    city: str
    district: str = ""
    level_label: str = ""
    event_items: str = ""
    discovered_at: str = ""
    raw_hash: str = ""

    def to_row(self) -> Dict[str, str]:
        """Convert this lead to a CSV row.

        Author: juruikang
        Date: 2026-06-12
        """
        return {field: str(asdict(self).get(field, "")) for field in LEAD_FIELDS}


def pg_array_literal(values: Iterable[str]) -> str:
    """Serialize item types for direct CSV import into Postgres.

    Author: juruikang
    Date: 2026-06-12
    """
    items = []
    for value in values:
        text = str(value or "").strip()
        if text:
            items.append(text)
    return "[" + ",".join(f'"{item.replace(chr(34), chr(92) + chr(34))}"' for item in items) + "]"


@dataclass(frozen=True)
class EventCandidate:
    """Importable event candidate aligned to the events table columns.

    Author: juruikang
    Date: 2026-06-12
    """

    candidate_id: str
    lead_id: str
    name: str
    province: str
    city: str
    district: str
    event_date: str
    item_types: List[str]
    level_label: str = ""
    organizer: str = ""
    status: str = "public"

    def to_row(self) -> Dict[str, str]:
        """Convert this event candidate to a CSV row.

        Author: juruikang
        Date: 2026-06-12
        """
        row = {field: str(asdict(self).get(field, "")) for field in EVENT_FIELDS}
        row["item_types"] = pg_array_literal(self.item_types)
        return row


@dataclass(frozen=True)
class Evidence:
    """Field-level evidence row persisted to evidence.jsonl.

    Author: juruikang
    Date: 2026-06-12
    """

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
        """Convert this evidence item to a JSONL row payload.

        Author: juruikang
        Date: 2026-06-12
        """
        return asdict(self)


@dataclass
class ExtractResult:
    """Extraction result wrapper used by callers that prefer one return object.

    Author: juruikang
    Date: 2026-06-12
    """

    candidates: List[EventCandidate]
    evidence: List[Evidence]


class SourceConnector:
    """Base source connector contract.

    Author: juruikang
    Date: 2026-06-12
    """

    name = "source"

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        """Discover leads for this source.

        Author: juruikang
        Date: 2026-06-12
        """
        raise NotImplementedError
