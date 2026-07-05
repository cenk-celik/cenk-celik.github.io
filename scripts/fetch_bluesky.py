#!/usr/bin/env python3
"""
Refresh the cached snapshot of recent Bluesky posts shown on the homepage.

Uses Bluesky's public, unauthenticated AppView API - no account, app
password or token needed since the profile is public. On any failure this
prints a warning and exits 0 without touching cache.json, so the homepage
keeps showing the last successful snapshot ("keep-last-good") instead of an
empty section.
"""
from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HANDLE = "cenkcelik.bsky.social"
DISPLAY_LIMIT = 3
FETCH_LIMIT = 10  # fetch a few extra in case the newest items are replies/reposts
ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "src" / "content" / "bluesky" / "cache.json"
API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def main() -> int:
    params = urllib.parse.urlencode({"actor": HANDLE, "limit": FETCH_LIMIT})
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": "cenk-celik-github-io-site"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"Could not reach Bluesky this run ({exc}); keeping existing cache.", file=sys.stderr)
        return 0

    posts = []
    for item in data.get("feed", [])[:DISPLAY_LIMIT]:
        post = item.get("post", {})
        record = post.get("record", {})
        reason = item.get("reason", {})
        is_repost = reason.get("$type") == "app.bsky.feed.defs#reasonRepost"

        uri = post.get("uri", "")
        rkey = uri.rstrip("/").split("/")[-1]
        author_handle = post.get("author", {}).get("handle", HANDLE)

        images = [
            {"url": img.get("fullsize", ""), "alt": img.get("alt", "")}
            for img in post.get("embed", {}).get("images", [])
        ]

        entry = {
            "uri": uri,
            "url": f"https://bsky.app/profile/{author_handle}/post/{rkey}",
            "text": record.get("text", ""),
            "createdAt": record.get("createdAt", ""),
            "likeCount": post.get("likeCount", 0),
            "repostCount": post.get("repostCount", 0),
            "images": images,
        }
        if is_repost:
            by = reason.get("by", {})
            entry["repostOf"] = by.get("displayName") or by.get("handle")

        posts.append(entry)

    if not posts:
        print("Bluesky returned no posts this run; keeping existing cache.", file=sys.stderr)
        return 0

    payload = {
        "fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "posts": posts,
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Cached {len(posts)} Bluesky posts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
