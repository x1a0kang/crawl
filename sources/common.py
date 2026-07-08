from __future__ import annotations

import re
from typing import Iterable, List

from crawl.models import Lead, now_iso
from crawl.normalize.dates import extract_date
from crawl.normalize.filters import infer_items, is_mvp_race
from crawl.normalize.text import lead_id, normalize_space, stable_hash


def make_lead(
    source_name: str,
    source_url: str,
    raw_title: str,
    event_name: str,
    event_date: str = "",
    province: str = "",
    city: str = "",
    district: str = "",
    level_label: str = "",
    event_items: str = "",
    raw_text: str = "",
) -> Lead:
    title = normalize_space(raw_title)
    name = normalize_space(event_name or title)
    date = event_date or extract_date(raw_text or title)
    items = event_items or infer_items(f"{name} {raw_text}")
    raw = raw_text or " ".join([title, name, date, province, city, district, level_label, items])
    return Lead(
        lead_id=lead_id(source_name, source_url, name, date),
        source_name=source_name,
        source_url=source_url,
        raw_title=title,
        event_name=name,
        event_date=date,
        province=normalize_space(province),
        city=normalize_space(city),
        district=normalize_space(district),
        level_label=normalize_space(level_label),
        event_items=items,
        discovered_at=now_iso(),
        raw_hash=stable_hash(raw, 24),
    )


def clean_event_title(title: str) -> str:
    value = normalize_space(title)
    value = re.sub(r"^(报名|重要公告|奖励前\d+名)[｜|\s:：]+", "", value)
    value = re.sub(r"(报名开启|报名了|开启报名|即将报名|点此报名|直通报名)$", "", value)
    value = re.sub(r"\s+20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?.*$", "", value)
    value = re.sub(r"\s+报名(开始|截止)[:：].*$", "", value)
    value = re.sub(r"\s+[^\s]{0,20}(团队|奖励|认证|抽送|跑游|最低|首次|北马).*$", "", value)
    return normalize_space(value)


def maybe_lead(
    source_name: str,
    source_url: str,
    title: str,
    raw_text: str = "",
    province: str = "",
    city: str = "",
) -> Lead:
    event_name = clean_event_title(title)
    items = infer_items(f"{event_name} {raw_text}")
    if not is_mvp_race(event_name, items):
        return None
    return make_lead(
        source_name=source_name,
        source_url=source_url,
        raw_title=title,
        event_name=event_name,
        event_date=extract_date(raw_text),
        province=province,
        city=city,
        event_items=items,
        raw_text=raw_text,
    )


def text_blocks_for_links(html: str, href_pattern: str, window: int = 1200):
    import re

    pattern = re.compile(r'<a\b[^>]*href=["\']([^"\']*%s[^"\']*)["\'][^>]*>(.*?)</a>' % href_pattern, re.I | re.S)
    matches = list(pattern.finditer(html or ""))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(html), match.end() + window)
        block = html[start:end]
        yield match.group(1), block
