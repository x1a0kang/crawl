from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List

from crawl.models import EVENT_FIELDS, LEAD_FIELDS, EventCandidate, Evidence, Lead


def ensure_output_dir(out_dir: str) -> Path:
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_leads(path: Path, leads: Iterable[Lead]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEAD_FIELDS)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_row())


def read_leads(path: str) -> List[Lead]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        return [Lead(**row) for row in csv.DictReader(handle)]


def write_events(path: Path, candidates: Iterable[EventCandidate]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(candidate.to_row())


def write_evidence(path: Path, evidence: Iterable[Evidence]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in evidence:
            handle.write(json.dumps(item.to_row(), ensure_ascii=False) + "\n")
