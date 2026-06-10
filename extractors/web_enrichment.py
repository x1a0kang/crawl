from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from crawl.extractors.detail import WebEnricher, build_field_evidence, extract_detail_fields
from crawl.models import Evidence, Lead
from crawl.normalize.text import normalize_space


SEARCH_QUERIES = (
    "{name} 竞赛规程",
    "{name} 报名须知",
    "{name} 报名时间",
    "{name} 起点 终点",
    "{name} 领物 地点",
    "{name} 官方",
)
MAX_PAGES_PER_EVENT = 5


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    description: str = ""


@dataclass(frozen=True)
class ScrapedPage:
    title: str
    url: str
    markdown: str
    source_type: str


CommandRunner = Callable[[List[str], int], subprocess.CompletedProcess]


class FirecrawlClient:
    def __init__(self, timeout: int = 60, runner: CommandRunner = None) -> None:
        self.timeout = timeout
        self.runner = runner or self._run
        self._runner_provided = runner is not None

    def available(self) -> bool:
        return self._runner_provided or shutil.which("firecrawl") is not None

    def search(self, query: str, limit: int = 5) -> List[SearchResult]:
        if not self.available():
            return []
        result = self.runner(
            ["firecrawl", "search", query, "--json", "--limit", str(limit)],
            self.timeout,
        )
        if result.returncode != 0:
            return []
        return parse_search_results(result.stdout)

    def scrape(self, url: str) -> str:
        if not self.available():
            return ""
        result = self.runner(
            ["firecrawl", "scrape", url, "--only-main-content"],
            self.timeout,
        )
        if result.returncode != 0:
            return ""
        return result.stdout or ""

    @staticmethod
    def _run(args: List[str], timeout: int) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


class FirecrawlWebEnricher(WebEnricher):
    def __init__(self, client: FirecrawlClient = None, max_pages: int = MAX_PAGES_PER_EVENT) -> None:
        self.client = client or FirecrawlClient()
        self.max_pages = max(1, int(max_pages or MAX_PAGES_PER_EVENT))

    def enrich(self, lead: Lead, candidate_id_value: str) -> Tuple[Dict[str, str], List[Evidence]]:
        pages = self._scrape_pages(lead)
        merged: Dict[str, str] = {}
        evidence: List[Evidence] = []
        for page in pages:
            fields = extract_detail_fields(page.markdown, source_url=page.url)
            for key, value in fields.items():
                if value and not merged.get(key):
                    merged[key] = value
            evidence.extend(
                build_field_evidence(
                    candidate_id_value,
                    fields,
                    page.source_type,
                    page.url,
                    source_title=page.title,
                    extracted_text=page.markdown,
                    confidence=confidence_for_source(page.source_type),
                )
            )
        return merged, evidence

    def _scrape_pages(self, lead: Lead) -> List[ScrapedPage]:
        urls: Dict[str, SearchResult] = {}
        for query in build_queries(lead.event_name):
            for result in self.client.search(query, limit=self.max_pages):
                if not result.url or result.url in urls:
                    continue
                urls[result.url] = result
        ranked = sorted(urls.values(), key=rank_search_result)[: self.max_pages]
        pages: List[ScrapedPage] = []
        for result in ranked:
            markdown = self.client.scrape(result.url)
            if not markdown:
                continue
            pages.append(
                ScrapedPage(
                    title=result.title,
                    url=result.url,
                    markdown=markdown,
                    source_type=classify_source(result.url, result.title, markdown),
                )
            )
        return pages


def build_queries(event_name: str) -> List[str]:
    return [template.format(name=event_name) for template in SEARCH_QUERIES]


def parse_search_results(stdout: str) -> List[SearchResult]:
    try:
        payload = json.loads(stdout or "")
    except ValueError:
        return []
    rows = extract_result_rows(payload)
    results: List[SearchResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link") or row.get("href") or ""
        title = row.get("title") or row.get("name") or url
        description = row.get("description") or row.get("snippet") or row.get("content") or ""
        if url:
            results.append(SearchResult(normalize_space(str(title)), str(url), normalize_space(str(description))))
    return results


def extract_result_rows(payload: object) -> List[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "organic", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_result_rows(value)
            if nested:
                return nested
    return []


def rank_search_result(result: SearchResult) -> tuple[int, str]:
    source_type = classify_source(result.url, result.title, result.description)
    priority = {
        "official_notice": 0,
        "government_notice": 1,
        "wechat_article": 2,
        "registration_platform": 3,
        "media_article": 4,
    }.get(source_type, 5)
    text = f"{result.title} {result.description}"
    if any(term in text for term in ("竞赛规程", "报名须知", "报名公告", "官方")):
        priority -= 1
    return priority, result.url


def classify_source(url: str, title: str = "", text: str = "") -> str:
    host = urlparse(url or "").netloc.lower()
    combined = f"{title} {text} {url}"
    if "mp.weixin.qq.com" in host:
        return "wechat_article"
    if any(part in host for part in (".gov.cn", "sport.gov.cn", "athletics.org.cn", "runchina.org.cn", "chinaath.com")):
        return "government_notice"
    if any(part in host for part in ("reg.", "zuicool.com", "sport-china.cn", "ihuipao", "marathon")) and "官方" in combined:
        return "official_notice"
    if any(part in host for part in ("zuicool.com", "sport-china.cn", "ihuipao", "reg.")):
        return "registration_platform"
    if re.search(r"官方|竞赛规程|报名须知|组委会", combined):
        return "official_notice"
    return "media_article"


def confidence_for_source(source_type: str) -> str:
    return {
        "official_notice": "0.85",
        "government_notice": "0.82",
        "wechat_article": "0.78",
        "registration_platform": "0.70",
        "media_article": "0.55",
    }.get(source_type, "0.50")
