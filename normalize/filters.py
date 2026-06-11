from __future__ import annotations

from typing import List
import re


HARD_EXCLUDE_TERMS = ("越野", "跑山", "线上赛", "线上跑", "铁人三项", "垂直马拉松")
SOFT_EXCLUDE_TERMS = ("健康跑", "欢乐跑", "亲子跑")

FULL_PATTERNS = [
    re.compile(r"全程马拉松|全程|全马"),
    re.compile(r"42(?:\.195)?\s*(?:公里|千米|k|km)\b", re.I),
]
HALF_PATTERNS = [
    re.compile(r"半程马拉松|半程|半马"),
    re.compile(r"21(?:\.0975|\.1)?\s*(?:公里|千米|k|km)\b", re.I),
]
TEN_K_PATTERNS = [
    re.compile(r"十\s*公里"),
    re.compile(r"10\s*(?:公里|千米|k|km)\b", re.I),
]


def extract_item_types(text: str) -> List[str]:
    value = normalize_race_text(text)
    items: List[str] = []
    if any(pattern.search(value) for pattern in FULL_PATTERNS):
        items.append("full_marathon")
    if any(pattern.search(value) for pattern in HALF_PATTERNS):
        items.append("half_marathon")
    if any(pattern.search(value) for pattern in TEN_K_PATTERNS):
        items.append("ten_km")
    if not items and "马拉松" in value:
        items.append("full_marathon")
    return items


def is_mvp_race(name: str, event_items: str = "") -> bool:
    text = normalize_race_text(f"{name or ''} {event_items or ''}")
    item_types = extract_item_types(text)
    if not item_types:
        return False
    if any(term in text for term in HARD_EXCLUDE_TERMS):
        return False
    if any(term in text for term in SOFT_EXCLUDE_TERMS) and not item_types:
        return False
    return True


def infer_items(text: str) -> str:
    value = normalize_race_text(text)
    items = []
    item_types = extract_item_types(value)
    if "full_marathon" in item_types:
        items.append("全程马拉松")
    if "half_marathon" in item_types:
        items.append("半程马拉松")
    if "ten_km" in item_types:
        items.append("10公里")
    return ",".join(dict.fromkeys(items))


def normalize_race_text(text: str) -> str:
    return (text or "").replace("Ｋ", "K").replace("ｋ", "k").replace("　", " ")
