from pathlib import Path
import csv
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawl.extractors.detail import extract_from_leads
from crawl.models import Lead, now_iso
from crawl.main import filter_leads_by_date
from crawl.normalize.dedupe import dedupe_candidates
from crawl.normalize.filters import is_mvp_race
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
        leads = list(ZuicoolSource(html=html).discover())
        names = [lead.event_name for lead in leads]
        self.assertIn("2026成都马拉松", names)
        self.assertIn("2026金昌半程马拉松", names)
        self.assertNotIn("2026中岳嵩山越野赛", names)
        self.assertNotIn("2026探秘兵马俑线上赛-前世", names)

    def test_sport_china_discovery_filters_list_page(self):
        html = (FIXTURES / "sport_china_race.html").read_text(encoding="utf-8")
        leads = list(SportChinaSource(html=html).discover())
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


if __name__ == "__main__":
    unittest.main()
