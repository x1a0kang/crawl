from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawl.extractors.detail import extract_from_leads
from crawl.main import (
    build_context,
    filter_leads_by_date,
    resolve_date_window,
)
from crawl.models import (
    DiscoverContext,
    Lead,
    default_last_years_window as model_default_window,
    now_iso,
)
from crawl.normalize.dedupe import dedupe_candidates
from crawl.normalize.filters import is_mvp_race
from crawl.sources.china_marathon import ChinaMarathonSource
from crawl.sources.sport_china import SportChinaSource
from crawl.sources.zuicool import ZuicoolSource
from crawl.writers import write_candidates, write_evidence, write_leads


FIXTURES = Path(__file__).parent / "fixtures"


class PipelineTest(unittest.TestCase):
    def test_filter_keeps_marathon_and_excludes_non_mvp(self):
        self.assertTrue(is_mvp_race("2026成都马拉松", "全马"))
        self.assertTrue(is_mvp_race("2026金昌半程马拉松", "半马"))
        self.assertFalse(is_mvp_race("2026中岳嵩山越野赛", ""))
        self.assertFalse(is_mvp_race("2026长沙世茂环球金融中心垂直马拉松赛", "马拉松"))
        self.assertFalse(is_mvp_race("2026探秘兵马俑线上赛-前世", ""))

    def test_zuicool_discovery_filters_list_page(self):
        html = (FIXTURES / "zuicool_home.html").read_text(encoding="utf-8")
        leads = list(
            ZuicoolSource(
                html_by_url=[("https://zuicool.com/", html)],
            ).discover()
        )
        names = [lead.event_name for lead in leads]
        self.assertIn("2026成都马拉松", names)
        self.assertIn("2026金昌半程马拉松", names)
        self.assertNotIn("2026中岳嵩山越野赛", names)
        self.assertNotIn("2026探秘兵马俑线上赛-前世", names)

    def test_sport_china_discovery_filters_list_page(self):
        page1 = (FIXTURES / "sport_china_race_page1.json").read_text(encoding="utf-8")
        leads = list(SportChinaSource(json_by_page=[page1]).discover())
        names = [lead.event_name for lead in leads]
        self.assertEqual(len(names), 2)
        self.assertTrue(any("塔城半程马拉松" in name for name in names))
        self.assertTrue(any("贵阳马拉松" in name for name in names))
        self.assertTrue(any(lead.event_date == "2026-06-21" for lead in leads))

    def test_filter_leads_by_date_requires_known_date(self):
        leads = [
            Lead("l1", "manual", "u1", "a", "2026成都马拉松", "2026-01-01", "", "", "全马", now_iso(), "h1"),
            Lead("l2", "manual", "u2", "b", "2026成都马拉松", "2026-06-10", "", "", "全马", now_iso(), "h2"),
            Lead("l3", "manual", "u3", "c", "2026成都马拉松", "", "", "", "全马", now_iso(), "h3"),
        ]
        filtered = filter_leads_by_date(leads, "2026-01-01", "2026-06-09")
        self.assertEqual([lead.lead_id for lead in filtered], ["l1"])

    def test_extract_and_dedupe_candidates(self):
        lead = Lead(
            lead_id="l1",
            source_name="zuicool",
            source_url="https://zuicool.com/event/1",
            raw_title="2026成都马拉松",
            event_name="2026成都马拉松",
            event_date="2026-10-25",
            province="四川",
            city="成都",
            event_items="全马",
            discovered_at=now_iso(),
            raw_hash="abc",
        )
        candidates, evidence = extract_from_leads([lead, lead], fetch_details=False)
        deduped = dedupe_candidates(candidates)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].review_status, "pending_review")
        self.assertTrue(any(item.field_name == "manual_search_query" for item in evidence))

    def test_output_files_are_written(self):
        lead = Lead(
            lead_id="l1",
            source_name="manual",
            source_url="https://example.com",
            raw_title="2026南京仙林半程马拉松",
            event_name="2026南京仙林半程马拉松",
            event_date="2026-04-12",
            province="江苏",
            city="南京",
            event_items="半马",
            discovered_at=now_iso(),
            raw_hash="abc",
        )
        candidates, evidence = extract_from_leads([lead], fetch_details=False)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_leads(out / "leads.csv", [lead])
            write_candidates(out / "candidates.csv", candidates)
            write_evidence(out / "evidence.jsonl", evidence)
            with (out / "leads.csv").open("r", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["event_name"], "2026南京仙林半程马拉松")
            with (out / "evidence.jsonl").open("r", encoding="utf-8") as handle:
                first = json.loads(handle.readline())
            self.assertIn("candidate_id", first)


class DiscoverContextTest(unittest.TestCase):
    def test_default_last_years_window_today_is_2026_06_09(self):
        start, end = model_default_window(3, today=date(2026, 6, 9))
        self.assertEqual(start, "2023-06-09")
        self.assertEqual(end, "2026-06-09")

    def test_resolve_date_window_explicit_wins(self):
        args = _Args(date_from="2026-01-01", date_to="2026-06-09", last_years=5)
        self.assertEqual(resolve_date_window(args), ("2026-01-01", "2026-06-09"))

    def test_resolve_date_window_falls_back_to_last_years(self):
        args = _Args(date_from="", date_to="", last_years=0)
        start, end = resolve_date_window(args)
        # Defaults to the last 3 years ending today, so start == end - 3y.
        self.assertEqual(start, model_default_window(3)[0])
        self.assertEqual(end, model_default_window(3)[1])

    def test_build_context_propagates_max_pages(self):
        ctx = build_context(_Args(date_from="", date_to="", last_years=0, max_pages=7))
        self.assertEqual(ctx.max_pages, 7)


class ChinaMarathonSourceTest(unittest.TestCase):
    def test_parses_page1_table_and_filters_10km(self):
        page1 = (FIXTURES / "china_marathon_race_page1.html").read_text(encoding="utf-8")
        leads = list(
            ChinaMarathonSource(html_by_page=[page1]).discover(
                DiscoverContext(date_from="2026-04-01", date_to="2026-12-31", max_pages=10)
            )
        )
        names = [lead.event_name for lead in leads]
        self.assertIn("2026弥勒半程马拉松", names)
        self.assertIn("2026长春马拉松", names)
        self.assertIn("2026蚌埠马拉松", names)
        # 10 公里赛事应被过滤
        self.assertFalse(any("10公里" in name for name in names))
        # 解析到日期与城市
        mile = next(lead for lead in leads if lead.event_name == "2026弥勒半程马拉松")
        self.assertEqual(mile.event_date, "2026-05-25")
        self.assertIn("云南", mile.province)
        self.assertIn("弥勒", mile.city)

    def test_pagination_stops_when_page_is_past_date_from(self):
        page1 = (FIXTURES / "china_marathon_race_page1.html").read_text(encoding="utf-8")
        page2 = (FIXTURES / "china_marathon_race_page2.html").read_text(encoding="utf-8")
        leads = list(
            ChinaMarathonSource(html_by_page=[page1, page2]).discover(
                DiscoverContext(date_from="2026-04-01", date_to="2026-12-31", max_pages=10)
            )
        )
        # 2023 武汉马拉松 早于 2026-04-01，不应被收录
        self.assertFalse(any("武汉" in lead.event_name for lead in leads))

    def test_no_fetcher_warns_and_returns_empty(self):
        context = DiscoverContext(rendered_fetcher=None)
        leads = list(ChinaMarathonSource().discover(context))
        self.assertEqual(leads, [])
        self.assertTrue(any("rendered" in msg for msg in context.warnings))


class SportChinaSourceTest(unittest.TestCase):
    def test_parses_paginated_json_and_builds_detail_url(self):
        page1 = (FIXTURES / "sport_china_race_page1.json").read_text(encoding="utf-8")
        page7 = (FIXTURES / "sport_china_race_page7.json").read_text(encoding="utf-8")
        leads = list(
            SportChinaSource(json_by_page=[page1, page7]).discover(
                DiscoverContext(date_from="2026-01-01", date_to="2026-12-31", max_pages=10)
            )
        )
        urls = {lead.source_url for lead in leads}
        # raceId=956 应当生成 detail URL
        self.assertIn("https://app.sport-china.cn/race/#/offline/detail/956", urls)
        self.assertIn("https://app.sport-china.cn/race/#/offline/detail/720", urls)
        # 越野赛被过滤
        names = [lead.event_name for lead in leads]
        self.assertFalse(any("越野" in name for name in names))
        # 提取的日期
        mile = next(lead for lead in leads if "塔城" in lead.event_name)
        self.assertEqual(mile.event_date, "2026-06-21")

    def test_stops_when_date_is_past_window(self):
        # 使用 date_from=2027 后，没有任何赛事早于该日期，应当立刻停止
        page1 = (FIXTURES / "sport_china_race_page1.json").read_text(encoding="utf-8")
        leads = list(
            SportChinaSource(json_by_page=[page1, page1, page1]).discover(
                DiscoverContext(date_from="2027-01-01", date_to="2027-12-31", max_pages=10)
            )
        )
        self.assertEqual(leads, [])


class ZuicoolSourceTest(unittest.TestCase):
    def test_dedupes_across_entries(self):
        run_page = (FIXTURES / "zuicool_events_type_run_page2.html").read_text(encoding="utf-8")
        newreg_page = (FIXTURES / "zuicool_events_newreg_page2.html").read_text(encoding="utf-8")
        source = ZuicoolSource(
            html_by_url=[
                ("https://zuicool.com/events?type=run&page=2&per-page=100", run_page),
                ("https://zuicool.com/events/newreg?page=2&per-page=100", newreg_page),
            ]
        )
        leads = list(
            source.discover(DiscoverContext(date_from="2026-01-01", date_to="2026-12-31", max_pages=10))
        )
        urls = [lead.source_url for lead in leads]
        # 重复赛事跨入口只生成一个 lead
        self.assertEqual(urls.count("https://zuicool.com/event/67025"), 1)
        names = [lead.event_name for lead in leads]
        self.assertIn("2026成都马拉松", names)
        self.assertIn("2026贵阳马拉松", names)
        self.assertIn("2026南京仙林半程马拉松", names)
        # 越野赛与线上赛被过滤
        self.assertFalse(any("越野" in name for name in names))
        self.assertFalse(any("线上" in name for name in names))

    def test_unreachable_reg_entry_only_warns(self):
        source = ZuicoolSource(
            html_by_url=[
                ("https://zuicool.com/events/reg?page=1&per-page=100", ""),  # 模拟 EOF
                ("https://zuicool.com/events?type=run&page=1&per-page=100", (FIXTURES / "zuicool_events_type_run_page2.html").read_text(encoding="utf-8")),
            ]
        )
        context = DiscoverContext(date_from="2026-01-01", date_to="2026-12-31", max_pages=10)
        leads = list(source.discover(context))
        # 第二个入口仍然产生 lead
        self.assertTrue(any(lead.event_name == "2026成都马拉松" for lead in leads))


def _Args(**kwargs):
    """Tiny namespace stub so we can exercise resolve_date_window / build_context."""
    from argparse import Namespace

    defaults = {
        "date_from": "",
        "date_to": "",
        "last_years": 0,
        "max_pages": 120,
        "rendered_fetcher": "auto",
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


if __name__ == "__main__":
    unittest.main()
