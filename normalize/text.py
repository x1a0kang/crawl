from __future__ import annotations

import hashlib
import re


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha1((value or "").encode("utf-8")).hexdigest()[:length]


def normalize_space(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def normalize_event_name(name: str) -> str:
    value = normalize_space(name)
    value = re.sub(r"^[【\[]?报名[】\]]?[｜|:\s]+", "", value)
    value = re.sub(r"^\d{4}\s*", "", value)
    value = re.sub(r"\s+20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?.*$", "", value)
    value = re.sub(r"\s+报名(开始|截止)[:：].*$", "", value)
    value = re.sub(r"[“”\"'·•\s]+", "", value)
    value = re.sub(r"(赛|赛事)$", "", value)
    return value


def lead_id(source_name: str, source_url: str, event_name: str, event_date: str = "") -> str:
    return stable_hash("|".join([source_name, source_url, event_name, event_date]))


def candidate_id(normalized_name: str, event_date: str, city: str) -> str:
    return stable_hash("|".join([normalized_name, event_date, city]))


def normalize_level_label(value: str) -> str:
    """Clean China Marathon race grade labels.

    Strips suffixes like "属地办赛" (with optional brackets/spaces).
    Returns the cleaned label. If result is not A/B/C, returns the cleaned
    original text.

    Author: juruikang
    Date: 2026-06-12
    """
    text = normalize_space(value)
    cleaned = re.sub(r"[\s（(]*属地办赛.*$", "", text)
    if cleaned in {"A", "B", "C"}:
        return cleaned
    return cleaned or text
