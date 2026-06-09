from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Iterable, List
from urllib.parse import urljoin


@dataclass(frozen=True)
class Link:
    href: str
    text: str
    title: str


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: List[Link] = []
        self._href = ""
        self._title = ""
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and "href" in attrs_dict:
            self._href = urljoin(self.base_url, attrs_dict.get("href", ""))
            self._title = attrs_dict.get("title", "")
            self._parts = []
        elif self._href and tag == "img":
            alt = attrs_dict.get("alt", "")
            if alt:
                self._parts.append(alt)

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = normalize_space(" ".join(self._parts))
            self.links.append(Link(self._href, text, normalize_space(self._title)))
            self._href = ""
            self._title = ""
            self._parts = []


def extract_links(html: str, base_url: str) -> List[Link]:
    parser = LinkExtractor(base_url)
    parser.feed(html)
    return parser.links


def strip_tags(html: str) -> str:
    class TextParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: List[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = TextParser()
    parser.feed(html)
    return normalize_space(" ".join(parser.parts))


def normalize_space(value: str) -> str:
    return " ".join(unescape(value or "").replace("\xa0", " ").split())

