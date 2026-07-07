from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional
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

ProgressCallback = Callable[[int, int, Lead], None]
WarningCallback = Callable[[str], None]


@dataclass
class EventBuild:
    """Mutable build state for one importable event row.

    Author: juruikang
    Date: 2026-06-12
    """

    fields: Dict[str, object]
    evidence: List[Evidence]


def extract_from_leads(
    leads: Iterable[Lead],
    progress: Optional[ProgressCallback] = None,
    warn: Optional[WarningCallback] = None,
) -> tuple[List[EventCandidate], List[Evidence]]:
    """Build events from leads using only China Marathon official detail API.

    Author: juruikang
    Date: 2026-06-12
    """
    lead_list = list(leads)
    candidates: List[EventCandidate] = []
    evidence: List[Evidence] = []
    total = len(lead_list)
    for index, lead in enumerate(lead_list, start=1):
        if not is_mvp_race(lead.event_name, lead.event_items):
            continue
        if progress is not None:
            progress(index, total, lead)

        # Step 1: create a minimal event row from the official list lead.
        build = build_event_from_lead(lead)
        # Step 2: enrich only with the China Marathon searchById API.
        if lead.source_name == "china-marathon":
            try:
                payload = fetch_china_marathon_detail_payload(lead)
                official_fields = china_marathon_detail_fields(payload, lead)
                merge_fields(build.fields, official_fields)
                build.evidence.extend(
                    build_field_evidence(
                        "",
                        official_fields,
                        "official_detail",
                        lead.source_url,
                        source_title=lead.event_name,
                        extracted_text=china_marathon_detail_text(payload),
                        confidence="0.85",
                    )
                )
            except Exception as exc:
                if warn is not None:
                    warn(f"detail fetch failed for {lead.source_name} {lead.event_name}: {exc}")

        # Step 3: derive stable ids after official detail has had a chance to
        # override name/date/city.
        cid = candidate_id(
            normalize_event_name(str(build.fields.get("name") or lead.event_name)),
            str(build.fields.get("event_date") or lead.event_date),
            str(build.fields.get("city") or lead.city),
        )
        build.evidence = [replace_candidate_id(item, cid) for item in build.evidence]

        # Step 4: normalize the final CSV row and evidence records.
        candidate = event_candidate_from_fields(cid, lead.lead_id, build.fields)
        candidates.append(candidate)
        evidence.extend(build.evidence)
        evidence.extend(build_candidate_status_evidence(candidate))
    return candidates, evidence


def build_event_from_lead(lead: Lead) -> EventBuild:
    """Build the base event row from a lead row.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Fetch one China Marathon official detail payload by internal race id.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Fetch and flatten one China Marathon detail payload for evidence text.

    Author: juruikang
    Date: 2026-06-12
    """
    return china_marathon_detail_text(fetch_china_marathon_detail_payload(lead))


def extract_china_marathon_race_id(url: str) -> str:
    """Extract the China Marathon race id from an internal source reference.

    Author: juruikang
    Date: 2026-06-12
    """
    match = re.search(r"^china-marathon:race_id=([^;]+)(?:;|$)", url or "")
    return match.group(1) if match else ""


def china_marathon_detail_fields(payload: object, lead: Lead) -> Dict[str, object]:
    """Map official detail payload fields to event CSV fields.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Return the ``ssdetails`` object from the official detail response.

    Author: juruikang
    Date: 2026-06-12
    """
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    detail = data.get("ssdetails")
    return detail if isinstance(detail, dict) else {}


def china_marathon_detail_text(payload: object) -> str:
    """Flatten official detail fields into compact evidence text.

    Author: juruikang
    Date: 2026-06-12
    """
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


def event_candidate_from_fields(candidate_id_value: str, lead_id: str, fields: Dict[str, object]) -> EventCandidate:
    """Normalize build fields into an importable event candidate.

    Author: juruikang
    Date: 2026-06-12
    """
    event_date = str(fields.get("event_date") or "")
    registration_start = str(fields.get("registration_start_at") or "")
    registration_end = str(fields.get("registration_end_at") or "")
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
    """Build field-level evidence rows for non-empty values.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Build evidence rows for the import publication status.

    Author: juruikang
    Date: 2026-06-23
    """
    fields = {
        "status": candidate.status,
    }
    return build_field_evidence(
        candidate.candidate_id,
        fields,
        "derived",
        "",
        source_title="pipeline import status",
        extracted_text="status derived from pipeline defaults",
        confidence="0.70",
    )


def replace_candidate_id(item: Evidence, candidate_id_value: str) -> Evidence:
    """Replace placeholder candidate ids after final id derivation.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Merge official detail fields into the base lead fields.

    Author: juruikang
    Date: 2026-06-12
    """
    for key, value in incoming.items():
        if value and not base.get(key):
            base[key] = value
        elif key == "item_types" and value:
            existing = list(base.get(key) or [])
            for item in value:
                if item not in existing:
                    existing.append(item)
            base[key] = existing


def normalize_level_label(value: str) -> str:
    """Clean China Marathon race grade labels.

    Author: juruikang
    Date: 2026-06-12
    """
    text = normalize_space(value)
    # 去掉 "属地办赛" 等描述后缀，兼容以下真实形态：
    #   "C 属地办赛"      （半角空格）
    #   "C（属地办赛）"   （全角左括号，无空格）
    #   "C(属地办赛)"     （半角括号）
    cleaned = re.sub(r"[\s（(]*属地办赛.*$", "", text)
    if cleaned in {"A", "B", "C"}:
        return cleaned
    return cleaned or text


def normalize_datetime(value: str) -> str:
    """Normalize a China-local date or date-time string to ISO timestamptz.

    Author: juruikang
    Date: 2026-06-12
    """
    date_value = extract_date(value)
    if not date_value:
        return ""
    time_value = normalize_time(value) or "00:00:00"
    return f"{date_value}T{time_value}+08:00"


def normalize_time(value: str) -> str:
    """Normalize HH:MM strings to HH:MM:SS.

    Author: juruikang
    Date: 2026-06-12
    """
    match = re.search(r"(\d{1,2})[:：](\d{2})", value or "")
    if not match:
        return ""
    hour, minute = match.groups()
    return f"{int(hour):02d}:{int(minute):02d}:00"


def parse_datetime(value: str) -> Optional[datetime]:
    """Parse ISO datetime strings used by event candidates.

    Author: juruikang
    Date: 2026-06-12
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
