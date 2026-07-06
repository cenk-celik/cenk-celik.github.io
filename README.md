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
Google Scholar has no official API, so this scrapes the public profile via the [`scholarly`](https://github.com/scholarly-python-package/scholarly) library. Google periodically blocks or rate-limits this — that happens to every academic site that automates Scholar, not just this one. Per your instruction, the script is **keep-last-good**: on any failure it logs a warning and exits without touching `publications.json`, so the site simply keeps showing the last successful sync until the next scheduled run succeeds. Matching is done by normalised title, and any manually-set `selected`, `doi`, `pubmedUrl`, `preprintUrl` or `type` is always preserved across re-syncs.

### Software stats (`scripts/fetch_repos.py`)
Plain GitHub REST API calls (unauthenticated is enough for a handful of public repos; in Actions, the built-in `GITHUB_TOKEN` is used automatically to raise the rate limit). Same keep-last-good behaviour per repository.

### Bluesky feed (`scripts/fetch_bluesky.py`)
Bluesky's public AT Protocol AppView endpoint (`public.api.bsky.app`) needs no login or token for a public profile. The script snapshots the latest posts into `src/content/bluesky/cache.json`, which the homepage reads at build time — so the homepage never makes a live network call itself (faster, and immune to Bluesky being briefly down). Reposts are shown with a small "reposted from" label rather than filtered out, since original posts are infrequent enough that filtering them out could leave the section thin.

### Schedule
`.github/workflows/sync-content.yml` runs all three scripts once daily and commits `src/content/{publications,repos,bluesky}` if anything changed — that commit lands on `main` and triggers `deploy.yml`, so the live site picks up new papers, updated stars or fresh posts with no manual step. It can also be run on demand from the Actions tab (`workflow_dispatch`).

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

Everything builds and deploys from GitHub Actions — there is exactly **one manual, one-time setting** to flip after the first push, because it can't be set from a file: in the repository, go to **Settings → Pages → Build and deployment → Source**, and choose **GitHub Actions** (rather than "Deploy from a branch"). After that, every push to `main` runs `deploy.yml` automatically.

One more one-time setting, needed for `sync-content.yml` to be able to commit its own updates: **Settings → Actions → General → Workflow permissions**, set to **Read and write permissions**.

No custom domain is configured — the site serves from `cenk-celik.github.io` as before. Adding one later is just a `CNAME` file plus a DNS record; ask if you want that set up.

## Known limitations

- **Google Scholar sync is inherently a little fragile.** There's no official API; if Google blocks the scraper for a while, publications simply stop updating until it lets up again — nothing breaks, nothing needs fixing, it just catches up next run.
