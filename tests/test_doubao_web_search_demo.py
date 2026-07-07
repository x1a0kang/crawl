from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawl.demos.doubao_web_search_demo import (
    DemoResult,
    MarathonInput,
    build_ark_payload,
    build_demo_result,
    build_parser,
    build_prompt,
    call_doubao_web_search,
    enrich_with_retries,
    extract_response_text,
    main,
    normalize_event_payload,
    parse_json_object,
    read_inputs,
    write_outputs,
)
from crawl.models import EVENT_FIELDS


class DoubaoWebSearchDemoTest(unittest.TestCase):
    """Tests for the Doubao Web Search standalone demo.

    Author: juruikang
    Date: 2026-07-07
    """

    def test_reads_txt_input_one_event_per_line(self):
        """TXT input should use one non-empty event name per line.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.txt"
            path.write_text("2026蚌埠马拉松\n\n 2026杭州马拉松 \n", encoding="utf-8")
            rows = read_inputs(path)

        self.assertEqual([row.event_name for row in rows], ["2026蚌埠马拉松", "2026杭州马拉松"])

    def test_reads_csv_input_with_named_header(self):
        """CSV input with event_name header should read optional context columns.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.csv"
            path.write_text(
                "event_name,event_date,province,city\n"
                "2026蚌埠马拉松,2026年4月26日,安徽省,蚌埠市\n",
                encoding="utf-8-sig",
            )
            rows = read_inputs(path)

        self.assertEqual(rows[0].event_name, "2026蚌埠马拉松")
        self.assertEqual(rows[0].event_date, "2026-04-26")
        self.assertEqual(rows[0].province, "安徽省")
        self.assertEqual(rows[0].city, "蚌埠市")

    def test_reads_csv_input_skipping_unknown_title_row(self):
        """CSV input without event_name header should skip first row and read first column.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.csv"
            path.write_text("赛事名称\n2026蚌埠马拉松\n2026杭州马拉松\n", encoding="utf-8-sig")
            rows = read_inputs(path)

        self.assertEqual([row.event_name for row in rows], ["2026蚌埠马拉松", "2026杭州马拉松"])

    def test_parser_has_no_limit_argument(self):
        """Demo CLI should process the entire input file without a limit flag.

        Author: juruikang
        Date: 2026-07-07
        """
        options = build_parser().format_help()
        self.assertNotIn("--limit", options)

    def test_payload_uses_sdk_web_search_shape(self):
        """Ark payload should match SDK Responses API web_search shape.

        Author: juruikang
        Date: 2026-07-07
        """
        payload = build_ark_payload("model-id", MarathonInput("2026蚌埠马拉松"))
        self.assertEqual(payload["tools"], [{"type": "web_search", "max_keyword": 3}])
        self.assertEqual(payload["input"][0]["content"], build_prompt(MarathonInput("2026蚌埠马拉松")))
        self.assertEqual(payload["text"], {"format": {"type": "json_object"}})

    def test_call_doubao_web_search_uses_sdk_responses_create(self):
        """Demo should call Ark SDK responses.create with prepared payload.

        Author: juruikang
        Date: 2026-07-07
        """

        class FakeResponses:
            """Fake SDK responses resource.

            Author: juruikang
            Date: 2026-07-07
            """

            def __init__(self):
                """Capture calls for assertions.

                Author: juruikang
                Date: 2026-07-07
                """
                self.kwargs = None

            def create(self, **kwargs):
                """Return a minimal fake response and record kwargs.

                Author: juruikang
                Date: 2026-07-07
                """
                self.kwargs = kwargs
                return {"output_text": "{\"name\":\"2026蚌埠马拉松\"}"}

        class FakeArk:
            """Fake SDK client.

            Author: juruikang
            Date: 2026-07-07
            """

            def __init__(self):
                """Create fake responses resource.

                Author: juruikang
                Date: 2026-07-07
                """
                self.responses = FakeResponses()

        fake = FakeArk()
        response = call_doubao_web_search(fake, "model-id", MarathonInput("2026蚌埠马拉松"))

        self.assertEqual(response["output_text"], "{\"name\":\"2026蚌埠马拉松\"}")
        self.assertEqual(fake.responses.kwargs["model"], "model-id")
        self.assertEqual(fake.responses.kwargs["tools"], [{"type": "web_search", "max_keyword": 3}])

    def test_prompt_contains_strict_no_guess_rules(self):
        """Prompt should include strict no-guess and same-year rules.

        Author: juruikang
        Date: 2026-07-07
        """
        prompt = build_prompt(MarathonInput("2026蚌埠马拉松"))
        self.assertIn("搜索中没有明确获取到的字段禁止猜测", prompt)
        self.assertIn("往年的赛事信息", prompt)
        self.assertIn("直接输出 JSON", prompt)
        self.assertIn("参考导入 JSON 规则", prompt)

    def test_extracts_response_text_from_responses_payload(self):
        """Responses API payload should expose assistant output text.

        Author: juruikang
        Date: 2026-07-07
        """
        payload = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "{\"name\":\"2026蚌埠马拉松\"}"}
                    ]
                }
            ]
        }

        self.assertEqual(extract_response_text(payload), "{\"name\":\"2026蚌埠马拉松\"}")

    def test_extracts_response_text_from_sdk_choice_payload(self):
        """SDK shape response.output.choices[0].message.content should parse.

        Author: juruikang
        Date: 2026-07-07
        """

        class Message:
            """Fake SDK message object.

            Author: juruikang
            Date: 2026-07-07
            """

            content = "{\"name\":\"2026蚌埠马拉松\"}"

        class Choice:
            """Fake SDK choice object.

            Author: juruikang
            Date: 2026-07-07
            """

            message = Message()

        class Output:
            """Fake SDK output object.

            Author: juruikang
            Date: 2026-07-07
            """

            choices = [Choice()]

        class Response:
            """Fake SDK response object.

            Author: juruikang
            Date: 2026-07-07
            """

            output = Output()

        self.assertEqual(extract_response_text(Response()), "{\"name\":\"2026蚌埠马拉松\"}")

    def test_parses_fenced_json_object(self):
        """JSON parsing should tolerate fenced JSON blocks.

        Author: juruikang
        Date: 2026-07-07
        """
        parsed = parse_json_object('```json\n{"name":"2026蚌埠马拉松"}\n```')
        self.assertEqual(parsed["name"], "2026蚌埠马拉松")

    def test_normalizes_event_payload_for_csv(self):
        """Model payload should normalize into current EVENT_FIELDS.

        Author: juruikang
        Date: 2026-07-07
        """
        row = normalize_event_payload(
            MarathonInput("2026蚌埠马拉松", province="安徽省", city="蚌埠市"),
            {
                "name": "2026蚌埠马拉松",
                "province": None,
                "city": "",
                "event_date": "2026年4月26日",
                "item_types": ["full_marathon", "ten_kilometer", "bad_value"],
                "start_time": "7:30",
                "registration_start_at": "2026年3月1日10:00",
                "registration_end_at": "null",
                "status": "published",
            },
        )

        self.assertEqual(set(row), set(EVENT_FIELDS))
        self.assertEqual(row["province"], "安徽省")
        self.assertEqual(row["city"], "蚌埠市")
        self.assertEqual(row["event_date"], "2026-04-26")
        self.assertEqual(row["item_types"], '["full_marathon","ten_km"]')
        self.assertEqual(row["start_time"], "07:30:00")
        self.assertEqual(row["registration_start_at"], "2026-03-01T10:00:00+08:00")
        self.assertEqual(row["registration_end_at"], "")
        self.assertEqual(row["status"], "draft")

    def test_build_demo_result_keeps_evidence_and_confidence(self):
        """Parsed model JSON should keep normalized evidence in JSONL shape.

        Author: juruikang
        Date: 2026-07-07
        """
        result = build_demo_result(
            MarathonInput("2026蚌埠马拉松"),
            {
                "name": "2026蚌埠马拉松",
                "event_date": "2026-04-26",
                "item_types": ["full_marathon"],
                "confidence": 0.876,
                "evidence": [
                    {
                        "field_name": "event_date",
                        "field_value": "2026-04-26",
                        "source_url": "https://example.com",
                        "source_title": "公告",
                        "evidence_text": "比赛日期为2026年4月26日",
                    }
                ],
            },
            "{}",
        )

        self.assertEqual(result.confidence, "0.88")
        self.assertEqual(result.evidence[0]["source_url"], "https://example.com")

    def test_write_outputs_skips_error_rows_in_csv(self):
        """CSV should contain only successful event rows while JSONL keeps errors.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            success = DemoResult(
                input_event_name="2026蚌埠马拉松",
                event={field: "" for field in EVENT_FIELDS},
                evidence=[],
                confidence="0.90",
                raw_response="{}",
            )
            success.event["name"] = "2026蚌埠马拉松"
            success.event["status"] = "draft"
            failed = DemoResult(
                input_event_name="坏数据",
                event=None,
                evidence=[],
                confidence="0",
                raw_response="",
                error="invalid json",
            )

            write_outputs(out, [success, failed])
            with (out / "doubao_events.csv").open("r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            with (out / "doubao_events.jsonl").open("r", encoding="utf-8") as handle:
                jsonl_rows = [json.loads(line) for line in handle]

        self.assertEqual(rows[0]["name"], "2026蚌埠马拉松")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(jsonl_rows), 2)
        self.assertEqual(jsonl_rows[1]["error"], "invalid json")

    def test_main_reports_missing_input_without_traceback(self):
        """Missing input files should return a CLI error instead of a traceback.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--input", str(Path(tmp) / "missing.csv"), "--out", str(Path(tmp) / "out")])

        self.assertEqual(code, 2)

    def test_main_reports_missing_sdk_without_traceback(self):
        """Missing Ark SDK should return a CLI error instead of a traceback.

        Author: juruikang
        Date: 2026-07-07
        """
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "names.csv"
            input_path.write_text("赛事名称\n2026蚌埠马拉松\n", encoding="utf-8")
            with patch(
                "crawl.demos.doubao_web_search_demo.create_ark_client",
                side_effect=RuntimeError("missing sdk"),
            ):
                code = main(["--input", str(input_path), "--out", str(Path(tmp) / "out")])

        self.assertEqual(code, 2)

    def test_sdk_exception_becomes_error_result(self):
        """SDK exceptions should be captured in JSONL result rows.

        Author: juruikang
        Date: 2026-07-07
        """

        class DisconnectingClient:
            """Test client that simulates Ark closing the connection.

            Author: juruikang
            Date: 2026-07-07
            """

            class Responses:
                """Fake responses resource that raises a transport failure.

                Author: juruikang
                Date: 2026-07-07
                """

                def create(self, **kwargs):
                    """Raise the same kind of transport failure the SDK may surface.

                    Author: juruikang
                    Date: 2026-07-07
                    """
                    raise ConnectionError("Remote end closed connection without response")

            responses = Responses()

        result = enrich_with_retries(DisconnectingClient(), "model-id", MarathonInput("2026蚌埠马拉松"), retries=0)

        self.assertIsNone(result.event)
        self.assertIn("Remote end closed connection without response", result.error)


if __name__ == "__main__":
    unittest.main()
