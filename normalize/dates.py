from __future__ import annotations

import re
from typing import Optional


DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})日?"),
    re.compile(r"(20\d{2})\s*(\d{2})(\d{2})"),
]


def extract_date(text: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def extract_year(text: str) -> str:
    match = re.search(r"(20\d{2})", text or "")
    return match.group(1) if match else ""


def in_date_range(value: str, date_from: str = "", date_to: str = "") -> bool:
    if not value:
        return False
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    return True
