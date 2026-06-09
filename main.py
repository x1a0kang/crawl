from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawl.extractors.detail import extract_from_leads
from crawl.models import Lead
from crawl.normalize.dedupe import dedupe_candidates
from crawl.normalize.dates import in_date_range
from crawl.sources import SOURCE_REGISTRY
from crawl.writers import ensure_output_dir, read_leads, write_candidates, write_evidence, write_leads


DEFAULT_SOURCES = "china-marathon,sport-china,zuicool"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline race data collection pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="Discover race leads from configured sources")
    discover.add_argument("--sources", default=DEFAULT_SOURCES, help="Comma-separated source names")
    discover.add_argument("--out", default="crawl/output", help="Output directory")
    discover.add_argument("--manual-seeds", default="seeds.csv", help="CSV path for manual source")
    add_date_args(discover)

    extract = subparsers.add_parser("extract", help="Extract review candidates from leads")
    extract.add_argument("--input", required=True, help="Input leads.csv path")
    extract.add_argument("--out", default="crawl/output", help="Output directory")
    extract.add_argument("--no-fetch", action="store_true", help="Do not fetch detail pages")
    add_date_args(extract)

    all_cmd = subparsers.add_parser("all", help="Run discovery and extraction")
    all_cmd.add_argument("--sources", default=DEFAULT_SOURCES, help="Comma-separated source names")
    all_cmd.add_argument("--out", default="crawl/output", help="Output directory")
    all_cmd.add_argument("--manual-seeds", default="seeds.csv", help="CSV path for manual source")
    all_cmd.add_argument("--no-fetch", action="store_true", help="Do not fetch detail pages")
    add_date_args(all_cmd)

    return parser


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "discover":
        out = ensure_output_dir(args.out)
        leads = discover_sources(args.sources, args.manual_seeds)
        leads = filter_leads_by_date(leads, args.date_from, args.date_to)
        write_leads(out / "leads.csv", leads)
        print(f"wrote {len(leads)} leads to {out / 'leads.csv'}")
        return 0
    if args.command == "extract":
        out = ensure_output_dir(args.out)
        leads = read_leads(args.input)
        leads = filter_leads_by_date(leads, args.date_from, args.date_to)
        candidates, evidence = extract_from_leads(leads, fetch_details=not args.no_fetch)
        candidates = dedupe_candidates(candidates)
        write_candidates(out / "candidates.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        print(f"wrote {len(candidates)} candidates and {len(evidence)} evidence rows to {out}")
        return 0
    if args.command == "all":
        out = ensure_output_dir(args.out)
        leads = discover_sources(args.sources, args.manual_seeds)
        leads = filter_leads_by_date(leads, args.date_from, args.date_to)
        write_leads(out / "leads.csv", leads)
        candidates, evidence = extract_from_leads(leads, fetch_details=not args.no_fetch)
        candidates = dedupe_candidates(candidates)
        write_candidates(out / "candidates.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        print(f"wrote {len(leads)} leads, {len(candidates)} candidates and {len(evidence)} evidence rows to {out}")
        return 0
    parser.print_help()
    return 2


def discover_sources(source_names: str, manual_seeds: str) -> List[Lead]:
    leads: List[Lead] = []
    for source_name in [item.strip() for item in source_names.split(",") if item.strip()]:
        source_class = SOURCE_REGISTRY.get(source_name)
        if source_class is None:
            raise SystemExit(f"unknown source: {source_name}")
        if source_name == "manual":
            source = source_class(manual_seeds)
        else:
            source = source_class()
        try:
            leads.extend(list(source.discover()))
        except Exception as exc:
            print(f"warning: source {source_name} failed: {exc}", file=sys.stderr)
    return dedupe_leads(leads)


def add_date_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date-from", default="", help="Inclusive event date lower bound, YYYY-MM-DD")
    parser.add_argument("--date-to", default="", help="Inclusive event date upper bound, YYYY-MM-DD")


def filter_leads_by_date(leads: Iterable[Lead], date_from: str = "", date_to: str = "") -> List[Lead]:
    if not date_from and not date_to:
        return list(leads)
    return [lead for lead in leads if in_date_range(lead.event_date, date_from, date_to)]


def dedupe_leads(leads: Iterable[Lead]) -> List[Lead]:
    seen = set()
    result: List[Lead] = []
    for lead in leads:
        key = (lead.source_name, lead.source_url, lead.event_name, lead.event_date)
        if key in seen:
            continue
        seen.add(key)
        result.append(lead)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
