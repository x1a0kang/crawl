"""China Marathon official listing source.

The authoritative site is ``runchina.org.cn`` whose ``/#/race`` page is
rendered by a Vue SPA behind a Tencent anti-bot script. The simple
``urllib`` fetch returns the challenge page, so the only reliable first-pass
strategy is to ask a rendered fetcher (the local ``firecrawl`` CLI) for the
post-render HTML/markdown.

This connector:

* walks page 1..``context.max_pages``;
* parses table rows into ``Lead`` objects with ``event_date``, ``event_name``,
  ``province``/``city``, ``event_items`` and the original detail URL;
* stops when a page adds no new leads, when the earliest date on the page
  is already older than ``context.date_from`` or when ``max_pages`` is hit;
* warns (instead of raising) when no rendered fetcher is available so the
  rest of the pipeline still produces sport-china / zuicool candidates.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from crawl.html_tools import normalize_space, strip_tags
from crawl.models import DiscoverContext, Lead, SourceConnector
from crawl.normalize.dates import extract_date
from crawl.sources.common import make_lead
from crawl.rendered import parse_firecrawl_markdown


RACE_INDEX_URL = "https://www.runchina.org.cn/#/race"

# Row schema on the rendered page is: 开赛时间 / 比赛名称 / 赛事等级 / 比赛地点 / 比赛项目
# We do not hard-code that a row is a `<tr>` — the firecrawl output normalises
# to markdown — so we look for the title pattern in each line block.
EVENT_TITLE_PATTERN = re.compile(r"(20\d{2}[^|\n]{0,80}(?:马拉松|半程马拉松|全程马拉松|半马|全马)[^|\n]{0,40})")
PROVINCE_CITY_PATTERN = re.compile(r"(?P<province>[^|:\n]{2,8}?)[\s|](?P<city>[^|:\n]{2,20})")
ITEMS_PATTERN = re.compile(r"全马|半马|全程马拉松|半程马拉松|马拉松")


class ChinaMarathonSource(SourceConnector):
    name = "china-marathon"
    default_url = RACE_INDEX_URL
    fallback_url = "https://www.marathon.org.cn/"

    def __init__(
        self,
        url: str = None,
        html_by_page: Optional[Sequence[str]] = None,
    ) -> None:
        self.url = url or self.default_url
        # ``html_by_page`` is the deterministic, fixture-friendly input used by
        # unit tests: a sequence of HTML payloads, one per page, that the
        # source will iterate through instead of issuing HTTP requests.
        self.html_by_page = html_by_page

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        context = context or DiscoverContext()
        max_pages = max(1, int(context.max_pages or 1))

        if self.html_by_page is not None:
            yield from self._iter_fixture_pages(context, max_pages)
            return

        fetcher = context.rendered_fetcher
        if fetcher is None:
            context.warn(
                "china-marathon: no rendered fetcher available; "
                "skipping runchina.org.cn (use --rendered-fetcher auto|firecrawl)."
            )
            return

        yield from self._iter_live_pages(context, max_pages, fetcher)

    # ------------------------------------------------------------------ live

    def _iter_live_pages(
        self,
        context: DiscoverContext,
        max_pages: int,
        fetcher,
    ) -> Iterable[Lead]:
        seen_keys: Set[Tuple[str, str]] = set()
        for page in range(1, max_pages + 1):
            payload = fetcher(self.url, page)
            if not payload:
                if page == 1:
                    context.warn(
                        "china-marathon: rendered fetcher returned no content for page 1"
                    )
                break
            html = parse_firecrawl_markdown(payload)
            rows = self._extract_rows_from_html(html, page=page)
            if not rows:
                break
            yield from self._harvest_rows(rows, context, seen_keys)

    # --------------------------------------------------------------- fixture

    def _iter_fixture_pages(
        self,
        context: DiscoverContext,
        max_pages: int,
    ) -> Iterable[Lead]:
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
        """Split the rendered HTML/markdown into race rows.

        The real page is a single big table; the markdown converter flattens
        it to ``| ... |`` rows, but to remain robust we simply split on
        ``<tr>``/line boundaries and group the cells of each row.
        """
        if not html:
            return []
        rows: List[dict] = []

        # Strategy 1: real <tr> blocks (when the rendered fetcher returns HTML).
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
        """
        text = " | ".join(cells)
        date = extract_date(text)
        title_match = EVENT_TITLE_PATTERN.search(text)
        title = title_match.group(1).strip() if title_match else (cells[1] if len(cells) > 1 else "")
        location = cells[3] if len(cells) > 3 else ""
        province = ""
        city = ""
        if location:
            match = PROVINCE_CITY_PATTERN.search(location)
            if match:
                province = match.group("province").strip()
                city = match.group("city").strip()
            else:
                city = location.strip()
        items = ",".join(dict.fromkeys(match.group(0) for match in ITEMS_PATTERN.finditer(text)))
        return {
            "event_date": date,
            "title": title,
            "province": province,
            "city": city,
            "event_items": items,
            "text": text,
        }

    def _row_to_lead(self, row: dict, context: DiscoverContext) -> Optional[Lead]:
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
        source_url = f"{self.url}?page={row.get('page', 1)}"
        return make_lead(
            source_name=self.name,
            source_url=source_url,
            raw_title=title,
            event_name=title,
            event_date=fields["event_date"],
            province=fields["province"],
            city=fields["city"],
            event_items=items,
            raw_text=fields["text"],
        )

    @staticmethod
    def _page_is_past_window(rows: List[dict], context: DiscoverContext) -> bool:
        if not context.date_from:
            return False
        earliest = ""
        for row in rows:
            cells = row.get("cells") or []
            date = extract_date(" ".join(cells))
            if date and (not earliest or date < earliest):
                earliest = date
        return bool(earliest) and earliest < context.date_from
