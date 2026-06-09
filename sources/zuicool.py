from __future__ import annotations

import re
from typing import Iterable, List

from urllib.parse import urljoin

from crawl.html_tools import extract_links, strip_tags
from crawl.net import fetch_text
from crawl.models import Lead, SourceConnector
from crawl.normalize.dates import extract_date
from crawl.sources.common import maybe_lead, text_blocks_for_links


class ZuicoolSource(SourceConnector):
    name = "zuicool"
    default_url = "https://zuicool.com/"

    def __init__(self, url: str = None, html: str = None) -> None:
        self.url = url or self.default_url
        self.html = html

    def discover(self) -> Iterable[Lead]:
        html = self.html if self.html is not None else fetch_text(self.url)
        leads: List[Lead] = []
        for href, block in text_blocks_for_links(html, r"/event/\d+"):
            text = strip_tags(block)
            title = self._title_from_block(text)
            if not title:
                continue
            lead = maybe_lead(self.name, urljoin(self.url, href), title, raw_text=text)
            if lead:
                leads.append(lead)
        return leads

    @staticmethod
    def _title_from_block(text: str) -> str:
        for part in re.split(r"\s{2,}|\n", text or ""):
            part = part.strip()
            if re.search(r"20\d{2}.+(马拉松|半程马拉松|全程马拉松|半马|全马)", part):
                return part
        match = re.search(r"(20\d{2}[^。；\n]{0,80}(?:马拉松|半程马拉松|全程马拉松)[^。；\n]{0,60})", text or "")
        return match.group(1).strip() if match else ""
