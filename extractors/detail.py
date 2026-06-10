from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen

from crawl.models import EventCandidate, Evidence, Lead, now_iso
from crawl.net import DEFAULT_USER_AGENT
from crawl.normalize.dates import extract_date
from crawl.normalize.filters import extract_item_types, is_mvp_race
from crawl.normalize.text import candidate_id, normalize_event_name, normalize_space


CHINA_MARATHON_DETAIL_API_URL = (
    "https://api-changzheng.chinaath.com/changzheng-content-center-api/"
    "api/homePage/official/searchById"
)
CHINA_MARATHON_DETAIL_TIMEOUT = 10

REGISTRATION_RANGE_PATTERN = re.compile(
    r"(?:报名时间|报名日期|报名期限|报名通道|报名).*?"
    r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?).{0,20}?"
    r"(?:至|到|—|-|~|－).{0,20}?"
    r"(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?)"
)
REGISTRATION_START_PATTERNS = [
    re.compile(r"(?:报名开始|报名开启|开始报名|报名启动)[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?)"),
    re.compile(r"预报名时间[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)"),
]
REGISTRATION_END_PATTERNS = [
    re.compile(r"(?:报名截止|截止报名|报名结束)[:：]?\s*(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?(?:\s*\d{1,2}[:：]\d{2})?)"),
]
LOTTERY_PATTERNS = [
    re.compile(r"(?:抽签结果|中签结果|出签结果|开奖结果|出签).*?(20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)"),
]
START_TIME_PATTERNS = [
    re.compile(r"(?:比赛时间|发枪时间|起跑时间|开跑时间)[:：]?\s*(?:20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?)?\s*(\d{1,2}[:：]\d{2})"),
]
START_POINT_PATTERN = re.compile(r"(?:起点|起跑点|起跑地点)[:：]?\s*([^，。；\n\r]{2,80})")
FINISH_POINT_PATTERN = re.compile(r"(?:终点|终点位置)[:：]?\s*([^，。；\n\r]{2,80})")
PACKET_PICKUP_PATTERN = re.compile(r"(?:领物地点|领物处|装备领取地点|参赛物品领取地点)[:：]?\s*([^，。；\n\r]{2,100})")
CERTIFICATION_PATTERNS = [
    re.compile(r"世界田联(?:白金标|金标|银标|铜标)"),
    re.compile(r"(?:白金标|金标|银标|铜标|精英牌|标牌)"),
]


ProgressCallback = Callable[[int, int, Lead], None]
WarningCallback = Callable[[str], None]


class WebEnricher:
    def enrich(self, lead: Lead, candidate_id_value: str) -> Tuple[Dict[str, str], List[Evidence]]:
        raise NotImplementedError


@dataclass
class EventBuild:
    fields: Dict[str, object]
    evidence: List[Evidence]


def extract_from_leads(
    leads: Iterable[Lead],
    fetch_details: bool = True,
    progress: Optional[ProgressCallback] = None,
    warn: Optional[WarningCallback] = None,
    web_enricher: Optional[WebEnricher] = None,
) -> Tuple[List[EventCandidate], List[Evidence]]:
    lead_list = list(leads)
    candidates: List[EventCandidate] = []
    evidence: List[Evidence] = []
    total = len(lead_list)
    for index, lead in enumerate(lead_list, start=1):
        if not is_mvp_race(lead.event_name, lead.event_items):
            continue
        if progress is not None:
            progress(index, total, lead)

        build = build_event_from_lead(lead)
        if fetch_details and lead.source_name == "china-marathon":
            try:
                payload = fetch_china_marathon_detail_payload(lead)
                official_fields = china_marathon_detail_fields(payload, lead)
                merge_fields(build.fields, official_fields)
                build.evidence.extend(
                    build_field_evidence(
                        "",
                        official_fields,
                        "official_index",
                        lead.source_url,
                        source_title=lead.event_name,
                        extracted_text=china_marathon_detail_text(payload),
                        confidence="0.85",
                    )
                )
            except Exception as exc:
                if warn is not None:
                    warn(f"detail fetch failed for {lead.source_name} {lead.event_name}: {exc}")

        cid = candidate_id(
            normalize_event_name(str(build.fields.get("name") or lead.event_name)),
            str(build.fields.get("event_date") or lead.event_date),
            str(build.fields.get("city") or lead.city),
        )
        build.evidence = [replace_candidate_id(item, cid) for item in build.evidence]

        if fetch_details and web_enricher is not None:
            try:
                web_fields, web_evidence = web_enricher.enrich(lead, cid)
                merge_fields(build.fields, web_fields)
                build.evidence.extend(web_evidence)
            except Exception as exc:
                if warn is not None:
                    warn(f"web enrichment failed for {lead.event_name}: {exc}")

        candidate = event_candidate_from_fields(cid, lead.lead_id, build.fields)
        candidates.append(candidate)
        evidence.extend(build.evidence)
        evidence.extend(build_candidate_status_evidence(candidate))
        evidence.extend(build_search_query_evidence(cid, lead))
    return candidates, evidence


def build_event_from_lead(lead: Lead) -> EventBuild:
    item_types = extract_item_types(f"{lead.event_name} {lead.event_items}")
    fields: Dict[str, object] = {
        "name": lead.event_name,
        "province": lead.province,
        "city": lead.city,
        "district": "",
        "event_date": lead.event_date,
        "item_types": item_types,
        "address_text": " ".join(part for part in [lead.province, lead.city] if part),
        "status": "draft",
    }
    evidence = build_field_evidence("", fields, "official_index", lead.source_url, lead.raw_title)
    return EventBuild(fields=fields, evidence=evidence)


def fetch_china_marathon_detail_payload(lead: Lead) -> object:
    race_id = extract_china_marathon_race_id(lead.source_url)
    if not race_id:
        return {}
    payload = {"id": race_id, "type": "SS"}
    request = Request(
        CHINA_MARATHON_DETAIL_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.runchina.org.cn",
            "Referer": "https://www.runchina.org.cn/#/race/v/list",
        },
    )
    with urlopen(request, timeout=CHINA_MARATHON_DETAIL_TIMEOUT) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


def fetch_china_marathon_detail_text(lead: Lead) -> str:
    return china_marathon_detail_text(fetch_china_marathon_detail_payload(lead))


def extract_china_marathon_race_id(url: str) -> str:
    match = re.search(r"^china-marathon:race_id=([^;]+)(?:;|$)", url or "")
    return match.group(1) if match else ""


def china_marathon_detail_fields(payload: object, lead: Lead) -> Dict[str, object]:
    detail = china_marathon_detail_object(payload)
    if not detail:
        return {}
    province = normalize_space(detail.get("province") or lead.province)
    city = normalize_space(detail.get("city") or lead.city)
    district = normalize_space(detail.get("area") or "")
    project = normalize_space(detail.get("project") or lead.event_items)
    name = normalize_space(detail.get("name") or lead.event_name)
    fields: Dict[str, object] = {
        "name": name,
        "province": province,
        "city": city,
        "district": district,
        "event_date": extract_date(detail.get("gameDate") or "") or lead.event_date,
        "item_types": extract_item_types(f"{name} {project} {lead.event_items}"),
        "level_label": normalize_level_label(detail.get("raceGrade") or ""),
        "organizer": normalize_space(detail.get("compNameOrganizer") or ""),
        "address_text": " ".join(part for part in [province, city, district] if part),
    }
    return {key: value for key, value in fields.items() if value}


def china_marathon_detail_object(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    detail = data.get("ssdetails")
    return detail if isinstance(detail, dict) else {}


def china_marathon_detail_text(payload: object) -> str:
    detail = china_marathon_detail_object(payload)
    if not detail:
        return ""
    parts = [
        detail.get("name") or "",
        detail.get("gameDate") or "",
        detail.get("raceGrade") or "",
        detail.get("province") or "",
        detail.get("city") or "",
        detail.get("area") or "",
        detail.get("project") or "",
        detail.get("scale") or "",
        detail.get("compNameOrganizer") or "",
        detail.get("compNameUndertaker") or "",
        detail.get("compNamePromotionUnit") or "",
        detail.get("compNameCoOrganizer") or "",
    ]
    return normalize_space(" ".join(str(part) for part in parts if part))


def extract_detail_fields(text: str, source_url: str = "") -> Dict[str, str]:
    compact_text = normalize_space(text)
    fields: Dict[str, str] = {}
    range_match = REGISTRATION_RANGE_PATTERN.search(compact_text)
    if range_match:
        fields["registration_start_at"] = normalize_datetime(range_match.group(1))
        fields["registration_end_at"] = normalize_datetime(range_match.group(2))
    for field, patterns in [
        ("registration_start_at", REGISTRATION_START_PATTERNS),
        ("registration_end_at", REGISTRATION_END_PATTERNS),
        ("lottery_result_date", LOTTERY_PATTERNS),
        ("start_time", START_TIME_PATTERNS),
    ]:
        if fields.get(field):
            continue
        for pattern in patterns:
            match = pattern.search(compact_text)
            if match:
                value = normalize_time(match.group(1)) if field == "start_time" else normalize_date_or_datetime(match.group(1), field)
                fields[field] = value
                break
    for field, pattern in [
        ("start_point", START_POINT_PATTERN),
        ("finish_point", FINISH_POINT_PATTERN),
        ("packet_pickup_location", PACKET_PICKUP_PATTERN),
    ]:
        match = pattern.search(compact_text)
        if match:
            fields[field] = clean_short_text(match.group(1))
    for pattern in CERTIFICATION_PATTERNS:
        match = pattern.search(compact_text)
        if match:
            fields["certification_label"] = normalize_space(match.group(0))
            break
    if source_url:
        fields["official_site_url"] = source_url
    if compact_text:
        fields["description"] = compact_text[:300]
    return {key: value for key, value in fields.items() if value}


def event_candidate_from_fields(candidate_id_value: str, lead_id: str, fields: Dict[str, object]) -> EventCandidate:
    event_date = str(fields.get("event_date") or "")
    registration_start = str(fields.get("registration_start_at") or "")
    registration_end = str(fields.get("registration_end_at") or "")
    race_status = derive_race_status(event_date)
    registration_status = derive_registration_status(registration_start, registration_end)
    item_types = fields.get("item_types") or []
    if isinstance(item_types, str):
        item_types = extract_item_types(item_types)
    return EventCandidate(
        candidate_id=candidate_id_value,
        lead_id=lead_id,
        name=str(fields.get("name") or ""),
        province=str(fields.get("province") or ""),
        city=str(fields.get("city") or ""),
        district=str(fields.get("district") or ""),
        event_date=event_date,
        item_types=list(item_types),
        start_time=str(fields.get("start_time") or ""),
        registration_start_at=registration_start,
        registration_end_at=registration_end,
        lottery_result_date=str(fields.get("lottery_result_date") or ""),
        registration_status=str(fields.get("registration_status") or registration_status),
        race_status=str(fields.get("race_status") or race_status),
        level_label=str(fields.get("level_label") or ""),
        certification_label=str(fields.get("certification_label") or ""),
        organizer=str(fields.get("organizer") or ""),
        start_point=str(fields.get("start_point") or ""),
        finish_point=str(fields.get("finish_point") or ""),
        packet_pickup_location=str(fields.get("packet_pickup_location") or ""),
        address_text=str(fields.get("address_text") or ""),
        official_site_url=str(fields.get("official_site_url") or ""),
        description=str(fields.get("description") or ""),
        status=str(fields.get("status") or "draft"),
    )


def build_field_evidence(
    candidate_id_value: str,
    fields: Dict[str, object],
    source_type: str,
    source_url: str,
    source_title: str = "",
    extracted_text: str = "",
    confidence: str = "0.75",
) -> List[Evidence]:
    evidence: List[Evidence] = []
    for field_name, value in fields.items():
        if not value:
            continue
        field_value = ",".join(value) if isinstance(value, list) else str(value)
        evidence.append(
            Evidence(
                candidate_id=candidate_id_value,
                field_name=field_name,
                field_value=field_value,
                source_type=source_type,
                source_url=source_url,
                extracted_at=now_iso(),
                confidence=confidence,
                source_title=source_title,
                extracted_text=extracted_text[:500],
            )
        )
    return evidence


def build_candidate_status_evidence(candidate: EventCandidate) -> List[Evidence]:
    fields = {
        "registration_status": candidate.registration_status,
        "race_status": candidate.race_status,
        "status": candidate.status,
    }
    return build_field_evidence(
        candidate.candidate_id,
        fields,
        "derived",
        "",
        source_title="pipeline derived status",
        extracted_text="registration_status/race_status/status derived from extracted dates and pipeline defaults",
        confidence="0.70",
    )


def build_search_query_evidence(candidate_id_value: str, lead: Lead) -> List[Evidence]:
    queries = [
        f"{lead.event_name} 竞赛规程",
        f"{lead.event_name} 报名须知",
        f"{lead.event_name} 报名时间",
        f"{lead.event_name} 起点 终点",
        f"{lead.event_name} 领物 地点",
        f"{lead.event_name} 官方",
    ]
    return [
        Evidence(candidate_id_value, "manual_search_query", query, "manual_followup", "", now_iso(), "0.50")
        for query in queries
    ]


def replace_candidate_id(item: Evidence, candidate_id_value: str) -> Evidence:
    return Evidence(
        candidate_id=candidate_id_value,
        field_name=item.field_name,
        field_value=item.field_value,
        source_type=item.source_type,
        source_url=item.source_url,
        extracted_at=item.extracted_at,
        confidence=item.confidence,
        source_title=item.source_title,
        extracted_text=item.extracted_text,
    )


def merge_fields(base: Dict[str, object], incoming: Dict[str, object]) -> None:
    for key, value in incoming.items():
        if value and not base.get(key):
            base[key] = value
        elif key == "item_types" and value:
            existing = list(base.get(key) or [])
            for item in value:
                if item not in existing:
                    existing.append(item)
            base[key] = existing


def derive_registration_status(start_at: str, end_at: str, today: Optional[datetime] = None) -> str:
    now = today or datetime.now(timezone.utc)
    start = parse_datetime(start_at)
    end = parse_datetime(end_at)
    if start and now < start:
        return "not_started"
    if start and end and start <= now <= end:
        return "open"
    if end and now > end:
        return "closed"
    return "not_started"


def derive_race_status(event_date: str, today: Optional[date] = None) -> str:
    if not event_date:
        return "upcoming"
    current = today or date.today()
    try:
        value = date.fromisoformat(event_date)
    except ValueError:
        return "upcoming"
    if value > current:
        return "upcoming"
    if value == current:
        return "ongoing"
    return "ended"


def normalize_level_label(value: str) -> str:
    text = normalize_space(value)
    if text in {"A", "B", "C"}:
        return f"{text}类"
    return text


def normalize_date_or_datetime(value: str, field: str) -> str:
    return extract_date(value) if field == "lottery_result_date" else normalize_datetime(value)


def normalize_datetime(value: str) -> str:
    date_value = extract_date(value)
    if not date_value:
        return ""
    time_value = normalize_time(value) or "00:00:00"
    return f"{date_value}T{time_value}+08:00"


def normalize_time(value: str) -> str:
    match = re.search(r"(\d{1,2})[:：](\d{2})", value or "")
    if not match:
        return ""
    hour, minute = match.groups()
    return f"{int(hour):02d}:{int(minute):02d}:00"


def parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def clean_short_text(value: str) -> str:
    text = normalize_space(value)
    text = re.split(r"(?:终点|终点位置|领物地点|领物处|装备领取地点|参赛物品领取地点|世界田联|报名时间|比赛时间)[:：]?", text, maxsplit=1)[0]
    return normalize_space(re.sub(r"[。；，、].*$", "", text))
