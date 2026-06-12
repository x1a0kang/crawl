from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, List

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawl.extractors.detail import extract_from_leads
from crawl.models import DiscoverContext, Lead, default_last_years_window
from crawl.normalize.dedupe import dedupe_candidates
from crawl.normalize.dates import in_date_range
from crawl.sources import SOURCE_REGISTRY
from crawl.writers import ensure_output_dir, read_leads, write_events, write_evidence, write_leads


DEFAULT_SOURCES = "china-marathon"
AUTHORITATIVE_LEAD_SOURCES = {"china-marathon", "manual"}
LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser.

    Author: juruikang
    Date: 2026-06-12
    """
    parser = argparse.ArgumentParser(description="Offline race data collection pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="Discover race leads from configured sources")
    discover.add_argument("--sources", default=DEFAULT_SOURCES, help="Comma-separated source names")
    discover.add_argument("--out", default="crawl/output", help="Output directory")
    discover.add_argument("--manual-seeds", default="seeds.csv", help="CSV path for manual source")
    add_date_args(discover)
    add_discovery_args(discover)

    extract = subparsers.add_parser("extract", help="Extract importable event rows from leads")
    extract.add_argument("--input", required=True, help="Input leads.csv path")
    extract.add_argument("--out", default="crawl/output", help="Output directory")
    add_date_args(extract)

    all_cmd = subparsers.add_parser("all", help="Run discovery and extraction")
    all_cmd.add_argument("--sources", default=DEFAULT_SOURCES, help="Comma-separated source names")
    all_cmd.add_argument("--out", default="crawl/output", help="Output directory")
    all_cmd.add_argument("--manual-seeds", default="seeds.csv", help="CSV path for manual source")
    add_date_args(all_cmd)
    add_discovery_args(all_cmd)

    return parser


def add_date_args(parser: argparse.ArgumentParser) -> None:
    """Add shared date-window CLI arguments.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Add discovery-only CLI arguments.

    Author: juruikang
    Date: 2026-06-12
    """
    parser.add_argument(
        "--max-pages",
        type=int,
        default=120,
        help="Maximum number of paginated requests each source may issue (default: 120)",
    )


def main(argv: List[str] = None) -> int:
    """Run the selected pipeline command.

    Author: juruikang
    Date: 2026-06-12
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    context = build_context(args)

    if args.command == "discover":
        out = ensure_output_dir(args.out)
        leads, warnings = discover_sources(args.sources, args.manual_seeds, context)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        write_leads(out / "leads.csv", leads)
        emit_warnings(warnings)
        LOGGER.info("wrote %s leads to %s", len(leads), out / "leads.csv")
        return 0
    if args.command == "extract":
        out = ensure_output_dir(args.out)
        leads = read_leads(args.input)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        candidates, evidence = extract_from_leads_with_logging(leads, context=context)
        candidates = dedupe_candidates(candidates)
        write_events(out / "events.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        emit_warnings(context.warnings)
        LOGGER.info("wrote %s events and %s evidence rows to %s", len(candidates), len(evidence), out)
        return 0
    if args.command == "all":
        out = ensure_output_dir(args.out)
        leads, _warnings = discover_sources(args.sources, args.manual_seeds, context)
        leads = filter_leads_by_date(leads, context.date_from, context.date_to)
        write_leads(out / "leads.csv", leads)
        candidates, evidence = extract_from_leads_with_logging(leads, context=context)
        candidates = dedupe_candidates(candidates)
        write_events(out / "events.csv", candidates)
        write_evidence(out / "evidence.jsonl", evidence)
        emit_warnings(context.warnings)
        LOGGER.info(
            "wrote %s leads, %s events and %s evidence rows to %s",
            len(leads),
            len(candidates),
            len(evidence),
            out,
        )
        return 0
    parser.print_help()
    return 2


def build_context(args: argparse.Namespace) -> DiscoverContext:
    """Translate CLI args into a :class:`DiscoverContext`.

    Author: juruikang
    Date: 2026-06-12
    """
    date_from, date_to = resolve_date_window(args)
    return DiscoverContext(
        date_from=date_from,
        date_to=date_to,
        max_pages=max(1, int(getattr(args, "max_pages", 120) or 120)),
    )


def resolve_date_window(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve the effective event-date window.

    Explicit ``--date-from`` / ``--date-to`` always win. When both are empty
    we fall back to ``--last-years`` (defaulting to 3).

    Author: juruikang
    Date: 2026-06-12
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
    """Discover lead rows from the selected authoritative sources.

    Author: juruikang
    Date: 2026-06-12
    """
    leads: List[Lead] = []
    requested_names = parse_source_names(source_names)
    names, ignored_names = select_lead_source_names(requested_names)
    if ignored_names:
        context.warn(
            "ignored non-authoritative lead source(s): "
            f"{', '.join(ignored_names)}; online leads now come only from china-marathon"
        )
    if not names:
        raise SystemExit(
            "no authoritative lead source selected; use --sources china-marathon "
            "or --sources manual"
        )
    LOGGER.info("discovering from %s lead source(s): %s", len(names), ", ".join(names))
    LOGGER.info("date window: %s .. %s, max_pages=%s", context.date_from or "*", context.date_to or "*", context.max_pages)
    for source_name in names:
        source_class = SOURCE_REGISTRY[source_name]
        if source_name == "manual":
            source = source_class(manual_seeds)
        else:
            source = source_class()
        LOGGER.info("--- %s ---", source_name)
        try:
            started = len(leads)
            for lead in source.discover(context):
                leads.append(lead)
                LOGGER.info("  + %s | %s | %s", lead.event_name, lead.event_date or "unknown date", lead.source_url)
            added = len(leads) - started
            LOGGER.info("  %s: collected %s lead(s)", source_name, added)
        except Exception as exc:
            LOGGER.error("source %s failed: %s", source_name, exc)
            context.warn(f"{source_name} failed: {exc}")
    LOGGER.info("deduping %s raw lead(s)...", len(leads))
    deduped = dedupe_leads(leads)
    LOGGER.info("after dedupe: %s unique lead(s)", len(deduped))
    return deduped, list(context.warnings)


def extract_from_leads_with_logging(
    leads: List[Lead],
    context: DiscoverContext,
):
    """Extract event rows by calling China Marathon detail API only.

    Author: juruikang
    Date: 2026-06-12
    """
    LOGGER.info("extracting events from %s lead(s), fetching China Marathon detail API only...", len(leads))

    def progress(index: int, total: int, lead: Lead) -> None:
        LOGGER.info("  detail %s/%s: %s | %s", index, total, lead.event_name, lead.source_url)

    return extract_from_leads(
        leads,
        progress=progress,
        warn=context.warn,
    )


def parse_source_names(source_names: str) -> List[str]:
    """Parse and validate source names from the CLI.

    Author: juruikang
    Date: 2026-06-12
    """
    names = [item.strip() for item in source_names.split(",") if item.strip()]
    for source_name in names:
        if source_name not in SOURCE_REGISTRY:
            raise SystemExit(f"unknown source: {source_name}")
    return names


def select_lead_source_names(source_names: Iterable[str]) -> tuple[List[str], List[str]]:
    """Keep only lead sources allowed by the current China Marathon-first flow.

    Author: juruikang
    Date: 2026-06-12
    """
    selected: List[str] = []
    ignored: List[str] = []
    for source_name in source_names:
        if source_name in AUTHORITATIVE_LEAD_SOURCES:
            if source_name not in selected:
                selected.append(source_name)
        elif source_name not in ignored:
            ignored.append(source_name)
    return selected, ignored


def filter_leads_by_date(leads: Iterable[Lead], date_from: str = "", date_to: str = "") -> List[Lead]:
    """Filter leads by an inclusive event-date window.

    Author: juruikang
    Date: 2026-06-12
    """
    if not date_from and not date_to:
        return list(leads)
    return [lead for lead in leads if in_date_range(lead.event_date, date_from, date_to)]


def dedupe_leads(leads: Iterable[Lead]) -> List[Lead]:
    """Remove duplicate leads while preserving discovery order.

    Author: juruikang
    Date: 2026-06-12
    """
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
    """Print collected warnings as error-level log records.

    Author: juruikang
    Date: 2026-06-12
    """
    for message in warnings:
        LOGGER.error("%s", message)


if __name__ == "__main__":
    raise SystemExit(main())
