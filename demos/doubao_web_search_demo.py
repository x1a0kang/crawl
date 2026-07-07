from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawl.models import EVENT_FIELDS, pg_array_literal
from crawl.normalize.dates import extract_date
from crawl.normalize.filters import extract_item_types
from crawl.normalize.text import normalize_space


LOGGER = logging.getLogger(__name__)

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_API_KEY = "68bfba1d-95d1-4183-8f83-da63f989fe0b"
ARK_MODEL = "ep-20260701121520-4jhc7"
ALLOWED_ITEM_TYPES = ("full_marathon", "half_marathon", "ten_km")


@dataclass(frozen=True)
class MarathonInput:
    """Input row for one marathon enrichment request.

    Author: juruikang
    Date: 2026-07-07
    """

    event_name: str
    event_date: str = ""
    province: str = ""
    city: str = ""


@dataclass(frozen=True)
class DemoResult:
    """Normalized result for one demo enrichment request.

    Author: juruikang
    Date: 2026-07-07
    """

    input_event_name: str
    event: Optional[Dict[str, str]]
    evidence: List[Dict[str, str]]
    confidence: str
    raw_response: str
    error: str = ""


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for the standalone demo.

    Author: juruikang
    Date: 2026-07-07
    """
    parser = argparse.ArgumentParser(description="Doubao Web Search marathon enrichment demo")
    parser.add_argument("--input", required=True, help="Input CSV/TXT path. CSV needs event_name column.")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Delay between model calls")
    parser.add_argument("--timeout", type=int, default=120, help="HTTP timeout in seconds")
    parser.add_argument("--retries", type=int, default=1, help="Retry count after the first failed request")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Run the standalone Doubao Web Search demo.

    Author: juruikang
    Date: 2026-07-07
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    api_key = ARK_API_KEY.strip()
    model = ARK_MODEL.strip()
    if not api_key:
        LOGGER.error("ARK_API_KEY is required")
        return 2
    if api_key.startswith("请在这里填写"):
        LOGGER.error("please fill ARK_API_KEY in demos/doubao_web_search_demo.py")
        return 2
    if not model:
        LOGGER.error("ARK_MODEL is required")
        return 2
    if model.startswith("请在这里填写"):
        LOGGER.error("please fill ARK_MODEL in demos/doubao_web_search_demo.py")
        return 2

    input_path = Path(args.input)
    if not input_path.exists():
        LOGGER.error("input file not found: %s", input_path)
        return 2

    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = read_inputs(input_path)
    if not inputs:
        LOGGER.error("input file has no event rows: %s", input_path)
        return 2
    try:
        ark_client = create_ark_client(base_url=ARK_BASE_URL, api_key=api_key, timeout=args.timeout)
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        return 2

    results: List[DemoResult] = []
    for index, item in enumerate(inputs, start=1):
        LOGGER.info("processing %s/%s: %s", index, len(inputs), item.event_name)
        result = enrich_with_retries(ark_client, model, item, retries=args.retries)
        results.append(result)
        write_outputs(output_dir, results)
        if args.sleep_seconds > 0 and index < len(inputs):
            time.sleep(args.sleep_seconds)

    LOGGER.info("wrote %s result(s) to %s", len(results), output_dir)
    return 0


def read_inputs(path: Path) -> List[MarathonInput]:
    """Read marathon names from CSV or TXT input.

    Author: juruikang
    Date: 2026-07-07
    """
    if path.suffix.lower() == ".csv":
        rows = read_csv_inputs(path)
    else:
        rows = read_txt_inputs(path)
    return rows


def read_csv_inputs(path: Path) -> List[MarathonInput]:
    """Read CSV rows with event_name and optional context columns.

    Author: juruikang
    Date: 2026-07-07
    """
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return []
    header = [normalize_space(cell) for cell in rows[0]]
    data_rows = rows[1:]
    if "event_name" in header:
        event_name_index = header.index("event_name")
        event_date_index = header.index("event_date") if "event_date" in header else -1
        province_index = header.index("province") if "province" in header else -1
        city_index = header.index("city") if "city" in header else -1
        return [
            MarathonInput(
                event_name=normalize_space(row[event_name_index]) if len(row) > event_name_index else "",
                event_date=normalize_date(row[event_date_index]) if event_date_index >= 0 and len(row) > event_date_index else "",
                province=normalize_space(row[province_index]) if province_index >= 0 and len(row) > province_index else "",
                city=normalize_space(row[city_index]) if city_index >= 0 and len(row) > city_index else "",
            )
            for row in data_rows
            if len(row) > event_name_index and normalize_space(row[event_name_index])
        ]
    return [
        MarathonInput(event_name=normalize_space(row[0]))
        for row in data_rows
        if row and normalize_space(row[0])
    ]


def read_txt_inputs(path: Path) -> List[MarathonInput]:
    """Read TXT input as one event name per non-empty line.

    Author: juruikang
    Date: 2026-07-07
    """
    with path.open("r", encoding="utf-8-sig") as handle:
        return [MarathonInput(normalize_space(line)) for line in handle if normalize_space(line)]


def enrich_with_retries(ark_client: Any, model: str, item: MarathonInput, retries: int = 1) -> DemoResult:
    """Call the model with retry and convert failures into JSONL rows.

    Author: juruikang
    Date: 2026-07-07
    """
    attempts = max(1, int(retries or 0) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            raw_payload = call_doubao_web_search(ark_client, model, item)
            raw_text = serialize_response(raw_payload)
            output_text = extract_response_text(raw_payload)
            parsed = parse_json_object(output_text)
            return build_demo_result(item, parsed, raw_text)
        except Exception as exc:
            last_error = format_request_error(exc)
            LOGGER.error("Doubao enrichment failed for %s on attempt %s/%s: %s", item.event_name, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(1)
    return DemoResult(
        input_event_name=item.event_name,
        event=None,
        evidence=[],
        confidence="0",
        raw_response="",
        error=last_error,
    )


def call_doubao_web_search(ark_client: Any, model: str, item: MarathonInput) -> Any:
    """Call Ark SDK responses.create with Web Search enabled.

    Author: juruikang
    Date: 2026-07-07
    """
    payload = build_ark_payload(model, item)
    LOGGER.info("calling Doubao web search for %s", item.event_name)
    return ark_client.responses.create(**payload)


def create_ark_client(base_url: str, api_key: str, timeout: int) -> Any:
    """Create Volcano Ark SDK client lazily so tests do not need the SDK.

    Author: juruikang
    Date: 2026-07-07
    """
    try:
        from volcenginesdkarkruntime import Ark
    except ImportError as exc:
        raise RuntimeError(
            "missing Ark SDK; install dependencies with "
            "`python3 -m pip install -r requirements.txt`"
        ) from exc
    return Ark(base_url=base_url, api_key=api_key, timeout=timeout)


def format_request_error(exc: BaseException) -> str:
    """Format request and parsing errors for JSONL diagnostics.

    Author: juruikang
    Date: 2026-07-07
    """
    return str(exc)


def build_ark_payload(model: str, item: MarathonInput) -> Dict[str, Any]:
    """Build an Ark Responses API payload with Web Search and JSON schema.

    Author: juruikang
    Date: 2026-07-07
    """
    return {
        "model": model,
        "stream": False,
        "store": False,
        "tools": [{"type": "web_search", "max_keyword": 3}],
        "input": [
            {
                "role": "user",
                "content": build_prompt(item),
            }
        ],
        "text": {
            "format": {
                "type": "json_object",
            }
        },
    }


def build_prompt(item: MarathonInput) -> str:
    """Build the extraction prompt for one marathon event.

    Author: juruikang
    Date: 2026-07-07
    """
    context_parts = [
        f"赛事名称：{item.event_name}",
        f"已知日期：{item.event_date}" if item.event_date else "",
        f"已知省份：{item.province}" if item.province else "",
        f"已知城市：{item.city}" if item.city else "",
    ]
    context = "\n".join(part for part in context_parts if part)
    return f"""
你是马拉松赛事数据采集助手。请使用联网搜索，只基于可查到的网页证据，抽取下面赛事的信息。

{context}

搜索优先级：
1. 赛事官网、组委会公告、官方报名页。
2. 政府、体育局、田协、地方文旅体局公告。
3. 主流报名平台或可信新闻。

规则：
- 只输出符合 schema 的 JSON，不要输出 Markdown，不要解释。
- 直接输出 JSON，禁止输出除 JSON 外的任何内容。
- 搜索中没有明确获取到的字段禁止猜测，值用 null 表示；数组字段找不到时输出空数组。
- 往年的赛事信息如规模、起点、终点、报名费、名额、领物地点等，禁止填充到今年的赛事。
- 只有资料明确说明是当前输入赛事对应年份的信息时，才允许填入该字段。
- 每个非空字段都必须在 evidence 里给出 source_url、source_title、evidence_text。
- item_types 只能使用 full_marathon、half_marathon、ten_km。
- 日期使用 YYYY-MM-DD；时间使用 HH:MM:SS；带时区时间使用 ISO timestamptz。
- status 固定为 draft。

参考导入 JSON 规则：
- event.name、event.province、event.city、event.eventDate 是核心字段；缺少明确证据时不要编造。
- items 每个项目只能是 full_marathon、half_marathon、ten_km。
- 起点和终点属于项目维度；如果只能确认赛事级统一起终点，可填入 start_point、finish_point，并在 evidence 中写明来源。
- 报名开始和截止时间必须来自明确公告，格式化为时间字段；没有可靠来源时输出 null。
- lottery_result_date 只在明确抽签或公布日期时填写。
- organizer、packet_pickup_location、certification_label、level_label 必须有明确来源。
- seriesKey、registeredCount、图片、渠道等不在本 demo schema 中，不要输出。
""".strip()


def serialize_response(payload: Any) -> str:
    """Serialize Ark SDK response objects for JSONL diagnostics.

    Author: juruikang
    Date: 2026-07-07
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)
    if hasattr(payload, "model_dump_json"):
        return payload.model_dump_json()
    if hasattr(payload, "json"):
        return payload.json()
    if hasattr(payload, "model_dump"):
        return json.dumps(payload.model_dump(), ensure_ascii=False)
    return str(payload)


def extract_response_text(payload: Any) -> str:
    """Extract assistant output text from an Ark Responses API payload.

    Author: juruikang
    Date: 2026-07-07
    """
    sdk_choice_text = extract_sdk_choice_text(payload)
    if sdk_choice_text:
        return sdk_choice_text
    if not isinstance(payload, dict):
        try:
            payload = json.loads(serialize_response(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("response does not contain output text")
    for output in payload.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return str(content.get("text"))
    if payload.get("output_text"):
        return str(payload["output_text"])
    raise ValueError("response does not contain output text")


def extract_sdk_choice_text(payload: Any) -> str:
    """Extract content from SDK shape response.output.choices[0].message.content.

    Author: juruikang
    Date: 2026-07-07
    """
    output = getattr(payload, "output", None)
    choices = getattr(output, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content:
            return str(content)
    if isinstance(output, dict):
        choices = output.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if content:
                return str(content)
    return ""


def parse_json_object(text: str) -> Dict[str, Any]:
    """Parse a JSON object from model text, including fenced JSON blocks.

    Author: juruikang
    Date: 2026-07-07
    """
    value = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", value, flags=re.S)
    if fence_match:
        value = fence_match.group(1)
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("model output JSON must be an object")
    return parsed


def build_demo_result(item: MarathonInput, payload: Dict[str, Any], raw_response: str) -> DemoResult:
    """Normalize one parsed model payload into demo outputs.

    Author: juruikang
    Date: 2026-07-07
    """
    event = normalize_event_payload(item, payload)
    evidence = normalize_evidence(payload.get("evidence") or [])
    confidence = normalize_confidence(payload.get("confidence"))
    return DemoResult(
        input_event_name=item.event_name,
        event=event,
        evidence=evidence,
        confidence=confidence,
        raw_response=raw_response,
    )


def normalize_event_payload(item: MarathonInput, payload: Dict[str, Any]) -> Dict[str, str]:
    """Normalize model event fields into the current events.csv shape.

    Author: juruikang
    Date: 2026-07-07
    """
    row: Dict[str, str] = {}
    for field in EVENT_FIELDS:
        row[field] = normalize_field(field, payload.get(field))
    row["name"] = row["name"] or item.event_name
    row["event_date"] = row["event_date"] or item.event_date
    row["province"] = row["province"] or item.province
    row["city"] = row["city"] or item.city
    row["status"] = "draft"
    item_types = normalize_item_types(payload.get("item_types"), f"{row['name']} {payload.get('item_types') or ''}")
    row["item_types"] = pg_array_literal(item_types)
    return row


def normalize_field(field: str, value: Any) -> str:
    """Normalize one model field for CSV output.

    Author: juruikang
    Date: 2026-07-07
    """
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = normalize_space(text)
    if text.lower() in {"null", "none", "unknown", "未知"}:
        return ""
    if field in {"event_date", "lottery_result_date"}:
        return normalize_date(text)
    if field == "start_time":
        return normalize_time_value(text)
    if field in {"registration_start_at", "registration_end_at"}:
        return normalize_timestamptz(text)
    return text


def normalize_item_types(value: Any, fallback_text: str) -> List[str]:
    """Validate item_types and derive fallback values from text.

    Author: juruikang
    Date: 2026-07-07
    """
    raw_values: List[str] = []
    if isinstance(value, list):
        raw_values = [str(item) for item in value]
    elif value:
        raw_values = [str(value)]
    mapped = []
    for raw in raw_values:
        normalized = raw.strip()
        if normalized == "ten_kilometer":
            normalized = "ten_km"
        if normalized in ALLOWED_ITEM_TYPES and normalized not in mapped:
            mapped.append(normalized)
    if mapped:
        return mapped
    return extract_item_types(fallback_text)


def normalize_evidence(value: Any) -> List[Dict[str, str]]:
    """Normalize model evidence list for JSONL output.

    Author: juruikang
    Date: 2026-07-07
    """
    if not isinstance(value, list):
        return []
    evidence: List[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "field_name": normalize_space(item.get("field_name") or ""),
                "field_value": normalize_space(item.get("field_value") or ""),
                "source_url": normalize_space(item.get("source_url") or ""),
                "source_title": normalize_space(item.get("source_title") or ""),
                "evidence_text": normalize_space(item.get("evidence_text") or ""),
            }
        )
    return evidence


def normalize_confidence(value: Any) -> str:
    """Normalize model confidence into a compact string.

    Author: juruikang
    Date: 2026-07-07
    """
    if value is None:
        return "0"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    return f"{max(0.0, min(1.0, number)):.2f}"


def normalize_date(value: str) -> str:
    """Normalize free-form date text to YYYY-MM-DD.

    Author: juruikang
    Date: 2026-07-07
    """
    return extract_date(value)


def normalize_time_value(value: str) -> str:
    """Normalize free-form time text to HH:MM:SS.

    Author: juruikang
    Date: 2026-07-07
    """
    match = re.search(r"(\d{1,2})[:：](\d{2})(?::(\d{2}))?", value or "")
    if not match:
        return ""
    hour, minute, second = match.groups()
    return f"{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"


def normalize_timestamptz(value: str) -> str:
    """Normalize date-time text to an ISO timestamptz string.

    Author: juruikang
    Date: 2026-07-07
    """
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$", value or ""):
        return value
    date_value = extract_date(value)
    if not date_value:
        return ""
    time_value = normalize_time_value(value) or "00:00:00"
    return f"{date_value}T{time_value}+08:00"


def write_outputs(output_dir: Path, results: Iterable[DemoResult]) -> None:
    """Write JSONL and CSV outputs for all results collected so far.

    Author: juruikang
    Date: 2026-07-07
    """
    result_list = list(results)
    write_jsonl(output_dir / "doubao_events.jsonl", result_list)
    write_csv(output_dir / "doubao_events.csv", result_list)


def write_jsonl(path: Path, results: Iterable[DemoResult]) -> None:
    """Write demo JSONL with raw responses and errors.

    Author: juruikang
    Date: 2026-07-07
    """
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            payload = {
                "input_event_name": result.input_event_name,
                "event": result.event,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "raw_response": result.raw_response,
                "error": result.error,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_csv(path: Path, results: Iterable[DemoResult]) -> None:
    """Write successful demo rows as import-oriented CSV.

    Author: juruikang
    Date: 2026-07-07
    """
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for result in results:
            if result.event and not result.error:
                writer.writerow({field: result.event.get(field, "") for field in EVENT_FIELDS})


if __name__ == "__main__":
    raise SystemExit(main())
