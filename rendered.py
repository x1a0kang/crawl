"""Rendered (JavaScript-aware) HTTP fetchers.

Some authoritative sources (notably ``runchina.org.cn``) gate their listing
pages behind a Tencent anti-bot challenge that returns an interstitial script
when fetched with plain HTTP. To support those sources we expose a small
``rendered_fetcher`` abstraction: a callable ``(url, page) -> str`` that returns
HTML rendered by a JavaScript-capable client.

The default implementation shells out to the local ``firecrawl`` CLI; if it is
not available, the call returns an empty string and a warning is recorded on
the surrounding :class:`DiscoverContext` so the rest of the pipeline can still
run. The ``none`` mode skips the rendered path entirely.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Callable, Optional


RenderedFetcher = Callable[[str, int], str]


def has_firecrawl_cli() -> bool:
    """Return ``True`` when the local ``firecrawl`` binary is on PATH."""
    return shutil.which("firecrawl") is not None


def firecrawl_fetcher(timeout: int = 60) -> RenderedFetcher:
    """Build a fetcher that shells out to the ``firecrawl scrape`` CLI.

    The wrapper intentionally swallows errors and returns an empty string on
    failure so the caller can decide whether to warn or skip. We pass
    ``--only-main-content`` so we receive the already-cleaned HTML rather than
    the raw response payload.
    """

    def _fetch(url: str, page: int) -> str:
        if not has_firecrawl_cli():
            return ""
        try:
            result = subprocess.run(
                [
                    "firecrawl",
                    "scrape",
                    url,
                    "--only-main-content",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout or ""

    return _fetch


def parse_firecrawl_markdown(markdown: str) -> str:
    """Convert firecrawl's default markdown output into a stripped HTML-ish
    string the existing HTML parser can chew on.

    Firecrawl's ``scrape`` defaults to markdown; we wrap each non-empty line in
    a paragraph tag so that ``LinkExtractor`` can pick up the URLs. This is a
    best-effort translation: we only need the table cells that contain a
    date, a title and a location to round-trip through the parser.
    """
    if not markdown:
        return ""
    out: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "<a " in line or "](http" in line:
            # Keep markdown links but ensure they are not stripped of <a>.
            if "](" in line and "<a " not in line:
                line = _markdown_links_to_html(line)
        out.append(f"<p>{line}</p>")
    return "\n".join(out)


def _markdown_links_to_html(line: str) -> str:
    """Convert ``[text](url)`` markdown into ``<a href="url">text</a>``."""

    import re

    def _replace(match: "re.Match[str]") -> str:
        text, url = match.group(1), match.group(2)
        return f'<a href="{url}">{text}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace, line)


def build_fetcher(mode: str) -> Optional[RenderedFetcher]:
    """Resolve the CLI ``--rendered-fetcher`` value to a concrete callable.

    ``auto`` and ``firecrawl`` both return the firecrawl-backed fetcher (the
    latter is explicit so future modes like ``playwright`` can branch on it).
    ``none`` returns ``None`` to signal "do not render anything".
    """
    value = (mode or "auto").strip().lower()
    if value in {"none", "off", "false", "0"}:
        return None
    if value in {"auto", "firecrawl", "fc"}:
        return firecrawl_fetcher()
    return None


def fetcher_to_json(fetcher: Optional[RenderedFetcher]) -> str:
    """Best-effort label so a context can be logged without exposing callables."""
    if fetcher is None:
        return "none"
    if has_firecrawl_cli():
        return "firecrawl"
    return "firecrawl(unavailable)"


__all__ = [
    "RenderedFetcher",
    "build_fetcher",
    "fetcher_to_json",
    "firecrawl_fetcher",
    "has_firecrawl_cli",
    "parse_firecrawl_markdown",
]
