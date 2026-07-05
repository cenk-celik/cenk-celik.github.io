#!/usr/bin/env python3
"""
Fetch publications from Google Scholar and merge them into publications.json,
preserving hand-curated fields (most importantly `selected`).

Google Scholar has no official API. This uses the `scholarly` library, which
scrapes the public profile page and is liable to be rate-limited or blocked
by Google from time to time - that's expected, not a bug, and happens to
every academic site that automates this. On any failure this script prints
a warning and exits 0 without touching publications.json, so the site keeps
building from the last known-good data ("keep-last-good").

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
    """A stable-ish key for matching the same paper across scrapes."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def infer_type(venue: str) -> str:
    v = (venue or "").lower()
    if "biorxiv" in v or "medrxiv" in v or "preprint" in v:
        return "preprint"
    return "journal"


def main() -> int:
    try:
        from scholarly import scholarly
    except ImportError:
        print(
            "scholarly is not installed (pip install -r scripts/requirements.txt); skipping.",
            file=sys.stderr,
        )
        return 0

    try:
        author_stub = scholarly.search_author_id(SCHOLAR_ID)
        author = scholarly.fill(
            author_stub, sections=["publications", "basics", "indices"]
        )
    except Exception as exc:  # noqa: BLE001 - Scholar's failure modes are varied and unpredictable
        print(
            f"Could not reach Google Scholar this run ({exc}); keeping existing data.",
            file=sys.stderr,
        )
        return 0

    existing = []
    if PUB_PATH.exists():
        existing = json.loads(PUB_PATH.read_text(encoding="utf-8"))
    existing_by_key = {normalise(p["title"]): p for p in existing}

    merged: list[dict] = []
    seen_keys: set[str] = set()

    for pub in author.get("publications", []):
        try:
            filled = scholarly.fill(pub)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Skipping one publication after a fetch error ({exc}).",
                file=sys.stderr,
            )
            continue

        bib = filled.get("bib", {})
        title = (bib.get("title") or "").strip()
        if not title:
            continue

        key = normalise(title)
        seen_keys.add(key)
        prior = existing_by_key.get(key, {})

        year_raw = bib.get("pub_year")
        year = int(year_raw) if year_raw else prior.get("year", 0)
        venue = bib.get("citation") or bib.get("venue") or prior.get("venue", "")
        authors = (
            bib.get("author", "").split(" and ")
            if bib.get("author")
            else prior.get("authors", [])
        )

        entry = {
            "id": prior.get("id", key),
            "title": title,
            "authors": authors or prior.get("authors", []),
            "year": year,
            "venue": venue or prior.get("venue", ""),
            "venueAbbr": prior.get("venueAbbr", (venue or "")[:24]),
            # `type` and links are easy to get wrong from a scrape, so once a
            # human (or a previous run) has set them, leave them alone.
            "type": prior.get("type", infer_type(venue)),
            "doi": prior.get("doi"),
            "url": prior.get("url")
            or filled.get("pub_url")
            or f"https://scholar.google.com/citations?user={SCHOLAR_ID}",
            "pubmedUrl": prior.get("pubmedUrl"),
            "preprintUrl": prior.get("preprintUrl"),
            "citations": filled.get("num_citations", prior.get("citations", 0)),
            # Never overwritten by this script - edit publications.json by
            # hand to feature (or unfeature) a paper on the homepage.
            "selected": prior.get("selected", False),
        }
        merged.append(entry)

    # A partial or blocked scrape shouldn't silently delete papers that were
    # there before - carry over anything this run didn't see.
    for key, prior in existing_by_key.items():
        if key not in seen_keys:
            merged.append(prior)

    if not merged:
        print(
            "Scholar returned no publications this run; keeping existing file untouched.",
            file=sys.stderr,
        )
        return 0

    merged.sort(
        key=lambda p: (p.get("year") or 0, p.get("citations") or 0), reverse=True
    )
    PUB_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    metrics = {
        "citations": author.get("citedby", 0),
        "hIndex": author.get("hindex", 0),
        "i10Index": author.get("i10index", 0),
        "updated": datetime.date.today().isoformat(),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print(f"Synced {len(merged)} publications.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
