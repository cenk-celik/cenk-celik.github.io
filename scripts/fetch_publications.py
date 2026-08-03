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

The proxy itself is sourced with the `free-proxy` package's own `get()`
method (see _find_working_proxy() below), not `scholarly`'s
`ProxyGenerator.FreeProxies()`. FreeProxies() runs its own bespoke
generator (`_fp_coroutine`) to cycle through candidate proxies, and it
has broken outright, not just "found a bad proxy", on two separate real
bugs the first two times this ran for real: a missing `repeat` argument
on its refill call once its first proxy batch ran out (`free-proxy`
turned that into a required argument in 1.1.0; `scholarly` 1.7.11's
refill call never passed one), and a plain `list.pop()` with no
empty-list guard that crashes outright if a scrape ever turns up zero
proxies - which is exactly what a transient bad scrape looks like, so
that path gets exercised precisely when you need it not to crash.
`free-proxy`'s own public `get()` doesn't have either problem (a safe
`for` loop, a clean `FreeProxyException` when nothing works, and as of
1.1.0 it already retries a second, different source site on its own
before giving up), so this calls that directly and hands the result to
scholarly as a fixed proxy via `SingleProxy()` instead.

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

PROXY_ATTEMPTS = 10


def _find_working_proxy(pg) -> tuple[str | None, str]:
    """Source a single working proxy via free-proxy's own get() and hand
    it to scholarly with SingleProxy() - see the module docstring for why
    this doesn't use scholarly's own FreeProxies()/_fp_coroutine.

    get() only confirms a proxy can reach google.com in general, not
    scholar.google.com specifically, so this still asks scholarly's own
    SingleProxy() (which does check scholar.google.com) to confirm each
    candidate before trusting it, and moves on to a fresh one from
    get() if that check fails - up to PROXY_ATTEMPTS times.

    Returns (proxy_url, "ok") on success, or (None, breakdown) on
    failure. The breakdown separates "free-proxy itself never produced a
    candidate" (site down, scrape blocked, nothing there) from "a
    candidate was found but scholar.google.com specifically rejected it"
    (the proxy is fine in general, Google just doesn't like it) - the
    previous plain "no working free proxy found" message collapsed both
    into one, and which one it actually is points at a different problem.
    """
    from fp.errors import FreeProxyException
    from fp.fp import FreeProxy

    no_candidate = 0
    rejected_by_scholar = 0
    for _ in range(PROXY_ATTEMPTS):
        try:
            proxy_url = FreeProxy(rand=True, timeout=1).get()
        except FreeProxyException:
            no_candidate += 1
            continue  # this attempt's scrape/candidate didn't pan out; try again
        if proxy_url and pg.SingleProxy(http=proxy_url, https=proxy_url):
            return proxy_url, "ok"
        rejected_by_scholar += 1
    breakdown = (
        f"{no_candidate}/{PROXY_ATTEMPTS} attempts found no candidate proxy at all, "
        f"{rejected_by_scholar}/{PROXY_ATTEMPTS} found one but scholar.google.com rejected it"
    )
    return None, breakdown


def fetch_from_google_scholar() -> tuple[dict[str, int], dict] | None:
    """Returns (normalised title -> citation count, metrics dict), or None
    if Google Scholar couldn't be reached this run. Either way, also
    writes sync-status.json with a plain-English reason - see
    write_status() above for why that exists.

    This never raises: free-proxy sourcing is unpredictable enough that it
    can fail in ways that aren't reliably turned into a clean boolean or a
    single documented exception type - `_find_working_proxy()` already
    catches free-proxy's own `FreeProxyException`, but an uncaught
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
            write_status("failed", f"no working free proxy found in {PROXY_ATTEMPTS} attempts this run ({proxy_status})")
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
