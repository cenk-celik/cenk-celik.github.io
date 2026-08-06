#!/usr/bin/env python3
"""
Refresh citation counts in publications.json and metrics.json.

Source: Google Scholar, via the `scholarly` library - no account, no API
key, no registration with any website. Runs on a self-hosted GitHub
Actions runner (see the `sync-publications` job in
.github/workflows/sync-content.yml), not GitHub's own hosted runners -
that's the load-bearing fact behind everything else in this docstring, so
it's worth stating first: GitHub-hosted runner IPs are well-known,
recognisable cloud/datacenter ranges, and both Google Scholar directly and
the free proxies tried below as a workaround reject that pattern almost
universally in practice (evidence below). An ordinary residential
connection doesn't carry that signal.

Given that, the primary path here (`_fetch_author()` called with no proxy
configured, in `fetch_from_google_scholar()`) is the simplest one
possible: ask scholarly for the author's profile directly. Only if that
fails does this fall back to the free-proxy machinery below
(`_find_working_proxy()`, `_scrape_candidate_proxies()`) - kept for
resilience, not because it's proven to work. It never once got a proxy
past scholarly's own liveness check in testing from a GitHub-hosted
runner, but that evidence is about the old runner's IP range, not this
code path itself, and a fallback that runs only after the direct attempt
already failed costs nothing on the days that attempt succeeds.

Earlier approaches, roughly in the order tried and dropped:

1. Scraping Google Scholar directly from a GitHub-hosted runner - blocked
   outright, essentially every run.
2. Paid/registered proxy or scraping-API services (ScraperAPI, Webshare,
   SerpApi) - ruled out by request: no signup anywhere, free tier or not.
3. `scholarly`'s own `ProxyGenerator.FreeProxies()` - broke outright, not
   just "found a bad proxy", on two separate real bugs in its
   `_fp_coroutine` the first two times this ran for real: a missing
   `repeat` argument on its refill call once the first proxy batch ran
   out (`free-proxy` made that required in 1.1.0; `scholarly` 1.7.11's
   refill call never passed one), and a plain `list.pop()` with no
   empty-list guard that crashes if a scrape ever turns up zero proxies -
   exactly what a transient bad scrape looks like, so that path gets hit
   precisely when it most needs not to crash.
4. The `free-proxy` package's own `get()` - fixed both of the above, but
   then reported zero candidate proxies found at all, ten attempts in a
   row, on a real run, despite the source site being confirmed live (a
   manual fetch at the same time returned a full table updated seconds
   earlier). The one difference: `free-proxy` sends no User-Agent header
   at all, one of the most commonly bot-filtered signatures there is.
5. Scraping the proxy list directly with a realistic browser User-Agent
   (`_scrape_candidate_proxies()` below, still in use as part of the
   fallback) - this part worked, 300 real candidates every run since.
   Actually using any of them kept failing regardless: 0 of 160
   candidates tried, across two separate real runs (60 then 100, the
   second with an 8-second timeout instead of scholarly's hardcoded 5, to
   rule out "the timeout is just too tight"), ever passed scholarly's own
   `SingleProxy()` check. Meanwhile this same workflow's other steps
   (GitHub API, Bluesky) succeeded on every run in that period, so
   GitHub Actions' general internet access was never the problem - it was
   specifically relaying through a third-party proxy from a GitHub-hosted
   IP that failed, consistent with proxies refusing traffic that looks
   like it's coming from a datacenter rather than a real residential user.

That last finding is why this moved to a self-hosted runner rather than a
sixth round of parameter tuning: the evidence pointed at the runner's own
IP range as the actual constraint, not at anything tunable in code.

Each proxy candidate in the fallback path is still handed to scholarly's
own `SingleProxy()` before being trusted - worth being precise about what
that actually checks: `_use_proxy()` -> `_check_proxy()`
(scholarly/_proxy_generator.py) tests the proxy against
`http://httpbin.org/ip` with a 5-second timeout, a general "is this proxy
alive and does it forward requests" check. It is not scholar.google.com
and was never Google-specific.

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

On failure (direct fetch blocked, and no free proxy got through either)
this prints a warning and exits 0 without touching
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


# --- Google Scholar, via scholarly direct-first, with a free-proxy fallback -

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

# How many of the scraped candidates to test (via scholarly's own
# SingleProxy check) before giving up. Free proxy lists have a high dead
# rate at any given moment - most tools and guides on this put the share
# that's actually alive and fast enough somewhere in the low tens of
# percent - so treat this as "how many rolls of the dice", not "surely
# one of the first few will work". 60 already came back 0/60 once for
# real, against a confirmed-healthy 300-candidate scrape, which reads
# more like "5 seconds is too tight a bar" (see the _TIMEOUT override in
# _find_working_proxy) than "unlucky 60 in a row" - under a 5% chance of
# that at even a pessimistic 5% true success rate. Raised alongside that
# timeout fix so a genuinely low success rate still gets a fair number of
# tries: at 5%, 100 gives roughly a 99.4% chance of at least one success.
PROXY_ATTEMPTS = 100


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
    own SingleProxy(), up to PROXY_ATTEMPTS of them, until one passes -
    see the module docstring for exactly what that check does (a general
    proxy-alive check, not anything Google-specific) and why this scrapes
    the source page itself rather than going through scholarly's
    FreeProxies() or the free-proxy package.

    Returns (proxy_url, "ok") on success, or (None, breakdown) on
    failure. The breakdown separates "the scrape itself produced no
    candidates at all" (every source URL failed, or the table came back
    empty) from "candidates were found but none tried passed scholarly's
    check" - those point at different problems (site/scrape health vs.
    ordinary free-proxy attrition), and collapsing them into one message
    is exactly what made the previous couple of rounds here slower than
    they needed to be.
    """
    candidates = _scrape_candidate_proxies()
    if not candidates:
        return None, "the scrape itself returned zero candidate proxies (every source URL failed or came back empty)"

    # scholarly hardcodes this check's timeout to 5 seconds
    # (ProxyGenerator.__init__ sets self._TIMEOUT = 5) with no public way
    # to configure it - not exposed as a constructor argument or a
    # documented setting anywhere. 0/60 real candidates passing on the
    # last run, right after fixing the scrape itself, points more at "5
    # seconds is an unfair bar for a free proxy relaying a request to a
    # second external site" than at "60 unlucky picks in a row" (at even
    # a pessimistic 5% true success rate, that's under a 5% chance).
    # Reaching past the public API for this specific attribute is a
    # deliberate, documented trade-off, not an oversight - there's no
    # other lever available without forking scholarly outright.
    pg._TIMEOUT = 8

    random.shuffle(candidates)
    tried = candidates[:PROXY_ATTEMPTS]
    for proxy in tried:
        proxy_url = f"http://{proxy}"
        if pg.SingleProxy(http=proxy_url, https=proxy_url):
            return proxy_url, "ok"
    breakdown = f"scraped {len(candidates)} candidates, tried {len(tried)} of them, none passed scholarly's own proxy check"
    return None, breakdown


def _fetch_author(scholarly) -> tuple[dict[str, int], dict]:
    """Ask scholarly for the author's profile - one `search_author_id` +
    one `fill()` call - using whatever proxy (or lack of one) is currently
    configured on the `scholarly` module. Raises on any failure; the two
    call sites in fetch_from_google_scholar() below each decide what that
    means (direct failing means "try the proxy fallback"; proxy failing
    means "give up this run").
    """
    author_stub = scholarly.search_author_id(SCHOLAR_ID)
    # One request: the "publications" section already carries each paper's
    # citation count straight off the profile table (see the module
    # docstring) - no per-publication fill() needed or wanted.
    author = scholarly.fill(author_stub, sections=["basics", "publications", "indices"])

    by_title: dict[str, int] = {}
    for pub in author.get("publications", []):
        title = (pub.get("bib", {}).get("title") or "").strip()
        if title:
            by_title[normalise(title)] = pub.get("num_citations", 0)

    if not by_title:
        raise RuntimeError("Google Scholar returned no publications")

    metrics = {
        "citations": author.get("citedby", 0),
        "hIndex": author.get("hindex", 0),
        "i10Index": author.get("i10index", 0),
    }
    return by_title, metrics


def fetch_from_google_scholar() -> tuple[dict[str, int], dict, str] | None:
    """Returns (normalised title -> citation count, metrics dict, a short
    "how" tag for the success message - "direct, no proxy" or "via
    free-proxy fallback"), or None if Google Scholar couldn't be reached
    this run, direct or via the fallback. On failure this already writes
    sync-status.json with a plain-English reason - see write_status()
    above for why that exists. On success, writing sync-status.json is
    left to main() below, once it knows how many publications actually
    matched a local entry, but the "how" tag returned here still needs to
    survive into that message - see main().

    This never raises: everything below is wrapped so that an unexpected
    failure anywhere - proxy sourcing included, which is unpredictable
    enough that it doesn't reliably fail with one clean exception type -
    can't abort the whole sync-content.yml job, just this one file.
    """
    try:
        from scholarly import ProxyGenerator, scholarly
    except ImportError as exc:
        write_status("failed", f"scholarly is not usable ({exc}); skipped Google Scholar")
        print(f"scholarly is not usable ({exc}); skipping Google Scholar.", file=sys.stderr)
        return None

    # Primary path: no proxy at all. Only expected to work from a
    # residential IP - see the module docstring for why this now runs on
    # a self-hosted runner rather than GitHub's own.
    try:
        by_title, metrics = _fetch_author(scholarly)
        return by_title, metrics, "direct, no proxy"
    except Exception as direct_exc:  # noqa: BLE001 - anything here just means "try the fallback"
        direct_reason = str(direct_exc) or type(direct_exc).__name__

    # Fallback: a scraped free proxy. Kept for resilience even though it
    # never once got past scholarly's own liveness check in testing from
    # a GitHub-hosted runner - see the module docstring for why that
    # evidence is about the old runner's IP, not this code path, and why
    # it's still worth keeping: it only runs at all once the direct
    # attempt above has already failed.
    try:
        pg = ProxyGenerator()
        proxy_url, proxy_status = _find_working_proxy(pg)
        if not proxy_url:
            write_status("failed", f"direct fetch failed ({direct_reason}); no working free proxy either: {proxy_status}")
            print(f"Direct fetch failed ({direct_reason}); could not find a working free proxy either ({proxy_status}); skipping Google Scholar.", file=sys.stderr)
            return None
        # Pass pg twice so *every* request goes through the proxy.
        scholarly.use_proxy(pg, pg)
        by_title, metrics = _fetch_author(scholarly)
    except Exception as proxy_exc:  # noqa: BLE001 - proxy failure modes are varied and unpredictable
        write_status("failed", f"direct fetch failed ({direct_reason}); proxy fetch also failed ({proxy_exc})")
        print(f"Could not reach Google Scholar this run, direct or via proxy ({direct_reason}; {proxy_exc}).", file=sys.stderr)
        return None

    return by_title, metrics, "via free-proxy fallback"


def main() -> int:
    result = fetch_from_google_scholar()
    if result is None:
        print("Could not reach Google Scholar this run; keeping existing data.", file=sys.stderr)
        return 0
    by_title, metrics_totals, source = result

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

    write_status("ok", f"updated {updated}/{len(publications)} publications ({source})")
    print(f"Updated citation counts for {updated}/{len(publications)} publications, from Google Scholar ({source}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
