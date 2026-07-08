"""Complete marathon event import JSON with Doubao web search.

Author: juruikang
Date: 2026-07-07
"""

import argparse
import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path

try:
    from volcenginesdkarkruntime import Ark
except ModuleNotFoundError as import_error:
    Ark = None
    ARK_IMPORT_ERROR = import_error
else:
    ARK_IMPORT_ERROR = None


MODEL_NAME = "doubao-seed-2-1-pro-260628"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
API_KEY = "68bfba1d-95d1-4183-8f83-da63f989fe0b"
REQUEST_TIMEOUT_SECONDS = 300
REQUEST_MAX_RETRIES = 0
REQUIRED_COLUMNS = {"name", "event_date", "province", "city", "district"}
STRICT_PROMPT_RULE = (
    "搜索中没有明确获取到的字段禁止猜测，值用null表示，往年的赛事信息如规模，"
    "不是同一年的起终点等信息禁止填充到今年的赛事"
    "赛事信息中的所有内容绝对正确，必须填充到输出的对应字段中"
    "直接输出json，禁止输出除 json 外的任何内容"
)


def parse_args():
    """Parse command line arguments for input CSV and output JSON paths."""
    parser = argparse.ArgumentParser(
        description="Complete event import JSON from a CSV file with Doubao web search."
    )
    parser.add_argument("input_csv", help="CSV file path, such as demos/events_little.csv")
    parser.add_argument("output_json", help="Output JSON file path")
    return parser.parse_args()


def configure_logging():
    """Configure process logging without debug-level output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def create_client():
    """Create an Ark client from the ARK_API_KEY environment variable."""
    if Ark is None:
        raise RuntimeError("volcenginesdkarkruntime is required") from ARK_IMPORT_ERROR
    logging.info(
        "Creating Ark client with timeout=%s seconds and max_retries=%s",
        REQUEST_TIMEOUT_SECONDS,
        REQUEST_MAX_RETRIES,
    )
    return Ark(
        base_url=ARK_BASE_URL,
        api_key=API_KEY,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=REQUEST_MAX_RETRIES,
    )


def normalize_event_date(date_text):
    """Normalize a CSV event date to yyyy-MM-dd when possible."""
    cleaned_date = (date_text or "").strip()
    for date_format in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned_date, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return cleaned_date


def read_events(input_csv):
    """Read CSV rows and validate that required event columns exist."""
    with open(input_csv, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("CSV header is required")

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV is missing required columns: {missing_text}")

        events = []
        for row_index, row in enumerate(reader, start=2):
            # Keep only the deterministic fields used to identify the event.
            raw_item_types = (row.get("item_types") or "").strip()
            if raw_item_types:
                try:
                    item_types = json.loads(raw_item_types)
                except json.JSONDecodeError:
                    item_types = None
            else:
                item_types = None

            event = {
                "rowNumber": row_index,
                "name": (row.get("name") or "").strip(),
                "eventDate": normalize_event_date(row.get("event_date")),
                "province": (row.get("province") or "").strip(),
                "city": (row.get("city") or "").strip(),
                "district": (row.get("district") or "").strip() or None,
                "itemTypes": item_types,
                "levelLabel": (row.get("level_label") or "").strip() or None,
                "organizer": (row.get("organizer") or "").strip() or None,
            }
            events.append(event)

    return events


def build_prompt(event):
    """Build the model prompt for one event according to import JSON rules."""
    event_context = json.dumps(event, ensure_ascii=False, indent=2)
    return f"""
你是马拉松赛事数据整理助手。请根据下面给出的赛事信息，联网搜索该赛事今年对应届次的公开信息，并输出一个可用于赛事导入的 JSON 对象。
联网搜索的关键词必须包括：赛事名称;官宣;定档;报名;比赛线路;开跑;malasong5。

赛事信息：
{event_context}

必须遵守：
{STRICT_PROMPT_RULE}

输出 JSON 结构要求：
- 顶层必须是一个对象，包含 event 和 items 两个字段，不要输出数组。

event 字段要求：
- event.name、event.province、event.city、event.district、event.eventDate 必须使用赛事信息中给定的值，eventDate 格式为 yyyy-MM-dd。
- event.levelLabel、event.organizer：若赛事信息中已给出，则必须直接使用该值，不要自己编造；仅当赛事信息中为 null 时才通过搜索补全，levelLabel 只能是 A、B、C 或 null。
- event.startTime 使用 HH:mm:ss 或 null。
- event.registrationStartAt 和 event.registrationEndAt 使用 yyyy-MM-dd HH:mm:ss 或 null。
- event.registrationMode 只能是 direct（直报）、lottery（抽签）或 null。
- event.lotteryResultDate 使用 yyyy-MM-dd 或 null，仅抽签赛事建议填写。
- event.certificationLabel 只能是 标牌、精英标、金标、白金标 或 null。
- event.organizer 是主办方，无明确来源时为 null。
- event.registrationChannel 如能确认，格式为 渠道类型-渠道名称，多个渠道用英文逗号分隔，例如：公众号-上马网,小程序-汇赛通,APP-上马网,官网-上马网；渠道只能是：官网，小程序，公众号，APP，禁止出现其他渠道；不能确认时则为 null。
- event.packetPickupLocation 是赛事级统一领物地点，无明确来源时使用 null。
- event.description 是赛事简介，无明确来源时使用 null。
- event.seriesKey 尽量生成稳定英文小写下划线标识（例如 shanghai_marathon），用于关联同一赛事不同年份；不能确认同一赛事系列时为 null。
- event.status 固定为 published。

items 字段要求（每个赛事至少一个项目）：
- 若赛事信息中的 itemTypes 非空，则 items 必须与 itemTypes 中的项目类型一一对应，不要增加或减少；每个 item 的 itemType 只能是 full_marathon（全马 42.195km）、half_marathon（半马 21.0975km）、ten_km（10km）。
- 起点 startPoint（项目起点）和终点 finishPoint（项目终点）必须放在 items[] 中，不要放在 event 中；建议尽量填写，无明确来源时为 null。
- distanceKm：项目距离（单位 km），全马 42.195、半马 21.0975、十公里 10，不能为空。
- feeAmount：报名费（单位currency），数字类型；无明确来源时使用 null。
- currency：币种，国内赛事默认填 CNY；无明确来源时使用 null。
- quotaCount：项目规模，即报名人数名额，整数类型；无明确来源时使用 null。
- registeredCount：已报名人数，整数类型；没有可靠来源时禁止生成该字段。
""".strip()


def call_model(client, prompt):
    """Call Doubao Responses API with web search enabled."""
    return client.responses.create(
        model=MODEL_NAME,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                ],
            }
        ],
        tools=[
            {
                "type": "web_search",
                "max_keyword": 10,
            }
        ]
    )


def get_value(obj, key):
    """Read a field from either a dict-like object or an SDK object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def to_plain_data(value):
    """Convert SDK response objects into JSON-serializable plain data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            return model_dump()

    value_dict = getattr(value, "__dict__", None)
    if isinstance(value_dict, dict):
        return {
            key: to_plain_data(item)
            for key, item in value_dict.items()
            if not key.startswith("_")
        }

    return str(value)


def build_process_info(event, response, elapsed_seconds):
    """Build process information from a completed model response."""
    output_items = get_value(response, "output") or []
    reasoning_items = []
    web_search_items = []
    citation_items = []

    for output_item in output_items:
        item_type = get_value(output_item, "type")
        if item_type == "reasoning":
            reasoning_items.append(to_plain_data(output_item))
            continue
        if item_type == "web_search_call":
            web_search_items.append(to_plain_data(output_item))
            continue
        if item_type != "message":
            continue

        # Keep source citations attached to the final output text.
        for content_item in get_value(output_item, "content") or []:
            for annotation in get_value(content_item, "annotations") or []:
                citation_items.append(to_plain_data(annotation))

    return {
        "rowNumber": event["rowNumber"],
        "name": event["name"],
        "elapsedSeconds": elapsed_seconds,
        "responseId": get_value(response, "id"),
        "status": get_value(response, "status"),
        "model": get_value(response, "model"),
        "usage": to_plain_data(get_value(response, "usage")),
        "reasoning": reasoning_items,
        "webSearchCalls": web_search_items,
        "citations": citation_items,
    }


def extract_response_text(response):
    """Extract assistant text from common Responses API SDK shapes."""
    output_text = get_value(response, "output_text")
    if output_text:
        return output_text

    output_items = get_value(response, "output") or []
    texts = []
    for item in output_items:
        item_text = get_value(item, "text")
        if item_text:
            texts.append(item_text)
            continue

        content_items = get_value(item, "content") or []
        if isinstance(content_items, str):
            texts.append(content_items)
            continue

        for content_item in content_items:
            content_text = get_value(content_item, "text")
            if content_text:
                texts.append(content_text)

    return "\n".join(texts).strip()


def parse_model_json(response_text):
    """Parse model output as strict JSON."""
    cleaned_text = (response_text or "").strip()
    if not cleaned_text:
        raise ValueError("model returned empty text")
    return json.loads(cleaned_text)


def build_failure_result(event, error, raw_response=None):
    """Build a per-row failure object while preserving the source event."""
    failure = {
        "error": str(error),
        "source": event,
    }
    if raw_response:
        failure["rawResponse"] = raw_response
    return failure


def get_process_info_path(output_json):
    """Build the sidecar process-info JSONL path from the output JSON path."""
    output_path = Path(output_json)
    return output_path.with_name(f"{output_path.stem}_process.jsonl")


def open_process_info_writer(output_json):
    """Open the process-info JSONL sidecar file."""
    process_info_path = get_process_info_path(output_json)
    if process_info_path.parent and process_info_path.parent != Path("."):
        process_info_path.parent.mkdir(parents=True, exist_ok=True)

    return open(process_info_path, "w", encoding="utf-8")


def append_process_info(process_info_file, process_info):
    """Append one model response process-info record as JSONL."""
    json.dump(process_info, process_info_file, ensure_ascii=False)
    process_info_file.write("\n")
    process_info_file.flush()


def process_event(client, event, process_info_file=None):
    """Process one event row through prompt generation, model call, and JSON parsing."""
    logging.info("Processing row %s: %s", event["rowNumber"], event["name"])
    prompt = build_prompt(event)
    logging.info(
        "Prompt for row %s (%s):\n%s",
        event["rowNumber"],
        event["name"],
        prompt,
    )

    try:
        # Call the model once for this CSV row.
        request_started_at = datetime.now()
        response = call_model(client, prompt)
        elapsed_seconds = (datetime.now() - request_started_at).total_seconds()
        logging.info(
            "Model request for row %s completed in %.3f seconds",
            event["rowNumber"],
            elapsed_seconds,
        )
        if process_info_file:
            append_process_info(process_info_file, build_process_info(event, response, elapsed_seconds))
            logging.info(
                "Appended row %s process info",
                event["rowNumber"],
            )
        response_text = extract_response_text(response)
        result = parse_model_json(response_text)
        logging.info("Processed row %s successfully", event["rowNumber"])
        return result
    except json.JSONDecodeError as exc:
        logging.error("JSON parse failed at row %s: %s", event["rowNumber"], exc)
        return build_failure_result(event, f"json_parse_failed: {exc}", response_text)
    except Exception as exc:
        logging.error("Processing failed at row %s: %s", event["rowNumber"], exc)
        return build_failure_result(event, exc)


def open_results_writer(output_json):
    """Open and initialize the JSON array output file."""
    output_path = Path(output_json)
    if output_path.parent and output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)

    json_file = open(output_path, "w", encoding="utf-8")
    json_file.write("[\n")
    json_file.flush()
    return json_file


def append_result(json_file, result, is_first):
    """Append one completed result to the JSON array output file."""
    if not is_first:
        json_file.write(",\n")

    json.dump(result, json_file, ensure_ascii=False, indent=2)
    json_file.flush()


def close_results_writer(json_file):
    """Close the JSON array output file with its ending bracket."""
    json_file.write("\n]\n")
    json_file.flush()
    json_file.close()


def main():
    """Run the CSV to event import JSON completion workflow."""
    configure_logging()
    args = parse_args()

    logging.info("Reading CSV: %s", args.input_csv)
    events = read_events(args.input_csv)
    logging.info("Loaded %s event rows", len(events))

    client = create_client()
    json_file = open_results_writer(args.output_json)
    process_info_file = open_process_info_writer(args.output_json)
    process_info_path = get_process_info_path(args.output_json)
    logging.info("Writing process info to %s", process_info_path)
    written_count = 0
    try:
        for event in events:
            # Continue after per-row failures so every CSV row is attempted.
            result = process_event(client, event, process_info_file)
            append_result(json_file, result, written_count == 0)
            written_count += 1
            logging.info(
                "Appended row %s result to %s",
                event["rowNumber"],
                args.output_json,
            )
    finally:
        close_results_writer(json_file)
        process_info_file.close()

    logging.info("Wrote %s results to %s", written_count, args.output_json)
    logging.info("Wrote process info to %s", process_info_path)


if __name__ == "__main__":
    main()
