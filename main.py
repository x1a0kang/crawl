from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawl.extractors.detail import extract_from_leads
from crawl.models import DiscoverContext, Lead, default_last_years_window
from crawl.normalize.dedupe import dedupe_candidates
from crawl.normalize.dates import in_date_range
from crawl.rendered import build_fetcher
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
    add_discovery_args(discover)

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
    add_discovery_args(all_cmd)

    return parser


def add_date_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date-from", default="", help="Inclusive event date lower bound, YYYY-MM-DD")
    parser.add_argument("--date-to", default="", help="Inclusive event date upper bound, YYYY-MM-DD")
    parser.add_argument(
        "--last-years",
        type=int,
        default=0,
        help=(
            "When --date-from/--date-to are not provided, build a window that "
            "covers the last N years ending today (default: 3 when omitted and "
            "neither explicit date flag is set)."
        ),
    )


def add_discovery_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-pages",
        type=int,
        default=120,
        help="Maximum number of paginated requests each source may issue (default: 120)",
    )
    parser.add_argument(
        "--rendered-fetcher",
        default="auto",
        choices=["auto", "firecrawl", "none"],
        help=(
            "Rendered (JS-aware) fetcher for sites that need it. "
            "'auto' uses the local firecrawl CLI when present, 'none' disables it."
        ),
    )


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    context = build_context(args)

    if args.command == "discover":
        out = ensure_output_dir(args.out)
        leads, warnings = discover_sources(args.sources, args.manual_seeds, context)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        write_leads(out / "leads.csv", leads)
        emit_warnings(warnings)
        print(f"wrote {len(leads)} leads to {out / 'leads.csv'}")
        return 0
    if args.command == "extract":
        out = ensure_output_dir(args.out)
        leads = read_leads(args.input)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        candidates, evidence = extract_from_leads(leads, fetch_details=not args.no_fetch)
        candidates = dedupe_candidates(candidates)
        write_candidates(out / "candidates.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        print(f"wrote {len(candidates)} candidates and {len(evidence)} evidence rows to {out}")
        return 0
    if args.command == "all":
        out = ensure_output_dir(args.out)
        leads, warnings = discover_sources(args.sources, args.manual_seeds, context)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        write_leads(out / "leads.csv", leads)
        candidates, evidence = extract_from_leads(leads, fetch_details=not args.no_fetch)
        candidates = dedupe_candidates(candidates)
        write_candidates(out / "candidates.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        emit_warnings(warnings)
        print(f"wrote {len(leads)} leads, {len(candidates)} candidates and {len(evidence)} evidence rows to {out}")
        return 0
    parser.print_help()
    return 2


def build_context(args: argparse.Namespace) -> DiscoverContext:
    """Translate CLI args into a :class:`DiscoverContext`."""
    date_from, date_to = resolve_date_window(args)
    rendered_fetcher = build_fetcher(getattr(args, "rendered_fetcher", "auto"))
    return DiscoverContext(
        date_from=date_from,
        date_to=date_to,
        max_pages=max(1, int(getattr(args, "max_pages", 120) or 120)),
        rendered_fetcher=rendered_fetcher,
    )


def resolve_date_window(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve the effective event-date window.

    Explicit ``--date-from`` / ``--date-to`` always win. When both are empty
    we fall back to ``--last-years`` (defaulting to 3).
    """
    explicit_from = (getattr(args, "date_from", "") or "").strip()
    explicit_to = (getattr(args, "date_to", "") or "").strip()
    if explicit_from or explicit_to:
        return explicit_from, explicit_to
    years = int(getattr(args, "last_years", 0) or 0) or 3
    return default_last_years_window(years)


def discover_sources(
    source_names: str,
    manual_seeds: str,
    context: DiscoverContext,
) -> tuple[List[Lead], List[str]]:
    leads: List[Lead] = []
    names = [item.strip() for item in source_names.split(",") if item.strip()]
    print(f"discovering from {len(names)} source(s): {', '.join(names)}")
    print(f"date window: {context.date_from or '*'} .. {context.date_to or '*'}, max_pages={context.max_pages}")
    for source_name in names:
        source_class = SOURCE_REGISTRY.get(source_name)
        if source_class is None:
            raise SystemExit(f"unknown source: {source_name}")
        if source_name == "manual":
            source = source_class(manual_seeds)
        else:
            source = source_class()
        print(f"--- {source_name} ---")
        try:
            started = len(leads)
            for lead in source.discover(context):
                leads.append(lead)
                print(f"  + {lead.event_name} | {lead.event_date or 'unknown date'} | {lead.source_url}")
            added = len(leads) - started
            print(f"  {source_name}: collected {added} lead(s)")
        except Exception as exc:
            print(f"warning: source {source_name} failed: {exc}", file=sys.stderr)
            context.warn(f"{source_name} failed: {exc}")
    print(f"deduping {len(leads)} raw lead(s)...")
    deduped = dedupe_leads(leads)
    print(f"after dedupe: {len(deduped)} unique lead(s)")
    return deduped, list(context.warnings)


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


def emit_warnings(warnings: List[str]) -> None:
    for message in warnings:
        print(f"warning: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
