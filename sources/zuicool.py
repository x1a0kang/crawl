"""Zuicool (``zuicool.com``) public listing source.

We hit three public listing pages in sequence and parse every ``/event/{id}``
card. The three entries expose different sets of races (public registration,
new registrations and recently approved events) so combining them with the
existing per-source dedup gives a fuller picture.

The connector is page-aware: it walks ``?page=1..N`` and stops when a page
yields no new leads, when ``max_pages`` is reached, or when we are clearly
walking past the configured event-date window.

Connection errors on the optional ``events/reg`` endpoint are downgraded to
warnings so a transient outage does not stop the rest of the pipeline.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence, Set, Tuple
from urllib.error import URLError
from urllib.parse import urljoin

from crawl.html_tools import normalize_space, strip_tags
from crawl.models import DiscoverContext, Lead, SourceConnector
from crawl.net import fetch_text
from crawl.normalize.dates import extract_date
from crawl.sources.common import clean_event_title, make_lead


BASE_URL = "https://zuicool.com"
ENTRIES = (
    "https://zuicool.com/events?type=run&page={page}&per-page=100",
    "https://zuicool.com/events/newreg?page={page}&per-page=100",
    "https://zuicool.com/events/reg?page={page}&per-page=100",
)
TITLE_PATTERN = re.compile(r"20\d{2}[^|\n]{0,80}(?:马拉松|半程马拉松|全程马拉松|半马|全马)")


class ZuicoolSource(SourceConnector):
    name = "zuicool"

    def __init__(
        self,
        html_by_url: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> None:
        # ``html_by_url`` is a test-friendly shortcut: an iterable of
        # ``(url, html)`` pairs that the source will iterate over without
        # performing any HTTP requests.
        self.html_by_url = html_by_url

    def discover(self, context: Optional[DiscoverContext] = None) -> Iterable[Lead]:
        context = context or DiscoverContext()
        max_pages = max(1, int(context.max_pages or 1))
        seen: Set[Tuple[str, str, str]] = set()
        if self.html_by_url is not None:
            for entry_url, html in self.html_by_url:
                yield from self._harvest_page(entry_url, html, context, seen)
            return
        for entry_template in ENTRIES:
            for page in range(1, max_pages + 1):
                url = entry_template.format(page=page)
                try:
                    html = fetch_text(url)
                except (URLError, TimeoutError, OSError) as exc:
                    if "reg" in entry_template:
                        context.warn(f"zuicool: events/reg page {page} fetch failed: {exc}")
                    else:
                        context.warn(f"zuicool: {url} fetch failed: {exc}")
                    break
                if not html:
                    break
                emitted = list(self._harvest_page(url, html, context, seen))
                if not emitted:
                    break

    # ----------------------------------------------------------- parsing

    @staticmethod
    def _harvest_page(
        url: str,
        html: str,
        context: DiscoverContext,
        seen: Set[Tuple[str, str, str]],
    ) -> Iterable[Lead]:
        emitted = 0
        for href, block in _event_card_blocks(html):
            absolute = urljoin(url, href)
            text = strip_tags(block)
            if not TITLE_PATTERN.search(text):
                continue
            title = ZuicoolSource._title_from_block(text)
            if not title:
                continue
            event_date = extract_date(text) or extract_date(title)
            if not ZuicoolSource._date_in_window(event_date, context):
                continue
            lead = make_lead(
                source_name=ZuicoolSource.name,
                source_url=absolute,
                raw_title=title,
                event_name=title,
                event_date=event_date,
                event_items="",  # inferred from title/text inside make_lead
                raw_text=text,
            )
            key = (lead.source_url, lead.event_name, lead.event_date)
            if key in seen:
                continue
            seen.add(key)
            emitted += 1
            yield lead
        return  # explicit noop; the caller uses `emitted` to decide whether to stop

    @staticmethod
    def _title_from_block(text: str) -> str:
        """Extract the first marathon race title found in the block.

        The block may contain multiple event cards stitched together, so we
        grab the first match, run it through ``clean_event_title`` and return
        the result. ``clean_event_title`` strips trailing date / 报名 text.
        """
        for part in re.split(r"\s{2,}|\n", text or ""):
            part = normalize_space(part)
            match = TITLE_PATTERN.search(part)
            if match:
                return clean_event_title(match.group(0))
        match = re.search(r"(20\d{2}[^。；\n]{0,80}(?:马拉松|半程马拉松|全程马拉松|半马|全马))", text or "")
        return clean_event_title(match.group(1)) if match else ""

    @staticmethod
    def _date_in_window(event_date: str, context: DiscoverContext) -> bool:
        if not context.date_from and not context.date_to:
            return True
        if not event_date:
            return True
        if context.date_from and event_date < context.date_from:
            return False
        if context.date_to and event_date > context.date_to:
            return False
        return True


def _event_card_blocks(html: str):
    """Yield ``(href, text_block)`` pairs for each ``/event/{id}`` anchor.

    A "block" is the slice of HTML between the current card's anchor and the
    next ``/event/{id}`` anchor (or the end of the document), giving us a
    loose envelope that contains the event title, date and tags.
    """
    import re

    pattern = re.compile(r'<a\b[^>]*href=["\']([^"\']*/event/\d+[^"\']*)["\'][^>]*>(.*?)</a>', re.I | re.S)
    matches = list(pattern.finditer(html or ""))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        yield match.group(1), html[start:end]
