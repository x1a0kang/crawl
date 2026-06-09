from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List

from crawl.models import Lead, SourceConnector
from crawl.sources.common import make_lead


class ManualSeedSource(SourceConnector):
    name = "manual"

    def __init__(self, path: str = "seeds.csv") -> None:
        self.path = Path(path)

    def discover(self) -> Iterable[Lead]:
        if not self.path.exists():
            return []
        leads: List[Lead] = []
        with self.path.open("r", newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                leads.append(
                    make_lead(
                        source_name=row.get("source_name") or self.name,
                        source_url=row.get("source_url", ""),
                        raw_title=row.get("raw_title") or row.get("event_name", ""),
                        event_name=row.get("event_name", ""),
                        event_date=row.get("event_date", ""),
                        province=row.get("province", ""),
                        city=row.get("city", ""),
                        event_items=row.get("event_items", ""),
                        raw_text=str(row),
                    )
                )
        return leads

