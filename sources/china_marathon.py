from __future__ import annotations

import re
from typing import Iterable, List

from crawl.html_tools import extract_links, strip_tags
from crawl.net import fetch_text
from crawl.models import Lead, SourceConnector
from crawl.sources.common import make_lead, maybe_lead


class ChinaMarathonSource(SourceConnector):
    name = "china-marathon"
    default_url = "https://www.marathon.org.cn/"

    def __init__(self, url: str = None, html: str = None) -> None:
        self.url = url or self.default_url
        self.html = html

    def discover(self) -> Iterable[Lead]:
        html = self.html if self.html is not None else fetch_text(self.url)
        text = strip_tags(html)
        links = extract_links(html, self.url)
        leads: List[Lead] = []

        # Detail pages often have a single title and sparse official fields.
        detail_title = self._extract_detail_title(text)
        if detail_title:
            lead = maybe_lead(self.name, self.url, detail_title, raw_text=text)
            if lead:
                leads.append(lead)

        # List/calendar pages expose race detail links.
        for link in links:
            if "race" not in link.href.lower() and "marathon" not in link.href.lower():
                continue
            title = link.text or link.title
            if not title:
                continue
            lead = maybe_lead(self.name, link.href, title, raw_text=title)
            if lead:
                leads.append(lead)
        return leads

    @staticmethod
    def _extract_detail_title(text: str) -> str:
        match = re.search(r"(20\d{2}[^，。；\n]{0,40}(?:马拉松|半程马拉松|全程马拉松)[^，。；\n]{0,20})", text)
        if match:
            return match.group(1).strip()
        return ""
