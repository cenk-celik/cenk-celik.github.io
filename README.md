# cenk-celik.github.io

Cenk Celik's academic website — built with [Astro](https://astro.build), deployed on GitHub Pages, kept up to date by GitHub Actions. This document is the full reference: architecture, why it's built this way, how to edit content day to day, and how the automation works.

## Contents

- [Why Astro](#why-astro)
- [Folder structure](#folder-structure)
- [Editing content](#editing-content) — the part you'll actually use
- [Design system](#design-system)
- [Automation](#automation)
- [Local development](#local-development)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)

## Why Astro

Three static-site options were considered: Astro, Next.js (static export) and Hugo.

**Astro won on the combination that matters here: performance, simplicity and content-editing ergonomics.** Astro ships zero JavaScript by default and only hydrates the few interactive bits that need it (the theme toggle, the mobile nav) — so the site stays close to Hugo's raw speed without losing a component-based workflow. Its Content Collections give every Markdown folder a typed schema (`src/content.config.ts`), so a malformed front matter field fails the build with a clear error instead of silently breaking a page. Next.js was ruled out because its static export still ships a React runtime for what is fundamentally a content site, and its image/asset pipeline needs extra configuration to behave well on GitHub Pages. Hugo was the closest runner-up on raw speed, but its templating language is far less pleasant than writing plain `.astro` components, and building the small interactive pieces (dark mode, the Bluesky cards) would mean hand-rolling vanilla JS with no component model at all.

GitHub Pages deployment is native: `astro build` outputs static HTML/CSS to `dist/`, which a GitHub Action uploads and publishes via the official Pages deploy action. No Jekyll, no Ruby, no Docker.

## Folder structure

```
├── .github/
│   ├── workflows/
│   │   ├── deploy.yml          # build + deploy to GitHub Pages, on every push to main
│   │   └── sync-content.yml    # daily: refresh publications, software stats, Bluesky feed
│   └── dependabot.yml          # weekly dependency PRs (npm, pip, GitHub Actions)
├── scripts/                    # Python automation, run locally or by sync-content.yml
│   ├── fetch_publications.py
│   ├── fetch_repos.py
│   └── fetch_bluesky.py
├── public/                     # served as-is: cv.pdf, favicon, robots.txt, og-image.png
├── src/
│   ├── content.config.ts       # schema for every Markdown collection below
│   ├── content/
│   │   ├── bio/                # homepage biography (one file)
│   │   ├── research/           # one file per research theme
│   │   ├── teaching/           # one file per course/workshop
│   │   ├── news/               # one file per news item
│   │   ├── publications/       # publications.json + metrics.json (machine-generated)
│   │   ├── repos/              # featured.json (curated) + cache.json (machine-generated)
│   │   └── bluesky/            # cache.json (machine-generated)
│   ├── data/site.ts            # name, email, address, social links, nav
│   ├── layouts/BaseLayout.astro
│   ├── components/             # Header, Footer, PublicationCard, RepoCard, etc.
│   ├── pages/                  # one folder per route: research/, publications/, teaching/, software/, news/
│   ├── styles/                 # tokens.css (design tokens) + global.css
│   └── lib/content.ts          # helpers: sorting, date formatting, reading the JSON caches
├── astro.config.mjs
└── package.json
```

## Editing content

Everything you're likely to touch day to day lives in `src/content/` as Markdown. **You never need to touch a `.astro` or `.ts` file to update text.**

### Biography (homepage)
Edit `src/content/bio/index.md`. The front matter (`role`, `institution`, `lab`, `labUrl`) drives the hero; the Markdown body is the paragraph text.

### Research themes
One file per theme in `src/content/research/`. Front matter: `title`, `order` (controls sort order on the `/research` page and the homepage pills). Body text is the 2–3 sentence description. To add a theme, copy an existing file and change both.

### Teaching
One file per course/workshop in `src/content/teaching/`. Front matter:

```yaml
title: Life at the Single-Cell and Spatial Scale
year: 2026
organisation: Bilimler Köyü (Village of Sciences)
location: Foça, İzmir, Turkey
status: past   # or: upcoming
link: https://bilimler.org/etkinlikler/biyoloji/168/
linkLabel: Course page (Turkish)
```

To add a future course, copy a file, bump the year, set `status: upcoming`.

### News
One file per item in `src/content/news/`, named `YYYY-MM-DD-slug.md`. Front matter is just `date:`; the body is the one- or two-sentence announcement (Markdown links work as normal).

### Publications and the "selected" flag
`src/content/publications/publications.json` is normally rewritten automatically (see [Automation](#automation)), but it's a plain JSON array and safe to hand-edit. **To feature a paper on the homepage, set its `"selected": true`.** The sync script always preserves this field, your own `doi`/`pubmedUrl`/`preprintUrl` corrections, and `type`/`venueAbbr` once you've set them — it only fills in fields it finds empty and refreshes citation counts.

```json
{
  "id": "celik2025-mol-oncol-review",
  "title": "…",
  "selected": true
}
```

### Software / featured repositories
`src/content/repos/featured.json` is the curated list — add `{ "repo": "owner/name" }` to feature a new repository. `cache.json` (stars, language, last-updated) is filled in automatically on the next sync run; you don't edit it directly.

### CV
The CV is just the PDF at `public/cv.pdf`, linked from the hero button and the nav bar — replace that file when your CV changes, nothing else needs to change. (`/cv` redirects to it, in case anything links there directly.)

### Contact details and social links
`src/data/site.ts` — one object with your email, address, ORCID, and the social icon list (Google Scholar, Bluesky, LinkedIn, X, ORCID). This is the only "code-like" file in the list, but it's a flat object, not logic.

## Design system

- **Typography**: [Inter](https://fontsource.org/fonts/inter) (variable, self-hosted via Fontsource) for UI/navigation/labels, [Newsreader](https://fontsource.org/fonts/newsreader) (variable, self-hosted) for headings and reading text. This pairing is the closest free, self-hostable equivalent to the sans/serif pairing Claude.ai itself uses (Styrene for UI, Tiempos for body) — those two are commercial typefaces licensed to Anthropic, not available to bundle into a third-party site, so Inter + Newsreader stands in for the same "clean grotesque for structure, warm serif for reading" feel.
- **Colour**: dark by default, warm near-black background rather than cold blue-grey, with a single restrained terracotta accent (`--color-accent`) used only for links, focus states and small highlights — never as a background wash. Deliberately not the generic "academic navy" you see everywhere. Light mode mirrors the same tokens; toggle persists in `localStorage`.
- **All tokens** live in `src/styles/tokens.css` — colour, type scale (fluid, `clamp()`-based), spacing, radii, motion durations. Change the site's whole palette or scale from that one file.
- **Motion**: transitions only (hover states, theme swap); no scroll animation, respects `prefers-reduced-motion`.
- **Accessibility**: skip-to-content link, visible focus rings, underlined body-copy links (not colour alone), semantic headings, alt text on every image, `aria-label`s on icon-only controls.

## Automation

### Publications (`scripts/fetch_publications.py`)
Citation counts come from Google Scholar only, via the `scholarly` library — no account, no API key, no registration anywhere.

Google Scholar has no official API, and blocks or CAPTCHAs almost every automated request from a recognisable cloud/datacenter IP — which is exactly what a GitHub-hosted runner is. That ruled out both scraping it directly from `ubuntu-latest` (blocked essentially every run) and routing through free rotating proxies from the same runner (0 of 160 candidates tried, across two separate real runs, ever got past even a basic liveness check — see the script's own module docstring for the full evidence trail, including two real bugs found and fixed along the way in `scholarly` itself). Paid or registered proxy/scraping-API services (ScraperAPI, Webshare, SerpApi) were considered and ruled out by request: no signup anywhere, free tier or not.

What's left, and what this now does: the `sync-publications` job runs on a **self-hosted runner** — a machine you control, on an ordinary residential connection that doesn't carry the cloud-IP signal Google Scholar and free proxies both reject. See [Self-hosted runner setup](#self-hosted-runner-setup) below. The script itself asks Google Scholar directly first, and only falls back to a scraped free proxy if that fails. Each run costs about two requests total: the citation count for every paper is read straight off the author's own profile page (one request), rather than by opening each publication's own page as earlier versions of this script did — the `scholarly` maintainers note that per-publication scraping specifically is what free proxies essentially never get past. When Google Scholar still can't be reached, direct or via the fallback, the script leaves the existing data untouched rather than falling back to another source, so every citation count on the site always traces back to Google Scholar.

Each entry in `publications.json` is matched by normalised title, and only its `citations` field is updated — title, authors, venue, type, DOI, links and `selected` stay exactly as hand-curated. New publications are **not** auto-added (Google Scholar occasionally splits one real paper into two records - e.g. a preprint indexed separately from its published version - which makes auto-adding risky), so add new entries by hand; the next sync then keeps their citation count current. The script is still **keep-last-good**: if Google Scholar can't be reached this run, it logs a warning and exits without touching the data files.

### Self-hosted runner setup
One-time and manual, and only needed for the `sync-publications` job above — `sync-repos-bluesky` and `deploy.yml` stay on GitHub-hosted runners and need nothing extra.

1. On GitHub: **Settings → Actions → Runners → New self-hosted runner**, choose macOS, and follow the download/configure commands shown there (they include a one-time registration token). The default work folder and default labels are fine — `sync-content.yml` targets `runs-on: self-hosted`, which matches any runner registered to this repo.
2. Don't just run `./run.sh` in a terminal for daily use — it stops the moment that window closes. From the same runner folder, install it as a persistent service instead: `./svc.sh install` then `./svc.sh start`. It then starts on login and restarts itself if it crashes.
3. The runner needs `git` and `python3` on `PATH` — both already true if you've run these scripts locally before. `actions/setup-python` handles getting the exact Python version each run.
4. The machine needs to be **on, awake and connected to the internet at 06:00 UTC** for the daily run to fire on schedule. If it's asleep, the job queues rather than failing, and runs whenever the runner next reconnects. If your Mac normally sleeps overnight, either move the cron schedule in `sync-content.yml` to a time it's reliably awake, or stop it sleeping then (**System Settings → Battery/Energy Saver**, or `pmset repeat wake`).

One security note worth being deliberate about: a self-hosted runner executes whatever a workflow says with your local user account's permissions, which is a real risk on repositories that run untrusted code (e.g. from pull requests opened by strangers). `sync-content.yml` only triggers on a schedule and manual dispatch, never on `pull_request`, so it only ever runs this repository's own reviewed code — never somebody else's. Keep it that way: don't add `pull_request` or `pull_request_target` triggers to a workflow that targets this runner.

### Software stats (`scripts/fetch_repos.py`)
Plain GitHub REST API calls (unauthenticated is enough for a handful of public repos; in Actions, the built-in `GITHUB_TOKEN` is used automatically to raise the rate limit). Same keep-last-good behaviour per repository.

### Bluesky feed (`scripts/fetch_bluesky.py`)
Bluesky's public AT Protocol AppView endpoint (`public.api.bsky.app`) needs no login or token for a public profile. The script snapshots the latest posts into `src/content/bluesky/cache.json`, which the homepage reads at build time — so the homepage never makes a live network call itself (faster, and immune to Bluesky being briefly down). Reposts are shown with a small "reposted from" label rather than filtered out, since original posts are infrequent enough that filtering them out could leave the section thin.

### Schedule
`.github/workflows/sync-content.yml` runs all three scripts once daily, as two sequential jobs — `sync-repos-bluesky` (GitHub-hosted) then `sync-publications` (self-hosted) — each committing only the files it touched if anything changed. Either commit landing on `main` triggers `deploy.yml`, so the live site picks up new papers, updated stars or fresh posts with no manual step. It can also be run on demand from the Actions tab (`workflow_dispatch`).

### Dependencies
`.github/dependabot.yml` opens grouped weekly PRs for npm, pip (`/scripts`) and the GitHub Actions themselves, with minor/patch bumps grouped into one PR to keep review low-effort; major bumps still arrive individually since they're the ones worth actually reading.

## Local development

```bash
npm install
npm run dev       # http://localhost:4321
npm run build     # outputs to dist/
npm run preview   # serve the built dist/ locally
```

To run the sync scripts yourself:

```bash
pip install -r scripts/requirements.txt
python scripts/fetch_publications.py
python scripts/fetch_repos.py
python scripts/fetch_bluesky.py
```

## Deployment

Everything builds and deploys from GitHub Actions — there are a few manual, one-time settings to flip after the first push, because none of them can be set from a file. First: in the repository, go to **Settings → Pages → Build and deployment → Source**, and choose **GitHub Actions** (rather than "Deploy from a branch"). After that, every push to `main` runs `deploy.yml` automatically.

One more one-time setting, needed for `sync-content.yml` to be able to commit its own updates: **Settings → Actions → General → Workflow permissions**, set to **Read and write permissions**.

The Google Scholar sync additionally needs a one-time **self-hosted runner** set up on a machine you control — see [Self-hosted runner setup](#self-hosted-runner-setup) above. No account, API key or secret is needed anywhere in the sync itself; the runner is the only extra infrastructure it costs.

No custom domain is configured — the site serves from `cenk-celik.github.io` as before. Adding one later is just a `CNAME` file plus a DNS record; ask if you want that set up.

## Known limitations

- **Google Scholar sync depends on a self-hosted runner staying online.** No account or registration is needed anywhere, which was a deliberate choice, but it means the publications sync only runs when the machine hosting that runner is on and connected — if it's asleep at 06:00 UTC, that day's run queues rather than firing on time, and picks up whenever the runner next reconnects. Citation counts are otherwise **keep-last-good**: any day Google Scholar can't be reached, direct or via the free-proxy fallback, counts are simply left as they were rather than sourced elsewhere, so every number on the site always traces back to Google Scholar.
