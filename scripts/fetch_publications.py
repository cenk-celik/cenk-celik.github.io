#!/usr/bin/env python3
"""
Keep publications.json's *list* of publications current - add genuinely
new ones automatically, weekly. Nothing here touches citation counts,
h-index or i10-index any more: that whole approach (Google Scholar via
`scholarly`, first through GitHub-hosted runners, then a scraped free
proxy, then a self-hosted runner, then a local scheduled script) never
once reliably worked in production and has been dropped entirely - see
git history if the detail is ever useful again. metrics.json is gone;
the publications page no longer shows citation counts anywhere.

Source: Crossref's REST API (api.crossref.org), filtered to this site
owner's ORCID iD - no account, no API key, no registration, and no bot
detection to fight: this is a plain, documented, intentionally
automation-friendly public API, not a scrape. That's the whole reason
this can run on an ordinary GitHub-hosted Actions runner again rather
than needing a residential IP: Crossref doesn't care what kind of
machine asks it a question. Google Scholar has no equivalent - this
script only exists at all because Crossref does.

A request to `/works?filter=orcid:<id>` returns every work Crossref has
on file naming that ORCID iD as an author - for this ORCID iD, 20 records
as of writing, checked directly: some journal articles, some preprints,
and some things that are emphatically not publications in the sense this
site means - eLife specifically registers a DOI for each public review
and author response as well as the paper itself, and Crossref's `type`
for those is `peer-review` or `posted-content` with no useful distinction
from a real preprint at the `type` level alone - and protocols.io lab
protocols use `posted-content` too, for a third thing that isn't a
preprint either. That's dealt with by _classify() below rather than
trusted away: an explicit type allowlist, a DOI-prefix check for
protocols.io specifically, and a title-prefix check for the specific
eLife/PREreview boilerplate ("Author response:", "Editor's evaluation",
"Reviewer report", "Decision letter", "Public review") that shows up
under `posted-content` alongside genuine preprints.

Matching against what's already in publications.json is DOI-first (every
hand-curated entry already has one, bar a couple of conference abstracts
this script never touches anyway) since that's exact and unambiguous,
unlike title text. A DOI already present means nothing to do. A DOI
that's new but whose normalised title matches an existing entry usually
means the same paper under a second DOI - most often a preprint that has
since been formally published, since Crossref keeps the preprint's own
DOI live and searchable even after that happens. Auto-adding that as a
second, visually duplicate-looking entry is exactly the failure mode an
earlier version of this script was written to avoid, so it still is:
those cases are left out of publications.json and named in
sync-status.json instead, for a quick manual look - typically just
updating the existing entry's own `doi`/`url` by hand from preprint to
journal version, a one-line edit.

Everything else that passes the type filter and doesn't match an
existing DOI or title is a genuinely new publication and gets added
automatically: title, authors (best-effort "initials surname" formatting
to match this file's existing style, truncated to six names plus "et
al." past ten), year, venue, doi/url, and a type guessed from Crossref's
own `type`/`subtype` (`journal-article` -> "journal", `posted-content` ->
"preprint", `book-chapter` -> "book-chapter", `proceedings-article` and
`report` -> "journal", `monograph` -> "book-chapter"). `selected` is
always false - featuring a paper on the homepage stays a deliberate,
hand-made choice, never automatic. None of this is claimed to be
perfect: "review" vs plain "journal", the exact author list for a
twenty-author paper, a hand-written `venueAbbr` - all of that stays a
judgement call this script doesn't try to make, same as it's always been
for hand-added entries. Auto-added entries are a first draft, not a
final one; touching them up by hand afterwards is normal, not a bug
report.

On failure (Crossref unreachable, or an unexpected response shape) this
prints a warning and exits 0 without touching publications.json, so the
site keeps building from the last known-good list ("keep-last-good"). It
does still write sync-status.json (outcome + a plain-English reason) on
every run, success or failure, so a silent failure is visible straight
from `git log src/content/publications/sync-status.json`.

Run manually with: python scripts/fetch_publications.py
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

ORCID_ID = "0000-0001-8301-0172"
CROSSREF_URL = f"https://api.crossref.org/works?filter=orcid:{ORCID_ID}&rows=100&select=DOI,title,author,published,published-print,published-online,issued,created,container-title,institution,type,subtype"
# A descriptive User-Agent with a contact address, per Crossref's own
# etiquette (the "polite pool") - not required, but it's free reliability
# and costs one line. See https://api.crossref.org (their own docs page).
REQUEST_HEADERS = {"User-Agent": "cenk-celik.github.io publications sync (mailto:cenk.celik@proton.me)"}

ROOT = Path(__file__).resolve().parent.parent
PUB_PATH = ROOT / "src" / "content" / "publications" / "publications.json"
STATUS_PATH = ROOT / "src" / "content" / "publications" / "sync-status.json"

# Crossref `type` values worth treating as a publication for this site.
# Deliberately excludes (among others actually seen on this ORCID iD's
# own record): `peer-review` (eLife's public reviews), `journal` and
# `book` (the container, not a work), `component`, `grant`, `dataset`.
ALLOWED_CROSSREF_TYPES = {
    "journal-article",
    "book-chapter",
    "posted-content",
    "proceedings-article",
    "report",
    "monograph",
}

# `posted-content` covers genuine preprints *and* eLife/PREreview-style
# review artefacts (author responses, editor's evaluations, decision
# letters, public reviews) under the same Crossref `type`. Crossref's own
# `subtype` field distinguishes these when present ("preprint" vs
# anything else); this title-prefix list is the fallback for the records
# that don't set `subtype` at all, based on the actual boilerplate titles
# eLife uses for these artefacts.
NON_PREPRINT_TITLE_PREFIXES = (
    "author response",
    "editor's evaluation",
    "editors' evaluation",
    "reviewer report",
    "decision letter",
    "public review",
)

CROSSREF_TYPE_TO_PUB_TYPE = {
    "journal-article": "journal",
    "book-chapter": "book-chapter",
    "posted-content": "preprint",  # overridden for protocols.io - see _classify()
    "proceedings-article": "journal",
    "report": "journal",
    "monograph": "book-chapter",
}

# protocols.io registers its own DOIs under `posted-content`, same
# Crossref `type` as a genuine preprint - seen for real on this ORCID
# iD's own record (a lab protocol already hand-listed here with `type:
# "protocol"`). DOI prefix is a reliable way to tell them apart from an
# actual preprint server; extend this if another protocol repository
# ever shows up on this ORCID iD.
PROTOCOL_DOI_PREFIXES = ("10.17504/",)  # protocols.io


def normalise(title: str) -> str:
    """A stable-ish key for matching the same paper across sources.
    Strips a trailing version suffix ("... v1", "... V2") first - seen for
    real on this ORCID iD's own protocols.io entry, which Crossref titles
    with a "v1" the hand-curated publications.json entry never had, and
    which would otherwise defeat this exact dedup check."""
    title = re.sub(r"\s+v\d+$", "", title.strip(), flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def normalise_doi(doi: str) -> str:
    """DOIs are case-insensitive and sometimes show up with a full URL
    prefix; reduce to a bare lowercase DOI so comparisons are reliable."""
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def write_status(outcome: str, message: str) -> None:
    """Written on every run, success or failure alike - see git history
    (this line survives from the previous approach) for why: a run that
    quietly failed still leaves a plain-English reason in `git log`,
    readable with no login to this repo, no GitHub Actions access."""
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
    every `authors` list onto one line per name, turning a small update
    into a huge, unreviewable diff."""
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


# --- Crossref -----------------------------------------------------------


def _classify(item: dict, doi: str) -> tuple[str, str] | None:
    """Returns (pub_type, venue) for a Crossref work worth listing on this
    site, or None to skip it entirely. All of the "is this actually a
    publication" judgement calls live here in one place, in order:

    1. Type allowlist - drops peer-review, dataset, grant, and the
       journal/book "container" records outright.
    2. `posted-content` from protocols.io is a lab protocol, not a
       preprint, despite sharing the same Crossref `type` - checked by
       DOI prefix, the reliable signal (see PROTOCOL_DOI_PREFIXES above).
    3. `posted-content` from anywhere else: Crossref's own `subtype` says
       "preprint" or it doesn't, and when it doesn't say anything at all,
       the title is checked against known non-preprint boilerplate
       (eLife's public reviews and author responses) as a fallback.
    """
    crossref_type = item.get("type", "")
    if crossref_type not in ALLOWED_CROSSREF_TYPES:
        return None

    if crossref_type == "posted-content" and doi.startswith(PROTOCOL_DOI_PREFIXES):
        return "protocol", "Protocol"

    if crossref_type == "posted-content":
        subtype = (item.get("subtype") or "").strip().lower()
        if subtype:
            if subtype != "preprint":
                return None
        else:
            title = ((item.get("title") or [""])[0] or "").strip().lower()
            if title.startswith(NON_PREPRINT_TITLE_PREFIXES):
                return None

    pub_type = CROSSREF_TYPE_TO_PUB_TYPE.get(crossref_type, "journal")
    venue = _guess_venue(item, pub_type, doi)
    return pub_type, venue


def _extract_year(item: dict) -> int | None:
    for key in ("published", "published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts")
        if parts and parts[0] and parts[0][0]:
            return int(parts[0][0])
    return None


def _format_authors(crossref_authors: list[dict]) -> list[str]:
    formatted = []
    for a in crossref_authors:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family:
            initials = " ".join(f"{part[0]}." for part in given.split() if part)
            formatted.append(f"{initials} {family}".strip())
            continue
        name = (a.get("name") or "").strip()  # consortium-style entries
        if name:
            formatted.append(name)
    if len(formatted) > 10:
        formatted = formatted[:6] + ["et al."]
    return formatted


def _slugify(text: str, max_len: int = 24) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].rstrip("-")


def _guess_venue(item: dict, pub_type: str, doi: str) -> str:
    container = item.get("container-title") or []
    if container and container[0].strip():
        return container[0].strip()
    if pub_type == "preprint":
        # Crossref omits container-title for preprints. bioRxiv and
        # medRxiv (both Cold Spring Harbor Laboratory) share the
        # 10.1101/ prefix, which covers every preprint seen on this
        # ORCID iD's record so far - a reasonable default, not a blind
        # guess, but still worth a second glance for anything from a
        # different preprint server.
        if doi.startswith("10.1101/"):
            return "bioRxiv"
        institution = item.get("institution") or []
        if institution and institution[0].get("name"):
            return institution[0]["name"].strip()
        return "Preprint"
    return ""


def _make_id(first_author_family: str, year: int, venue: str, existing_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "", first_author_family.lower()) or "pub"
    venue_slug = _slugify(venue) or "work"
    candidate = f"{base}{year}-{venue_slug}"
    final, n = candidate, 2
    while final in existing_ids:
        final = f"{candidate}-{n}"
        n += 1
    return final


def fetch_crossref_works() -> list[dict] | None:
    """Returns the raw list of Crossref work records for ORCID_ID, or
    None if the request failed outright. Never raises."""
    try:
        import requests

        resp = requests.get(CROSSREF_URL, headers=REQUEST_HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["items"]
    except Exception as exc:  # noqa: BLE001 - network/JSON-shape failures are varied
        write_status("failed", f"could not fetch from Crossref: {exc}")
        print(f"Could not fetch from Crossref ({exc}).", file=sys.stderr)
        return None


def main() -> int:
    if not PUB_PATH.exists():
        write_status("failed", "publications.json not found in this checkout")
        print("publications.json not found; nothing to update.", file=sys.stderr)
        return 0

    items = fetch_crossref_works()
    if items is None:
        return 0

    publications = json.loads(PUB_PATH.read_text(encoding="utf-8"))
    existing_dois = {normalise_doi(p["doi"]) for p in publications if p.get("doi")}
    existing_titles = {normalise(p["title"]) for p in publications if p.get("title")}
    existing_ids = {p["id"] for p in publications if p.get("id")}

    new_entries: list[dict] = []
    possible_updates: list[str] = []  # human-readable titles, for the status message
    checked = 0

    for item in items:
        doi = normalise_doi(item.get("DOI", ""))
        title = ((item.get("title") or [""])[0] or "").strip()
        if not doi or not title:
            continue

        classified = _classify(item, doi)
        if classified is None:
            continue
        pub_type, venue = classified
        checked += 1

        if doi in existing_dois:
            continue

        title_key = normalise(title)
        if title_key in existing_titles:
            possible_updates.append(title)
            continue

        year = _extract_year(item) or datetime.date.today().year
        authors = _format_authors(item.get("author", []))
        first_family = (item.get("author", [{}])[0].get("family") or "pub") if item.get("author") else "pub"
        entry_id = _make_id(first_family, year, venue, existing_ids)
        existing_ids.add(entry_id)

        new_entries.append({
            "id": entry_id,
            "title": title,
            "authors": authors or ["Cenk Celik"],
            "year": year,
            "venue": venue,
            "type": pub_type,
            "doi": doi,
            "url": f"https://doi.org/{doi}",
            "pubmedUrl": None,
            "preprintUrl": f"https://doi.org/{doi}" if pub_type == "preprint" else None,
            "selected": False,
        })
        existing_dois.add(doi)
        existing_titles.add(title_key)

    if new_entries:
        publications.extend(new_entries)
        PUB_PATH.write_text(format_publications(publications), encoding="utf-8")

    parts = [f"checked {checked} Crossref record{'s' if checked != 1 else ''} for ORCID {ORCID_ID}"]
    parts.append(f"added {len(new_entries)} new" if new_entries else "nothing new to add")
    if possible_updates:
        joined = "; ".join(possible_updates[:5])
        parts.append(f"{len(possible_updates)} possible existing-entry update{'s' if len(possible_updates) != 1 else ''} to check by hand: {joined}")
    write_status("ok", "; ".join(parts))
    print("; ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
