"""中国马拉松官网爬虫 — 直接从 search 分页接口拉取赛事数据并输出 events.csv。

用法:
    python3 crawl_china_marathon.py                          # 默认最近3年
    python3 crawl_china_marathon.py 2025-01-01 2025-12-31    # 指定日期范围
    python3 crawl_china_marathon.py 2025-01-01 2025-12-31 output/2025-events.csv

Author: juruikang
"""

import csv
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ API config

RACE_API_URL = (
    "https://api-changzheng.chinaath.com/changzheng-content-center-api/"
    "api/homePage/official/searchCompetitionMls"
)
RACE_INDEX_URL = "https://www.runchina.org.cn/#/race/v/list"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
DEFAULT_PAGE_SIZE = 30
MAX_PAGES = 120

EVENT_FIELDS = [
    "name", "province", "city", "district", "event_date",
    "item_types", "level_label", "organizer", "status",
]

# ------------------------------------------------------------------ data model


@dataclass(frozen=True)
class Event:
    name: str
    province: str
    city: str
    district: str
    event_date: str
    item_types: List[str]
    level_label: str = ""
    organizer: str = ""
    status: str = "public"

    def to_row(self) -> Dict[str, str]:
        row = {f: str(asdict(self).get(f, "")) for f in EVENT_FIELDS}
        row["item_types"] = _pg_array(self.item_types)
        return row


def _pg_array(values: Iterable[str]) -> str:
    items = [str(v).strip() for v in values if str(v or "").strip()]
    return "[" + ",".join(f'"{v.replace(chr(34), chr(92)+chr(34))}"' for v in items) + "]"

# ------------------------------------------------------------------ text utils


def _normalize_space(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})日?"),
    re.compile(r"(20\d{2})\s*(\d{2})(\d{2})"),
]


def _extract_date(text: str) -> str:
    for p in _DATE_PATTERNS:
        m = p.search(text or "")
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return ""


def _normalize_level_label(value: str) -> str:
    text = _normalize_space(value)
    cleaned = re.sub(r"[\s（(]*属地办赛.*$", "", text)
    if cleaned in {"A", "B", "C"}:
        return cleaned
    return cleaned or text


_FULL_PATTERNS = [re.compile(r"全程马拉松|全程|全马"), re.compile(r"42(?:\.195)?\s*(?:公里|千米|k|km)\b", re.I)]
_HALF_PATTERNS = [re.compile(r"半程马拉松|半程|半马"), re.compile(r"21(?:\.0975|\.1)?\s*(?:公里|千米|k|km)\b", re.I)]
_TEN_K_PATTERNS = [re.compile(r"十\s*公里"), re.compile(r"10\s*(?:公里|千米|k|km)\b", re.I)]
_HARD_EXCLUDE = ("越野", "跑山", "线上赛", "线上跑", "铁人三项", "垂直马拉松")


def _extract_item_types(text: str) -> List[str]:
    v = (text or "").replace("Ｋ", "K").replace("ｋ", "k").replace("　", " ")
    items: List[str] = []
    if any(p.search(v) for p in _FULL_PATTERNS):
        items.append("full_marathon")
    if any(p.search(v) for p in _HALF_PATTERNS):
        items.append("half_marathon")
    if any(p.search(v) for p in _TEN_K_PATTERNS):
        items.append("ten_km")
    if not items and "马拉松" in v:
        items.append("full_marathon")
    return items


def _is_mvp_race(name: str, extra: str = "") -> bool:
    text = f"{name or ''} {extra or ''}"
    items = _extract_item_types(text)
    if not items:
        return False
    if any(term in text for term in _HARD_EXCLUDE):
        return False
    return True


def _split_location(location: str) -> Tuple[str, str, str]:
    parts = [p.strip() for p in (location or "").split("/") if p.strip()]
    return (
        parts[0] if parts else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
    )

# ------------------------------------------------------------------ dedupe


def _dedupe(events: List[Event]) -> List[Event]:
    by_key: Dict[str, Event] = {}
    for e in events:
        key = f"{e.name}|{e.event_date}|{e.city}"
        if key not in by_key:
            by_key[key] = e
    return list(by_key.values())

# ------------------------------------------------------------------ API fetch


def _fetch_page(page: int, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    payload = {
        "provinceId": "", "cityId": "", "districtId": "",
        "raceName": "", "raceGrade": "", "raceStartTime": "",
        "pageNo": page, "pageSize": page_size,
    }
    req = Request(
        RACE_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.runchina.org.cn",
            "Referer": RACE_INDEX_URL,
        },
    )
    with urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _extract_rows(payload: dict) -> List[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        rows = data.get("results") or data.get("list") or data.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    rows = payload.get("results") or payload.get("list") or payload.get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _extract_page_count(payload: dict) -> int:
    if not isinstance(payload, dict):
        return 0
    data = payload.get("data")
    if isinstance(data, dict):
        return int(data.get("pageCount") or 0)
    return int(payload.get("pageCount") or 0)


def _row_to_event(row: dict) -> Optional[Event]:
    title = _normalize_space(row.get("raceName") or row.get("name") or "")
    if not title:
        return None
    race_item = str(row.get("raceItem") or "")
    if not _is_mvp_race(title, race_item):
        return None
    event_date = _extract_date(row.get("raceTime") or row.get("raceStartTime") or "")
    province, city, district = _split_location(_normalize_space(row.get("raceAddress") or ""))
    level_label = _normalize_level_label(row.get("raceGrade") or "")
    item_types = _extract_item_types(f"{title} {race_item}")
    return Event(
        name=title, province=province, city=city, district=district,
        event_date=event_date, item_types=item_types,
        level_label=level_label, organizer="", status="public",
    )

# ------------------------------------------------------------------ main flow


def crawl(date_from: str = "", date_to: str = "", max_pages: int = MAX_PAGES) -> List[Event]:
    events: List[Event] = []
    seen: set = set()
    for page in range(1, max_pages + 1):
        logger.info("fetching page %d ...", page)
        try:
            payload = _fetch_page(page)
        except Exception as exc:
            logger.error("page %d fetch failed: %s", page, exc)
            break
        rows = _extract_rows(payload)
        if not rows:
            logger.info("page %d: empty, stopping", page)
            break
        page_added = 0
        for row in rows:
            row_date = _extract_date(row.get("raceTime") or row.get("raceStartTime") or "")
            if row_date and date_from and row_date < date_from:
                logger.info("page %d: reached date boundary, stopping", page)
                return _dedupe(events)
            ev = _row_to_event(row)
            if not ev:
                continue
            if date_from and ev.event_date < date_from:
                continue
            if date_to and ev.event_date > date_to:
                continue
            key = (ev.name, ev.event_date)
            if key in seen:
                continue
            seen.add(key)
            events.append(ev)
            page_added += 1
        logger.info("page %d: added %d events (total %d)", page, page_added, len(events))
        page_count = _extract_page_count(payload)
        if page_count and page >= page_count:
            logger.info("reached last page (%d)", page_count)
            break
    return _dedupe(events)


def write_csv(events: List[Event], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for ev in events:
            writer.writerow(ev.to_row())
    logger.info("wrote %d events to %s", len(events), path)


def _default_window() -> Tuple[str, str]:
    end = date.today()
    try:
        start = end.replace(year=end.year - 3)
    except ValueError:
        start = end.replace(year=end.year - 3, day=28)
    return start.isoformat(), end.isoformat()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2:
        d_from, d_to = args[0], args[1]
    else:
        d_from, d_to = _default_window()
    out_path = Path(args[2]) if len(args) >= 3 else Path("crawl/output/events.csv")

    logger.info("date window: %s .. %s", d_from or "*", d_to or "*")
    events = crawl(d_from, d_to)
    write_csv(events, out_path)
