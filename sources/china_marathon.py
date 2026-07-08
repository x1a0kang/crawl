"""China Marathon official listing source.

The authoritative list is displayed at ``runchina.org.cn/#/race/v/list`` and
backed by China Athletics' public JSON API. We use the API directly so
pagination is controlled by ``pageNo``/``pageSize`` instead of depending on a
browser-rendered SPA page.

This connector:

* walks page 1..``context.max_pages``;
* parses API rows into ``Lead`` objects with ``event_date``, ``event_name``,
  ``province``/``city``, ``event_items`` and the internal detail API ref;
* stops when a page adds no new leads, when the earliest date on the page
  is already older than ``context.date_from`` or when ``max_pages`` is hit.
"""

import json
import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple
from urllib.request import Request, urlopen

from crawl.html_tools import normalize_space, strip_tags
from crawl.models import DiscoverContext, Lead, SourceConnector
from crawl.net import DEFAULT_USER_AGENT
from crawl.normalize.dates import extract_date
from crawl.normalize.filters import infer_items
from crawl.normalize.text import normalize_level_label
from crawl.sources.common import make_lead


RACE_INDEX_URL = "https://www.runchina.org.cn/#/race/v/list"
RACE_API_URL = (
    "https://api-changzheng.chinaath.com/changzheng-content-center-api/"
    "api/homePage/official/searchCompetitionMls"
)
SOURCE_REF_PREFIX = "china-marathon:"
DEFAULT_PAGE_SIZE = 30

# Row schema in legacy table fixtures is:
# 开赛时间 / 比赛名称 / 赛事等级 / 比赛地点 / 比赛项目.
# The live CLI path uses the official JSON API; this table parser remains only
# for deterministic fixture coverage of historical page shapes.
EVENT_TITLE_PATTERN = re.compile(r"(20\d{2}[^|\n]{0,80}(?:马拉松|半程马拉松|全程马拉松|半马|全马)[^|\n]{0,40})")
PROVINCE_CITY_PATTERN = re.compile(r"(?P<province>[^|:\n]{2,8}?)[\s|](?P<city>[^|:\n]{2,20})")


class ChinaMarathonSource(SourceConnector):
    """China Marathon official API source.

    Author: juruikang
    Date: 2026-06-12
    """

    name = "china-marathon"
    default_url = RACE_INDEX_URL
    fallback_url = "https://www.marathon.org.cn/"

    def __init__(
        self,
        url: str = None,
        html_by_page: Optional[Sequence[str]] = None,
        api_by_page: Optional[Sequence[object]] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        """Create a China Marathon source.

        Author: juruikang
        Date: 2026-06-12
        """
        self.url = url or self.default_url
        # ``html_by_page`` is the deterministic, fixture-friendly input used by
        # unit tests: a sequence of HTML payloads, one per page, that the
        # source will iterate through instead of issuing HTTP requests.
        self.html_by_page = html_by_page
        # ``api_by_page`` is the same fixture hook for parsed/raw API payloads.
        self.api_by_page = api_by_page
        self.page_size = max(1, int(page_size or DEFAULT_PAGE_SIZE))

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        """Discover leads from fixtures or the official list API.

        Author: juruikang
        Date: 2026-06-12
        """
        context = context or DiscoverContext()
        max_pages = max(1, int(context.max_pages or 1))

        if self.html_by_page is not None:
            yield from self._iter_fixture_pages(context, max_pages)
            return
        if self.api_by_page is not None:
            yield from self._iter_api_payloads(self.api_by_page, context, max_pages)
            return

        try:
            yield from self._iter_live_api_pages(context, max_pages)
            return
        except Exception as exc:
            context.warn(f"china-marathon: API fetch failed: {exc}")
            return

    # ------------------------------------------------------------------ API

    def _iter_live_api_pages(
        self,
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
        """Page through the live official list API.

        Author: juruikang
        Date: 2026-06-12
        """
        seen_keys: Set[Tuple[str, str]] = set()
        for page in range(1, max_pages + 1):
            payload = self._fetch_api_page(page)
            rows = self._extract_api_rows(payload)
            if not rows:
                break
            yield from self._harvest_api_rows(rows, page, context, seen_keys)
            if self._page_is_past_window(rows, context):
                break
            page_count = self._extract_page_count(payload)
            if page_count and page >= page_count:
                break

    def _iter_api_payloads(
        self,
        payloads: Sequence[object],
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
        """Read API fixture payloads for deterministic tests.

        Author: juruikang
        Date: 2026-06-12
        """
        seen_keys: Set[Tuple[str, str]] = set()
        for page, payload in enumerate(payloads, start=1):
            if page > max_pages:
                break
            if isinstance(payload, (str, bytes)):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    break
            rows = self._extract_api_rows(payload)
            if not rows:
                break
            yield from self._harvest_api_rows(rows, page, context, seen_keys)
            if self._page_is_past_window(rows, context):
                break

    def _fetch_api_page(self, page: int) -> object:
        """Fetch one official list API page.

        Author: juruikang
        Date: 2026-06-12
        """
        payload = {
            "provinceId": "",
            "cityId": "",
            "districtId": "",
            "raceName": "",
            "raceGrade": "",
            "raceStartTime": "",
            "pageNo": page,
            "pageSize": self.page_size,
        }
        request = Request(
            RACE_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://www.runchina.org.cn",
                "Referer": self.url,
            },
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body)

    @staticmethod
    def _extract_api_rows(payload: object) -> List[dict]:
        """Extract race rows from an official API payload.

        Author: juruikang
        Date: 2026-06-12
        """
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if isinstance(data, dict):
            rows = data.get("results") or data.get("list") or data.get("rows")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        rows = payload.get("results") or payload.get("list") or payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return []

    @staticmethod
    def _extract_page_count(payload: object) -> int:
        """Extract the API page count if the server returns one.

        Author: juruikang
        Date: 2026-06-12
        """
        if not isinstance(payload, dict):
            return 0
        data = payload.get("data")
        if isinstance(data, dict):
            return int(data.get("pageCount") or 0)
        return int(payload.get("pageCount") or 0)

    def _harvest_api_rows(
        self,
        rows: List[dict],
        page: int,
        context: DiscoverContext,
        seen_keys: Set[Tuple[str, str]],
    ) -> Iterable[Lead]:
        """Convert API rows into deduplicated leads.

        Author: juruikang
        Date: 2026-06-12
        """
        for row in rows:
            if self._api_row_is_past_window(row, context):
                break
            lead = self._api_row_to_lead(row, page)
            if not lead:
                continue
            key = (lead.event_name, lead.event_date)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            yield lead

    def _api_row_to_lead(self, row: dict, page: int) -> Optional[Lead]:
        """Map one official API row to a lead.

        Author: juruikang
        Date: 2026-06-12
        """
        title = normalize_space(row.get("raceName") or row.get("name") or "")
        if not title:
            return None
        event_date = extract_date(row.get("raceTime") or row.get("raceStartTime") or "")
        address = normalize_space(row.get("raceAddress") or "")
        province, city, district = self._split_location(address)
        items = self._normalize_items(row.get("raceItem") or title)
        if not items:
            return None
        race_id = str(row.get("raceId") or row.get("id") or "").strip()
        source_url = f"{SOURCE_REF_PREFIX}page={page}"
        if race_id:
            source_url = f"{SOURCE_REF_PREFIX}race_id={race_id};page={page}"
        level_label = normalize_level_label(row.get("raceGrade") or "")
        raw_text = " ".join(
            str(part)
            for part in [
                title,
                event_date,
                level_label,
                address,
                row.get("raceItem") or "",
            ]
            if part
        )
        return make_lead(
            source_name=self.name,
            source_url=source_url,
            raw_title=title,
            event_name=title,
            event_date=event_date,
            province=province,
            city=city,
            district=district,
            level_label=level_label,
            event_items=items,
            raw_text=raw_text,
        )

    # --------------------------------------------------------------- fixture

    def _iter_fixture_pages(
        self,
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
        """Read table fixtures used by legacy parser tests.

        Author: juruikang
        Date: 2026-06-12
        """
        seen_keys: Set[Tuple[str, str]] = set()
        for page, html in enumerate(self.html_by_page or [], start=1):
            if page > max_pages:
                break
            rows = self._extract_rows_from_html(html, page=page)
            if not rows:
                break
            yield from self._harvest_rows(rows, context, seen_keys)

    # --------------------------------------------------------- shared harvest

    def _harvest_rows(
        self,
        rows: List[dict],
        context: DiscoverContext,
        seen_keys: Set[Tuple[str, str]],
    ) -> Iterable[Lead]:
        """Convert parsed table rows into deduplicated leads.

        Author: juruikang
        Date: 2026-06-12
        """
        emitted = 0
        for row in rows:
            if self._page_is_past_window([row], context):
                # Short-circuit: the rest of this page is at or before
                # ``context.date_from`` so further rows are even older.
                break
            lead = self._row_to_lead(row, context)
            if not lead:
                continue
            key = (lead.event_name, lead.event_date)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            emitted += 1
            yield lead
        # If the entire page was outside the window or empty, the caller will
        # rely on the (empty) emitted count to decide whether to continue
        # paging. We do not break here because other sources use different
        # stop signals.

    # ------------------------------------------------------------- parsing

    @staticmethod
    def _extract_rows_from_html(html: str, page: int = 1) -> List[dict]:
        """Split fixture HTML/markdown into race rows.

        The real page is a single big table; the markdown converter flattens
        it to ``| ... |`` rows, but to remain robust we simply split on
        ``<tr>``/line boundaries and group the cells of each row.
        """
        if not html:
            return []
        rows: List[dict] = []

        # Strategy 1: real <tr> blocks from HTML fixtures.
        for raw in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
            cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", raw, flags=re.I | re.S)
            cells = [normalize_space(strip_tags(cell)) for cell in cells]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append({"cells": cells, "html": raw, "page": page})

        if rows:
            return rows

        # Strategy 2: markdown table rows starting with '|'.
        for raw in html.splitlines():
            line = raw.strip()
            if not line.startswith("|") and "<" in line:
                line = normalize_space(strip_tags(line))
            if not line.startswith("|"):
                continue
            cells = [normalize_space(cell) for cell in line.strip("|").split("|")]
            cells = [cell for cell in cells if cell]
            if len(cells) >= 2:
                rows.append({"cells": cells, "html": line, "page": page})

        return rows

    @staticmethod
    def _row_to_cells_dict(cells: Sequence[str]) -> dict:
        """Map a row's cells to logical fields.

        Expected schema (5 columns, but we tolerate fewer/more):
        ``开赛时间 / 比赛名称 / 赛事等级 / 比赛地点 / 比赛项目``.

        Author: juruikang
        Date: 2026-06-12
        """
        text = " | ".join(cells)
        date = extract_date(cells[0] if cells else "") or extract_date(text)
        if len(cells) >= 5 and extract_date(cells[0]):
            title = cells[1]
        else:
            title_match = EVENT_TITLE_PATTERN.search(text)
            title = title_match.group(1).strip() if title_match else (cells[1] if len(cells) > 1 else "")
        location = cells[3] if len(cells) > 3 else ""
        province = ""
        city = ""
        district = ""
        if location:
            if "/" in location:
                province, city, district = ChinaMarathonSource._split_location(location)
            else:
                match = PROVINCE_CITY_PATTERN.search(location)
                if match:
                    province = match.group("province").strip()
                    city = match.group("city").strip()
                else:
                    city = location.strip()
        grade = cells[2] if len(cells) > 2 else ""
        level_label = normalize_level_label(grade)
        item_text = f"{title} {cells[4] if len(cells) > 4 else ''}"
        items = ChinaMarathonSource._normalize_items(item_text)
        return {
            "event_date": date,
            "title": title,
            "province": province,
            "city": city,
            "district": district,
            "level_label": level_label,
            "event_items": items,
            "text": text,
        }

    @staticmethod
    def _normalize_items(text: str) -> str:
        """Normalize free-form item text into the stored lead item string.

        Author: juruikang
        Date: 2026-06-12
        """
        return infer_items(text)

    @staticmethod
    def _split_location(location: str) -> Tuple[str, str, str]:
        """Split China Marathon location text into province, city, and district.

        Address format is "省/市/区" with '/' separator.

        Author: juruikang
        Date: 2026-06-12
        """
        parts = [part.strip() for part in (location or "").split("/") if part.strip()]
        province = parts[0] if parts else ""
        city = parts[1] if len(parts) > 1 else ""
        district = parts[2] if len(parts) > 2 else ""
        return province, city, district

    def _row_to_lead(self, row: dict, context: DiscoverContext) -> Optional[Lead]:
        """Map one parsed table fixture row to a lead.

        Author: juruikang
        Date: 2026-06-12
        """
        cells: Sequence[str] = row.get("cells") or []
        if not cells:
            return None
        fields = self._row_to_cells_dict(cells)
        title = fields["title"]
        if not title:
            return None
        items = fields["event_items"]
        if not title or not items:
            return None
        if not context.date_from and not context.date_to:
            pass  # no window to enforce
        source_url = f"{SOURCE_REF_PREFIX}page={row.get('page', 1)}"
        return make_lead(
            source_name=self.name,
            source_url=source_url,
            raw_title=title,
            event_name=title,
            event_date=fields["event_date"],
            province=fields["province"],
            city=fields["city"],
            district=fields.get("district", ""),
            level_label=fields.get("level_label", ""),
            event_items=items,
            raw_text=fields["text"],
        )

    @staticmethod
    def _page_is_past_window(rows: List[dict], context: DiscoverContext) -> bool:
        """Return whether a page is already older than the requested window.

        Author: juruikang
        Date: 2026-06-12
        """
        if not context.date_from:
            return False
        earliest = ""
        for row in rows:
            cells = row.get("cells") or []
            date = extract_date(" ".join(cells)) or extract_date(row.get("raceTime") or "")
            if date and (not earliest or date < earliest):
                earliest = date
        return bool(earliest) and earliest < context.date_from

    @staticmethod
    def _api_row_is_past_window(row: dict, context: DiscoverContext) -> bool:
        """Return whether an API row is older than the requested window.

        Author: juruikang
        Date: 2026-06-12
        """
        if not context.date_from:
            return False
        date = extract_date(row.get("raceTime") or row.get("raceStartTime") or "")
        return bool(date) and date < context.date_from
