from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from crawl.html_tools import extract_links, strip_tags
from crawl.net import fetch_text
from crawl.models import Candidate, Evidence, Lead, now_iso
from crawl.normalize.dates import extract_year
from crawl.normalize.filters import is_mvp_race
from crawl.normalize.text import candidate_id, normalize_event_name, normalize_space


REGISTRATION_START_PATTERNS = [
    re.compile(r"报名开始[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?\s*\d{0,2}:?\d{0,2})"),
    re.compile(r"预报名时间[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)"),
]
REGISTRATION_END_PATTERNS = [
    re.compile(r"报名截止[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?\s*\d{0,2}:?\d{0,2})"),
    re.compile(r"至\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?\s*\d{0,2}:?\d{0,2})"),
]
FEE_PATTERN = re.compile(r"(报名费|费用|价格)[:：]?\s*([0-9]{2,4}\s*元(?:/[^\s，。；]+)?)")
START_PATTERN = re.compile(r"(起点|起跑点)[:：]?\s*([^，。；\n]{2,40})")
FINISH_PATTERN = re.compile(r"(终点)[:：]?\s*([^，。；\n]{2,40})")


def extract_from_leads(leads: Iterable[Lead], fetch_details: bool = True) -> Tuple[List[Candidate], List[Evidence]]:
    candidates: List[Candidate] = []
    evidence: List[Evidence] = []
    for lead in leads:
        if not is_mvp_race(lead.event_name, lead.event_items):
            continue
        html = ""
        text = ""
        links = []
        if fetch_details and lead.source_url.startswith(("http://", "https://")):
            try:
                html = fetch_text(lead.source_url)
                text = strip_tags(html)
                links = extract_links(html, lead.source_url)
            except Exception:
                text = ""
                links = []
        fields = extract_detail_fields(text, links, lead)
        normalized_name = normalize_event_name(lead.event_name)
        cid = candidate_id(normalized_name, lead.event_date, lead.city)
        confidence = confidence_for(lead, fields)
        candidate = Candidate(
            candidate_id=cid,
            lead_id=lead.lead_id,
            normalized_name=normalized_name,
            event_date=lead.event_date,
            province=lead.province,
            city=lead.city,
            event_items=lead.event_items,
            registration_start_at=fields.get("registration_start_at", ""),
            registration_end_at=fields.get("registration_end_at", ""),
            fee=fields.get("fee", ""),
            start_point=fields.get("start_point", ""),
            finish_point=fields.get("finish_point", ""),
            official_site_url=fields.get("official_site_url", ""),
            official_registration_url=fields.get("official_registration_url", ""),
            route_image_url=fields.get("route_image_url", ""),
            confidence_score=f"{confidence:.2f}",
            review_status="pending_review",
        )
        candidates.append(candidate)
        evidence.extend(build_evidence(candidate, lead, fields))
        evidence.extend(build_search_query_evidence(candidate, lead))
    return candidates, evidence


def extract_detail_fields(text: str, links, lead: Lead) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    compact_text = normalize_space(text)
    for field, patterns in [
        ("registration_start_at", REGISTRATION_START_PATTERNS),
        ("registration_end_at", REGISTRATION_END_PATTERNS),
    ]:
        for pattern in patterns:
            match = pattern.search(compact_text)
            if match:
                fields[field] = normalize_space(match.group(1))
                break
    fee_match = FEE_PATTERN.search(compact_text)
    if fee_match:
        fields["fee"] = normalize_space(fee_match.group(2))
    for field, pattern in [("start_point", START_PATTERN), ("finish_point", FINISH_PATTERN)]:
        match = pattern.search(compact_text)
        if match:
            fields[field] = normalize_space(match.group(2))

    for link in links:
        text_value = f"{link.text} {link.title} {link.href}"
        if "路线" in text_value or "线路" in text_value:
            fields.setdefault("route_image_url", link.href)
        if "官网" in text_value or "官方网站" in text_value:
            fields.setdefault("official_site_url", link.href)
        if "报名" in text_value or "reg." in link.href or "registration" in link.href.lower():
            fields.setdefault("official_registration_url", link.href)

    if lead.source_name in {"zuicool", "sport-china"}:
        fields.setdefault("official_registration_url", lead.source_url)
    if lead.source_url.startswith(("http://", "https://")) and lead.source_name == "china-marathon":
        fields.setdefault("official_site_url", lead.source_url)
    return fields


def confidence_for(lead: Lead, fields: Dict[str, str]) -> float:
    score = 0.45
    if lead.event_date:
        score += 0.10
    if lead.city or lead.province:
        score += 0.05
    if fields.get("official_site_url") or fields.get("official_registration_url"):
        score += 0.10
    if fields.get("registration_start_at") or fields.get("registration_end_at"):
        score += 0.10
    if lead.source_name == "china-marathon":
        score += 0.05
    return min(score, 0.90)


def build_evidence(candidate: Candidate, lead: Lead, fields: Dict[str, str]) -> List[Evidence]:
    items = [
        ("normalized_name", candidate.normalized_name, lead.source_name, lead.source_url, "0.80"),
        ("event_date", candidate.event_date, lead.source_name, lead.source_url, "0.75"),
        ("event_items", candidate.event_items, lead.source_name, lead.source_url, "0.70"),
        ("province", candidate.province, lead.source_name, lead.source_url, "0.60"),
        ("city", candidate.city, lead.source_name, lead.source_url, "0.60"),
    ]
    for field_name, field_value in fields.items():
        if field_value:
            source_type = source_type_for(field_value, lead)
            items.append((field_name, field_value, source_type, lead.source_url, "0.65"))
    return [
        Evidence(candidate.candidate_id, name, value, source_type, source_url, now_iso(), confidence)
        for name, value, source_type, source_url, confidence in items
        if value
    ]


def build_search_query_evidence(candidate: Candidate, lead: Lead) -> List[Evidence]:
    year = extract_year(lead.event_date) or extract_year(lead.event_name)
    if year and lead.event_name.startswith(year):
        prefix = lead.event_name
    else:
        prefix = f"{year} {lead.event_name}".strip()
    queries = [
        f"{prefix} 官方",
        f"{prefix} 竞赛规程",
        f"{prefix} 报名须知",
        f"{prefix} 报名入口",
        f"{prefix} 路线图",
    ]
    return [
        Evidence(candidate.candidate_id, "manual_search_query", query, "manual_followup", "", now_iso(), "0.50")
        for query in queries
    ]


def source_type_for(value: str, lead: Lead) -> str:
    if lead.source_name in {"zuicool", "sport-china"}:
        return "registration_platform"
    if lead.source_name == "china-marathon":
        return "official_index"
    if "mp.weixin.qq.com" in value:
        return "wechat_article"
    return lead.source_name
