#!/usr/bin/env python3
"""
Refresh citation counts in publications.json and metrics.json.

Primary source: Google Scholar, via the `scholarly` library routed
through a free, automatically-sourced rotating proxy
(`ProxyGenerator.FreeProxies()`) - no account, no API key, no
registration with any website. Two earlier approaches were tried and
dropped: scraping Google Scholar directly (blocked on essentially every
GitHub Actions run - shared runner IPs are heavily flagged), and routing
through paid/registered proxy or scraping-API services (ScraperAPI,
Webshare, SerpApi), which either turned out not to be free in practice or
required signing up somewhere - ruled out by request. Free rotating
proxies avoid both problems, at a real cost: they are frequently slow,
already dead, or already blocked by Google themselves, so this may fail
more often than a paid proxy would have. That's an accepted trade-off for
needing zero registration anywhere, not a bug - the Semantic Scholar
fallback below exists specifically to absorb those failures.

Fallback source: the Semantic Scholar Academic Graph API (see
fetch_from_semantic_scholar() below) - a plain JSON API, no key or
registration needed, used whenever the Google Scholar attempt fails for
any reason (no working free proxy found, Google blocking the request
even through a proxy, etc.), so the site's citation counts never freeze
for weeks the way they did before this fallback existed.

Only citation counts are ever touched here - title, authors, venue, type,
DOI, links and `selected` are hand-curated and left exactly as they are.
New publications are not auto-added from either source: both Google
Scholar and Semantic Scholar occasionally split one real paper into two
records (e.g. a preprint indexed separately from its published version),
so adding papers automatically risks creating duplicates. Add new entries
to publications.json by hand; from the next run onwards this script keeps
their citation count current.

On total failure (both sources unreachable) this prints a warning and
exits 0 without touching the data files, so the site keeps building from
the last known-good data ("keep-last-good").

Run manually with: python scripts/fetch_publications.py
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCHOLAR_ID = "zidMl6YAAAAJ"

# Semantic Scholar authorId for Cenk Celik (UCL) - confirmed by
# cross-checking affiliation and known paper titles against
# https://api.semanticscholar.org/graph/v1/author/search?query=Cenk+Celik
SEMANTIC_SCHOLAR_AUTHOR_ID = "1491365022"
SEMANTIC_SCHOLAR_API = f"https://api.semanticscholar.org/graph/v1/author/{SEMANTIC_SCHOLAR_AUTHOR_ID}"
SEMANTIC_SCHOLAR_FIELDS = "citationCount,hIndex,papers.title,papers.citationCount,papers.externalIds"

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


def _get_json(url: str, attempts: int = 3) -> dict | None:
    """Shared GET-JSON-with-retries helper for both sources below."""
    req = urllib.request.Request(url, headers={"User-Agent": "cenk-celik-github-io-site"})
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)  # 1s, 2s backoff before retrying
    print(f"Request failed ({last_exc}): {url.split('?')[0]}", file=sys.stderr)
    return None


# --- Primary source: Google Scholar, via scholarly + a free proxy ----------


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
        author = scholarly.fill(author_stub, sections=["basics", "publications", "indices"])

        by_title: dict[str, int] = {}
        for pub in author.get("publications", []):
            try:
                filled = scholarly.fill(pub)
            except Exception as exc:  # noqa: BLE001 - one bad publication shouldn't sink the run
                print(f"Skipping one publication after a fetch error ({exc}).", file=sys.stderr)
                continue
            title = (filled.get("bib", {}).get("title") or "").strip()
            if title:
                by_title[normalise(title)] = filled.get("num_citations", 0)
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


# --- Fallback source: Semantic Scholar --------------------------------------


def fetch_from_semantic_scholar() -> tuple[dict[str, int], dict[str, int], dict] | None:
    """Returns (doi -> count, normalised title -> count, metrics dict), or
    None if Semantic Scholar couldn't be reached either."""
    params = urllib.parse.urlencode({"fields": SEMANTIC_SCHOLAR_FIELDS})
    author = _get_json(f"{SEMANTIC_SCHOLAR_API}?{params}")
    if author is None:
        return None

    papers = author.get("papers") or []
    if not papers:
        print("Semantic Scholar returned no papers this run.", file=sys.stderr)
        return None

    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}
    for p in papers:
        count = p.get("citationCount") or 0
        doi = (p.get("externalIds") or {}).get("DOI")
        if doi:
            by_doi[doi.lower()] = count
        title = p.get("title")
        if title:
            by_title[normalise(title)] = count

    metrics = {
        "citations": author.get("citationCount", 0),
        "hIndex": author.get("hIndex", 0),
        # Semantic Scholar has no i10-index field; compute it the same way
        # Google Scholar does - the count of this author's papers with 10
        # or more citations, across their whole Semantic Scholar record.
        "i10Index": sum(1 for p in papers if (p.get("citationCount") or 0) >= 10),
    }
    return by_doi, by_title, metrics


def main() -> int:
    source = "Google Scholar"
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}

    result = fetch_from_google_scholar()
    if result is not None:
        by_title, metrics_totals = result
    else:
        print("Falling back to Semantic Scholar for this run.", file=sys.stderr)
        source = "Semantic Scholar"
        fallback = fetch_from_semantic_scholar()
        if fallback is None:
            print("Semantic Scholar fallback also failed; keeping existing data.", file=sys.stderr)
            return 0
        by_doi, by_title, metrics_totals = fallback

    if not PUB_PATH.exists():
        print("publications.json not found; nothing to update.", file=sys.stderr)
        return 0

    publications = json.loads(PUB_PATH.read_text(encoding="utf-8"))
    updated = 0
    for pub in publications:
        doi = (pub.get("doi") or "").lower()
        key = normalise(pub.get("title", ""))
        if doi and doi in by_doi:
            pub["citations"] = by_doi[doi]
            updated += 1
        elif key in by_title:
            pub["citations"] = by_title[key]
            updated += 1
        # else: not found in this run's source - leave its citation count
        # as it was rather than guessing.

    PUB_PATH.write_text(format_publications(publications), encoding="utf-8")

    metrics = {**metrics_totals, "updated": datetime.date.today().isoformat()}
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print(f"Updated citation counts for {updated}/{len(publications)} publications, from {source}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
