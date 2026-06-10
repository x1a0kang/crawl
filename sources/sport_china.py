"""First Track (``sport-china.cn``) public listing source.

The historical listing lives behind a small JSON endpoint:

    https://api.sport-china.cn/officialApi/getRaces?page=N

Each page returns an array of race objects; the connector walks
``page=1..context.max_pages``, builds a detail URL of the form
``https://app.sport-china.cn/race/#/offline/detail/{raceId}`` and stops when
the page is empty or repeats a previous page (server-side deduped). Transient
page fetch failures are retried and then skipped so a single flaky page does
not discard later results.
"""

from __future__ import annotations

import json
import time
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
FETCH_ERRORS = (URLError, TimeoutError, OSError, ValueError)
DEFAULT_RETRY_DELAYS = (0.5, 1.5)
MAX_CONSECUTIVE_FETCH_FAILURES = 3


class SportChinaSource(SourceConnector):
    name = "sport-china"

    def __init__(
        self,
        json_by_page: Optional[Sequence[object]] = None,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        # ``json_by_page`` is the fixture-friendly hook used by the test
        # suite: pass a list where each element is either a parsed JSON
        # payload (dict) or the raw text of an API response.
        self.json_by_page = json_by_page
        self.retry_delays = tuple(retry_delays)

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        context = context or DiscoverContext()
        max_pages = max(1, int(context.max_pages or 1))
        if self.json_by_page is not None:
            yield from self._iter_pages(self.json_by_page, context, max_pages)
            return
        yield from self._iter_live(context, max_pages)

    # ---------------------------------------------------------------- live

    def _iter_live(self, context: DiscoverContext, max_pages: int) -> Iterable[Lead]:
        seen_page_ids: Set[str] = set()
        yielded_ids: Set[str] = set()
        consecutive_failures = 0
        for page in range(1, max_pages + 1):
            try:
                payload = self._fetch_page_with_retries(page)
            except FETCH_ERRORS as exc:
                consecutive_failures += 1
                context.warn(f"sport-china: page {page} fetch failed after retries: {exc}")
                if consecutive_failures >= MAX_CONSECUTIVE_FETCH_FAILURES:
                    context.warn(
                        "sport-china: stopping after "
                        f"{consecutive_failures} consecutive fetch failures"
                    )
                    return
                continue
            consecutive_failures = 0
            if not payload:
                return
            rows = self._extract_race_list(payload)
            if not rows:
                return
            row_ids = self._row_ids(rows)
            if row_ids and row_ids.issubset(seen_page_ids):
                return
            seen_page_ids.update(row_ids)
            for lead in self._harvest_rows(rows, page, context):
                race_id = lead.source_url.rsplit("/", 1)[-1]
                if race_id in yielded_ids:
                    continue
                yielded_ids.add(race_id)
                yield lead

    @staticmethod
    def _fetch_page(page: int) -> object:
        url = f"{API_URL}?page={page}"
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
        if not body:
            return None
        return json.loads(body)

    def _fetch_page_with_retries(self, page: int) -> object:
        for attempt, delay in enumerate((0, *self.retry_delays), start=1):
            if delay:
                time.sleep(delay)
            try:
                return self._fetch_page(page)
            except FETCH_ERRORS:
                if attempt > len(self.retry_delays):
                    raise
        return None

    # ----------------------------------------------------------- shared

    def _iter_pages(
        self,
        payloads: Sequence[object],
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
        seen_page_ids: Set[str] = set()
        yielded_ids: Set[str] = set()
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
            rows = self._extract_race_list(payload)
            if not rows:
                break
            row_ids = self._row_ids(rows)
            if row_ids and row_ids.issubset(seen_page_ids):
                break
            seen_page_ids.update(row_ids)
            harvested = list(self._harvest_rows(rows, page, context))
            for lead in harvested:
                race_id = lead.source_url.rsplit("/", 1)[-1]
                if race_id in yielded_ids:
                    continue
                yielded_ids.add(race_id)
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
        yield from self._harvest_rows(self._extract_race_list(payload), page, context)

    def _harvest_rows(
        self,
        rows: Sequence[dict],
        page: int,
        context: DiscoverContext,
    ) -> Iterable[Lead]:
        for row in rows:
            lead = self._row_to_lead(row, page)
            if not lead:
                continue
            if not self._lead_in_window(lead, context):
                continue
            yield lead

    @staticmethod
    def _row_ids(rows: Sequence[dict]) -> Set[str]:
        return {str(row.get("raceId") or row.get("id") or "").strip() for row in rows} - {""}

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
