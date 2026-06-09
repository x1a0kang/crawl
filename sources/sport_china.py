"""First Track (``sport-china.cn``) public listing source.

The historical listing lives behind a small JSON endpoint:

    https://api.sport-china.cn/officialApi/getRaces?page=N

Each page returns an array of race objects; the connector walks
``page=1..context.max_pages``, builds a detail URL of the form
``https://app.sport-china.cn/race/#/offline/detail/{raceId}`` and stops when
the page is empty, repeats a previous page (server-side deduped) or returns
only races whose dates are already earlier than ``context.date_from``.
"""

from __future__ import annotations

import json
from typing import Iterable, List, Optional, Sequence, Set
from urllib.error import URLError
from urllib.request import Request, urlopen

from crawl.models import DiscoverContext, Lead, SourceConnector
from crawl.net import DEFAULT_USER_AGENT
from crawl.normalize.dates import extract_date
from crawl.normalize.filters import is_mvp_race
from crawl.sources.common import make_lead


API_URL = "https://api.sport-china.cn/officialApi/getRaces"
DETAIL_URL = "https://app.sport-china.cn/race/#/offline/detail/{race_id}"


class SportChinaSource(SourceConnector):
    name = "sport-china"

    def __init__(
        self,
        json_by_page: Optional[Sequence[object]] = None,
    ) -> None:
        # ``json_by_page`` is the fixture-friendly hook used by the test
        # suite: pass a list where each element is either a parsed JSON
        # payload (dict) or the raw text of an API response.
        self.json_by_page = json_by_page

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        context = context or DiscoverContext()
        max_pages = max(1, int(context.max_pages or 1))
        if self.json_by_page is not None:
            yield from self._iter_pages(self.json_by_page, context, max_pages)
            return
        yield from self._iter_live(context, max_pages)

    # ---------------------------------------------------------------- live

    def _iter_live(self, context: DiscoverContext, max_pages: int) -> Iterable[Lead]:
        for page in range(1, max_pages + 1):
            try:
                payload = self._fetch_page(page)
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                context.warn(f"sport-china: page {page} fetch failed: {exc}")
                return
            if not payload:
                return
            yield from self._harvest_page(payload, page, context)

    @staticmethod
    def _fetch_page(page: int) -> object:
        url = f"{API_URL}?page={page}"
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
        if not body:
            return None
        return json.loads(body)

    # ----------------------------------------------------------- shared

    def _iter_pages(
        self,
        payloads: Sequence[object],
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
        seen_ids: Set[str] = set()
        for page, payload in enumerate(payloads, start=1):
            if page > max_pages:
                break
            if not payload:
                break
            if isinstance(payload, (str, bytes)):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    break
            if not payload:
                break
            harvested = list(self._harvest_page(payload, page, context))
            if not harvested:
                break
            for lead in harvested:
                race_id = lead.source_url.rsplit("/", 1)[-1]
                if race_id in seen_ids:
                    continue
                seen_ids.add(race_id)
                yield lead

    @staticmethod
    def _extract_race_list(payload: object) -> List[dict]:
        """Return the list of race dicts regardless of wrapper shape."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "dataList", "list", "rows", "records"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            # Some endpoints nest the list one more level deep.
            for key, value in payload.items():
                if isinstance(value, dict):
                    nested = value.get("list") or value.get("data")
                    if isinstance(nested, list):
                        return [item for item in nested if isinstance(item, dict)]
        return []

    def _harvest_page(
        self,
        payload: object,
        page: int,
        context: DiscoverContext,
    ) -> Iterable[Lead]:
        rows = self._extract_race_list(payload)
        for row in rows:
            lead = self._row_to_lead(row, page)
            if not lead:
                continue
            if not self._lead_in_window(lead, context):
                if context.date_from and lead.event_date and lead.event_date < context.date_from:
                    return  # rows are date-sorted ascending; stop paging
                continue
            yield lead

    @staticmethod
    def _row_to_lead(row: dict, page: int) -> Optional[Lead]:
        race_id = str(row.get("raceId") or row.get("id") or "").strip()
        name = (row.get("raceName") or row.get("name") or "").strip()
        if not name:
            return None
        start_time = (row.get("startTime") or row.get("raceTime") or "").strip()
        event_date = extract_date(start_time) or extract_date(name)
        province = (row.get("province") or row.get("provinceName") or "").strip()
        city = (row.get("city") or row.get("cityName") or "").strip()
        area = (row.get("area") or row.get("district") or "").strip()
        raw_text_parts = [name, start_time, province, city, area]
        if race_id:
            detail_url = DETAIL_URL.format(race_id=race_id)
        else:
            detail_url = f"https://app.sport-china.cn/race/#/offline/list?page={page}"
        lead = make_lead(
            source_name=SportChinaSource.name,
            source_url=detail_url,
            raw_title=name,
            event_name=name,
            event_date=event_date,
            province=province,
            city=city or area,
            event_items="",  # let make_lead infer from title/text
            raw_text=" ".join(part for part in raw_text_parts if part),
        )
        if not is_mvp_race(lead.event_name, lead.event_items):
            return None
        return lead

    @staticmethod
    def _lead_in_window(lead: Lead, context: DiscoverContext) -> bool:
        if not context.date_from and not context.date_to:
            return True
        if not lead.event_date:
            return True
        if context.date_from and lead.event_date < context.date_from:
            return False
        if context.date_to and lead.event_date > context.date_to:
            return False
        return True
