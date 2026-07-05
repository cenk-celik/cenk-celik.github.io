#!/usr/bin/env python3
"""
Refresh GitHub stats (stars, language, description, last update) for the
repositories listed in src/content/repos/featured.json.

To feature a new repository: add `{"repo": "owner/name"}` to featured.json.
Nothing else needs to change - this script fills in the rest on the next run.

Uses the unauthenticated GitHub API by default. In GitHub Actions,
GITHUB_TOKEN is picked up automatically to raise the rate limit; it needs
no special permissions (public read-only data only).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEATURED_PATH = ROOT / "src" / "content" / "repos" / "featured.json"
CACHE_PATH = ROOT / "src" / "content" / "repos" / "cache.json"


def fetch(repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{repo}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "cenk-celik-github-io-site",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"Could not fetch {repo} this run ({exc}); keeping previous data.", file=sys.stderr)
        return None

    return {
        "name": data["name"],
        "fullName": data["full_name"],
        "description": data.get("description"),
        "url": data["html_url"],
        "stars": data.get("stargazers_count", 0),
        "language": data.get("language"),
        "updatedAt": data.get("pushed_at"),
        "topics": data.get("topics", []),
    }


def main() -> int:
    featured = json.loads(FEATURED_PATH.read_text(encoding="utf-8"))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}

    ok = 0
    for item in featured:
        repo = item["repo"]
        result = fetch(repo)
        if result is not None:
            cache[repo] = result
            ok += 1
        # else: leave whatever was cached for that repo untouched

    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Refreshed {ok}/{len(featured)} repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
