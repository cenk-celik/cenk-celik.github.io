#!/usr/bin/env python3
"""
Refresh citation counts in publications.json and metrics.json.

Source: Google Scholar, via the `scholarly` library routed through a
free, automatically-sourced proxy - no account, no API key, no
registration with any website. Two earlier approaches were tried and
dropped: scraping Google Scholar directly (blocked on essentially every
GitHub Actions run - shared runner IPs are heavily flagged), and routing
through paid/registered proxy or scraping-API services (ScraperAPI,
Webshare, SerpApi), which either turned out not to be free in practice or
required signing up somewhere - ruled out by request. Free rotating
proxies avoid both problems, at a real cost: they are frequently slow,
already dead, or already blocked by Google themselves, so this may fail
more often than a paid proxy would have. That's an accepted trade-off for
needing zero registration anywhere, not a bug.

The proxy itself is scraped directly from free-proxy-list.net by this
script (see _scrape_candidate_proxies() below) - not sourced via the
`free-proxy` package, and not via scholarly's own
`ProxyGenerator.FreeProxies()`. Both of those were tried first, in that
order, and both failed in ways worth recording rather than silently
swapping out:

1. FreeProxies() runs its own bespoke generator (`_fp_coroutine`) to
   cycle through candidate proxies, and it broke outright, not just
   "found a bad proxy", on two separate real bugs the first two times
   this ran for real: a missing `repeat` argument on its refill call once
   its first proxy batch ran out (`free-proxy` made that a required
   argument in 1.1.0; `scholarly` 1.7.11's refill call never passed one),
   and a plain `list.pop()` with no empty-list guard that crashes if a
   scrape ever turns up zero proxies - exactly what a transient bad
   scrape looks like, so that path gets hit precisely when it most needs
   not to crash.
2. Switching to the `free-proxy` package's own public `get()` fixed both
   of those (a safe `for` loop, a clean `FreeProxyException` instead of a
   crash), but then reported zero candidate proxies found at all, ten
   attempts in a row, on a real run. Fetching the exact same source page
   by hand at the same time returned a full, live table of proxies
   updated seconds earlier - so the site wasn't down or empty. The one
   thing `free-proxy`'s scrape does differently from that manual fetch is
   send no headers at all (`requests.get(url, timeout=...)`, no
   User-Agent) - one of the most commonly bot-filtered signatures there
   is, and plausible enough, combined with the confirmed-live site, to be
   worth ruling out directly rather than guessing again.

So this scrapes the page itself with a realistic browser User-Agent
instead of going through either of the above for that step, then still
hands each candidate to scholarly's own `SingleProxy()` to confirm it
against scholar.google.com specifically before trusting it. `requests`
and `beautifulsoup4` are already hard dependencies of `scholarly` itself,
so this adds no new package - if anything it's one fewer, since
`free-proxy` is no longer needed at all.

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
publications.json or metrics.json, so the site keeps building from the
last known-good data ("keep-last-good"). It does still write
sync-status.json (outcome + a plain-English reason) on every run,
success or failure, so a silent failure is visible straight from `git
log src/content/publications/sync-status.json` rather than only from a
GitHub Actions log that needs a login to this repo to read.

Run manually with: python scripts/fetch_publications.py
"""

from __future__ import annotations

import datetime
import json
import random
import re
import sys
from pathlib import Path

SCHOLAR_ID = "zidMl6YAAAAJ"

ROOT = Path(__file__).resolve().parent.parent
PUB_PATH = ROOT / "src" / "content" / "publications" / "publications.json"
METRICS_PATH = ROOT / "src" / "content" / "publications" / "metrics.json"
STATUS_PATH = ROOT / "src" / "content" / "publications" / "sync-status.json"


def normalise(title: str) -> str:
    """A stable-ish key for matching the same paper across sources."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def write_status(outcome: str, message: str) -> None:
    """Written on every run, success or failure alike - deliberately the
    one thing this script still writes even when keep-last-good means
    nothing else changes. Viewing a GitHub Actions log needs a login to
    this repo; this doesn't - it's just a committed file, so a run that
    quietly failed still leaves a plain-English reason behind in `git
    log`/`git show` for whoever's debugging it (including a Claude
    session with no GitHub credentials)."""
    status = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "outcome": outcome,
        "message": message,
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")


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

PROXY_SOURCE_URLS = [
    # Primary, then a fallback in case the first is unreachable or its
    # markup changes out from under the #list selector below - same
    # underlying data provider (free-proxy-list.net), different page.
    "https://free-proxy-list.net/",
    "https://www.sslproxies.org/",
]
# A real browser User-Agent, not the default `python-requests/x.y.z` one
# requests sends when called with no headers - see the module docstring
# for why that specific difference is the point of this function.
PROXY_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
PROXY_ATTEMPTS = 15


def _scrape_candidate_proxies() -> list[str]:
    """Scrape a fresh list of candidate 'ip:port' proxies straight from
    free-proxy-list.net (falling back to sslproxies.org, which is the
    same underlying list under a different URL) using a normal browser
    User-Agent - see the module docstring for why. Parses the same
    `id="list"` table the `free-proxy` package itself targets, so this
    is the same data, fetched more plainly.

    Returns whatever candidates were found (possibly empty if every
    source failed or the table came back empty); doesn't filter or
    validate them - that's SingleProxy()'s job in _find_working_proxy().
    """
    import requests
    from bs4 import BeautifulSoup

    for url in PROXY_SOURCE_URLS:
        try:
            resp = requests.get(url, headers=PROXY_SCRAPE_HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException:
            continue  # try the next source URL
        soup = BeautifulSoup(resp.text, "html.parser")
        container = soup.find(id="list")
        if not container:
            continue
        candidates = []
        for row in container.find_all("tr")[1:]:  # [0] is the header row
            cells = row.find_all("td")
            if len(cells) >= 2:
                ip = cells[0].get_text(strip=True)
                port = cells[1].get_text(strip=True)
                if ip and port:
                    candidates.append(f"{ip}:{port}")
        if candidates:
            return candidates
    return []


def _find_working_proxy(pg) -> tuple[str | None, str]:
    """Scrape a batch of candidate proxies and hand each to scholarly's
    own SingleProxy() (which checks scholar.google.com specifically,
    unlike the general-purpose check a plain proxy-list scrape can do) -
    see the module docstring for why this scrapes the source page itself
    rather than going through scholarly's FreeProxies() or the
    free-proxy package.

    Returns (proxy_url, "ok") on success, or (None, breakdown) on
    failure. The breakdown separates "the scrape itself produced no
    candidates at all" (every source URL failed, or the table came back
    empty) from "candidates were found but scholar.google.com rejected
    every one tried" - those point at different problems, and collapsing
    them into one message is exactly what made the previous couple of
    rounds here slower than they needed to be.
    """
    candidates = _scrape_candidate_proxies()
    if not candidates:
        return None, "the scrape itself returned zero candidate proxies (every source URL failed or came back empty)"

    random.shuffle(candidates)
    tried = candidates[:PROXY_ATTEMPTS]
    for proxy in tried:
        proxy_url = f"http://{proxy}"
        if pg.SingleProxy(http=proxy_url, https=proxy_url):
            return proxy_url, "ok"
    breakdown = f"scraped {len(candidates)} candidates, tried {len(tried)} of them, scholar.google.com rejected every one"
    return None, breakdown


def fetch_from_google_scholar() -> tuple[dict[str, int], dict] | None:
    """Returns (normalised title -> citation count, metrics dict), or None
    if Google Scholar couldn't be reached this run. Either way, also
    writes sync-status.json with a plain-English reason - see
    write_status() above for why that exists.

    This never raises: proxy sourcing is unpredictable enough that it can
    fail in ways that aren't reliably turned into a clean boolean or a
    single documented exception type - `_scrape_candidate_proxies()`
    already catches `requests`' own `RequestException`, but an uncaught
    exception from anywhere in this function would abort the whole
    sync-content.yml job (repos and Bluesky steps included), not just this
    one file, so everything below is wrapped accordingly rather than
    trusting any single call to fail cleanly.
    """
    try:
        from scholarly import ProxyGenerator, scholarly
    except ImportError as exc:
        write_status("failed", f"scholarly is not usable ({exc}); skipped Google Scholar")
        print(f"scholarly is not usable ({exc}); skipping Google Scholar.", file=sys.stderr)
        return None

    try:
        pg = ProxyGenerator()
        proxy_url, proxy_status = _find_working_proxy(pg)
        if not proxy_url:
            write_status("failed", f"no working free proxy this run: {proxy_status}")
            print(f"Could not find a working free proxy this run ({proxy_status}); skipping Google Scholar.", file=sys.stderr)
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
        write_status("failed", f"error while fetching from Google Scholar: {exc}")
        print(f"Could not reach Google Scholar this run ({exc}).", file=sys.stderr)
        return None

    if not by_title:
        write_status("failed", "a proxy worked but Google Scholar returned no publications this run")
        print("Google Scholar returned no publications this run.", file=sys.stderr)
        return None

    metrics = {
        "citations": author.get("citedby", 0),
        "hIndex": author.get("hindex", 0),
        "i10Index": author.get("i10index", 0),
    }
    write_status("ok", f"fetched {len(by_title)} publications from Google Scholar")
    return by_title, metrics


def main() -> int:
    result = fetch_from_google_scholar()
    if result is None:
        print("Could not reach Google Scholar this run; keeping existing data.", file=sys.stderr)
        return 0
    by_title, metrics_totals = result

    if not PUB_PATH.exists():
        write_status("failed", "publications.json not found in this checkout")
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

    write_status("ok", f"updated {updated}/{len(publications)} publications")
    print(f"Updated citation counts for {updated}/{len(publications)} publications, from Google Scholar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
