#!/bin/bash
set -euo pipefail

# Refreshes Google Scholar citation counts and pushes the result if
# anything changed. Meant to be invoked on a schedule by launchd (see the
# accompanying io.cenk-celik.sync-publications.plist in this same
# folder) - not by GitHub Actions.
#
# That's deliberate, not incidental: fetch_publications.py needs to run
# from an ordinary residential IP to have any real chance of getting past
# Google Scholar (see that script's own module docstring for the
# evidence). A GitHub Actions self-hosted runner would have given it
# that, but only by registering this machine to accept jobs dispatched
# by this repository's own (public) GitHub Actions - a real trade-off,
# and one GitHub's own docs recommend against outside private repos. This
# script sidesteps that entirely: nothing here is triggered remotely, it
# only ever runs on this machine's own schedule, invoking a fixed script
# that already lives in this repo. Changing what it does means editing
# this file locally, not pushing a workflow change or opening a PR.
#
# launchd runs LaunchAgents with a minimal environment, not a full login
# shell - PATH in particular can't be trusted to already include
# Homebrew or even /usr/local. Set it explicitly so python3 and git are
# findable regardless of chip (Apple Silicon vs Intel Homebrew prefixes
# differ) or of what's already exported in whatever shell installed this.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO_DIR="/Users/cenkcelik/Documents/GitHub/cenk-celik.github.io"
cd "$REPO_DIR"

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) sync_publications_local.sh starting ==="

# sync-content.yml (repos/Bluesky, still on GitHub Actions) can commit
# independently of this script. Pull first so this doesn't build on a
# stale base and risk a rejected push if both happened to land close
# together.
git pull --rebase --quiet

python3 scripts/fetch_publications.py

git add src/content/publications
if git diff --cached --quiet; then
    echo "Nothing changed."
else
    # Uses whatever git identity is already configured on this machine -
    # the same one you commit as when running this by hand - rather than
    # a bot identity: unlike the GitHub Actions steps, this really is you,
    # from your own machine.
    git commit -m "chore: sync publications"
    git push
    echo "Pushed publications update."
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) sync_publications_local.sh done ==="
