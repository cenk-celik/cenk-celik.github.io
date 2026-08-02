#!/usr/bin/env python3
"""
Refresh citation counts in publications.json and metrics.json.

Source: Google Scholar, via the `scholarly` library routed through a
free, automatically-sourced rotating proxy (`ProxyGenerator.FreeProxies()`)
- no account, no API key, no registration with any website. Two earlier
approaches were tried and dropped: scraping Google Scholar directly
(blocked on essentially every GitHub Actions run - shared runner IPs are
heavily flagged), and routing through paid/registered proxy or
scraping-API services (ScraperAPI, Webshare, SerpApi), which either
turned out not to be free in practice or required signing up somewhere -
ruled out by request. Free rotating proxies avoid both problems, at a
real cost: they are frequently slow, already dead, or already blocked by
Google themselves, so this may fail more often than a paid proxy would
have. That's an accepted trade-off for needing zero registration
anywhere, not a bug.

Every publication's citation count is read straight off the author's own
profile page (the same "Title / Cited by / Year" table you see on
https://scholar.google.com/citations?user=<id>) as part of the one
`scholarly.fill(author, ...)` call below - it is never fetched by opening
each publication's own page. That used to happen here (one extra
`scholarly.fill(pub)` request per paper), and per the scholarly
maintainers it is specifically that per-publication scraping - not
author-level scraping - that free proxies essentially never get away
with (github.com/scholarly-python-package/scholarly, discussion #330:
"FreeProxy is not at all an option if you are scraping publications ...
but works mostly fine if you are scraping authors' info"). Dropping it
also cuts a run from 1 + one-request-per-paper down to about two requests
total (search + one profile page, since this author has well under the
100-publication page size scholarly requests at once) - both fewer
requests and each one far more likely to get through.

Only citation counts are ever touched here - title, authors, venue, type,
DOI, links and `selected` are hand-curated and left exactly as they are.
New publications are not auto-added from Google Scholar: it occasionally
splits one real paper into two records (e.g. a preprint indexed
separately from its published version), so adding papers automatically
risks creating duplicates. Add new entries to publications.json by hand;
from the next run onwards this script keeps their citation count current.

On failure (no working free proxy found, or Google blocking the request
even through a proxy) this prints a warning and exits 0 without touching
the data files, so the site keeps building from the last known-good data
("keep-last-good").

Run manually with: python scripts/fetch_publications.py
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

SCHOLAR_ID = "zidMl6YAAAAJ"

ROOT = Path(__file__).resolve().parent.parent
PUB_PATH = ROOT / "src" / "content" / "publications" / "publications.json"
METRICS_PATH = ROOT / "src" / "content" / "publications" / "metrics.json"


def normalise(title: str) -> str:
    """A stable-ish key for matching the same paper across sources."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def format_publications(publications: list[dict]) -> str:
    """Serialise the same way the file has always been hand-formatted: one
    object per block, but each value (including the `authors` array) stays
    on a single line. Plain `json.dumps(..., indent=2)` would instead wrap
    every `authors` list onto one line per name, turning a citation-count-only
    update into a huge, unreviewable diff."""
    lines = ["["]
    for i, pub in enumerate(publications):
        lines.append("  {")
        keys = list(pub.keys())
        for j, key in enumerate(keys):
            comma = "," if j < len(keys) - 1 else ""
            lines.append(f'    "{key}": {json.dumps(pub[key], ensure_ascii=False)}{comma}')
        lines.append("  }" + ("," if i < len(publications) - 1 else ""))
    lines.append("]")
    return "\n".join(lines) + "\n"


# --- Google Scholar, via scholarly + a free proxy ---------------------------


def fetch_from_google_scholar() -> tuple[dict[str, int], dict] | None:
    """Returns (normalised title -> citation count, metrics dict), or None
    if Google Scholar couldn't be reached this run.

    This never raises: free-proxy sourcing is unpredictable enough that it
    can fail in ways scholarly itself doesn't turn into a clean boolean -
    e.g. `ProxyGenerator.FreeProxies()` can raise instead of returning
    False if the underlying proxy-list site is unreachable, which was
    caught during testing here. An uncaught exception from this function
    would abort the whole sync-content.yml job (repos and Bluesky steps
    included), not just this one file, so everything below is wrapped
    accordingly rather than trusting any single call to fail cleanly.
    """
    try:
        from scholarly import ProxyGenerator, scholarly
    except ImportError as exc:
        print(f"scholarly is not usable ({exc}); skipping Google Scholar.", file=sys.stderr)
        return None

    try:
        pg = ProxyGenerator()
        if not pg.FreeProxies():
            print("Could not find a working free proxy this run; skipping Google Scholar.", file=sys.stderr)
            return None
        # Pass pg twice so *every* request goes through the proxy.
        scholarly.use_proxy(pg, pg)

        author_stub = scholarly.search_author_id(SCHOLAR_ID)
        # One request: the "publications" section already carries each
        # paper's citation count straight off the profile table (see the
        # module docstring) - no per-publication fill() needed or wanted.
        author = scholarly.fill(author_stub, sections=["basics", "publications", "indices"])

        by_title: dict[str, int] = {}
        for pub in author.get("publications", []):
            title = (pub.get("bib", {}).get("title") or "").strip()
            if title:
                by_title[normalise(title)] = pub.get("num_citations", 0)
    except Exception as exc:  # noqa: BLE001 - free-proxy failure modes are varied and unpredictable
        print(f"Could not reach Google Scholar this run ({exc}).", file=sys.stderr)
        return None

    if not by_title:
        print("Google Scholar returned no publications this run.", file=sys.stderr)
        return None

    metrics = {
        "citations": author.get("citedby", 0),
        "hIndex": author.get("hindex", 0),
        "i10Index": author.get("i10index", 0),
    }
    return by_title, metrics


def main() -> int:
    result = fetch_from_google_scholar()
    if result is None:
        print("Could not reach Google Scholar this run; keeping existing data.", file=sys.stderr)
        return 0
    by_title, metrics_totals = result

    if not PUB_PATH.exists():
        print("publications.json not found; nothing to update.", file=sys.stderr)
        return 0

    publications = json.loads(PUB_PATH.read_text(encoding="utf-8"))
    updated = 0
    for pub in publications:
        key = normalise(pub.get("title", ""))
        if key in by_title:
            pub["citations"] = by_title[key]
            updated += 1
        # else: not found in this run's source - leave its citation count
        # as it was rather than guessing.

    PUB_PATH.write_text(format_publications(publications), encoding="utf-8")

    metrics = {**metrics_totals, "updated": datetime.date.today().isoformat()}
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print(f"Updated citation counts for {updated}/{len(publications)} publications, from Google Scholar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
