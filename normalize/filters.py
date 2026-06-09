from __future__ import annotations

from typing import Iterable


INCLUDE_TERMS = ("马拉松", "半程马拉松", "半马", "全程马拉松", "全马")
EXCLUDE_TERMS = ("越野", "跑山", "健康跑", "欢乐跑", "亲子跑", "线上赛", "线上跑", "铁人三项", "垂直马拉松")
STRONG_ROAD_TERMS = ("半程马拉松", "半马", "全程马拉松", "全马")


def is_mvp_race(name: str, event_items: str = "") -> bool:
    text = f"{name or ''} {event_items or ''}"
    if not any(term in text for term in INCLUDE_TERMS):
        return False
    if any(term in text for term in EXCLUDE_TERMS) and not any(term in text for term in STRONG_ROAD_TERMS):
        return False
    return True


def infer_items(text: str) -> str:
    value = text or ""
    items = []
    if "全程马拉松" in value or "全马" in value:
        items.append("全马")
    if "半程马拉松" in value or "半马" in value:
        items.append("半马")
    if not items and "马拉松" in value:
        items.append("马拉松")
    return ",".join(dict.fromkeys(items))
