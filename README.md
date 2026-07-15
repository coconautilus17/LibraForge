# LibraForge

> **Note:** This tool is a work in progress. Features, interfaces, and behavior are
> liable to change without notice. AI (Claude) is used heavily in building this project,
> across code, tests, and documentation, under human review and direction throughout.

Self-hosted Audible metadata matching, M4B conversion, Audiobookshelf-style library
organisation, series-wide metadata enrichment, and direct Audible downloading - five
tools in one Docker container, with a vanilla-JS web UI. Every write operation defaults
to a dry run.

![LibraForge Start Here](docs/start-here.png)

---

## Features

Five tools plus a home dashboard, sharing one container and a common view of your
library. See [docs/features.md](docs/features.md) for full detail on every tool,
provider, and setting - this is the short version.

- **Start Here** (`/`) - a one-glance scan of your library: how many books need
  metadata, need conversion, or are ready to organise, with links straight into the
  right tool for each stage and a collapsible guide to the badges and modes you'll see
  elsewhere in the app.
- **Metadata Forge** (`/forge`) - searches Audible (or another provider) and writes
  matched metadata to your files, dry-run first, with a Match Report of every result.
  A Manual Review mode with a live filesystem search lets you load and fix any single
  book by hand; Fix Series bulk-corrects a whole detected series at once; and a
  rule-based Suspicion Report flags likely-wrong matches for a second look, no LLM
  involved.
- **M4B Tool** (`/m4b-tool`) - converts or merges audio into a single M4B. Discovers
  multipart and non-M4B conversion candidates automatically, with results cached on
  disk and a status indicator showing whether that cache is fresh, stale, or still
  building. Flags when `No conversion` (a lossless stream-copy) is safe versus when a
  real re-encode is needed.
- **Folder Forge** (`/organizer`) - plans and applies `Author/Series/Book N - Title`
  destination moves with a dry-run preview and structured review reasons per book. The
  destination layout is driven by a configurable naming template rather than a fixed
  scheme, skip patterns exclude books from a run entirely, and a failed move never
  aborts the rest of the run.
- **Enrichment Forge** (`/enrichment-forge`) - finds a series already in your
  Audiobookshelf library and compiles genre and narrator across every book in it from
  Audible and Goodreads at once, instead of fixing each book one at a time. Explicit
  content evidence is shown but never pre-checked, since neither provider proves a book
  is clean on its own.
- **Library Downloader** (`/library`) - browses your Audible library and downloads
  purchases straight into your library folder, decrypted to standard M4B with chapters,
  metadata, cover, and ASIN intact - no external tooling. Already-owned books are
  flagged, with a per-run or per-book duplicate-handling rule.
- **Settings** (`/settings`) - one page for accounts (multi-account Audible sign-in,
  switch/rename/disconnect), providers (Audiobookshelf, abs-agg, abs-tract), appearance,
  and everything else global.

**Providers:** Audible (direct), Audiobookshelf, abs-agg (LibriVox, Storytel, BookBeat,
Big Finish, and others), and Goodreads/Kindle via abs-tract.

---

## Roadmap

- **Script modularisation** - complex functions split out of `app.js` and `main.py` into
  dedicated, standardised modules with clean interface contracts (the fixer itself is
  already split into `app/fixer/{scoring,parsing,clues,tagging,search}.py`).
- **Mobile-friendly web UI** - responsive layout pass so manual review and run controls
  are usable on a phone.
- **Pipeline unification** - persistent stage stepper across pages, and an optional
  "run full pipeline" mode chaining fixer -> m4b-tool -> organizer automatically.
- **Incremental M4B discovery caching** - today, any change anywhere under a discovery
  root (one new book, one rewritten file) invalidates the *entire* cached search for
  that root, forcing a full re-walk even though per-file probe results still get reused.
  A per-folder diff against the shared library index (already tracked, just not used for
  partial invalidation here) would let an update to one folder skip re-walking the rest.
- **Full provider validation** - end-to-end tests for the abs-agg sources that don't
  have dedicated tests yet: **LibriVox, Storytel, Audioteka, BookBeat, Big Finish, ARD
  Audiothek, Die drei ???**. Confirmed working today: Audible, Audiobookshelf, and (via
  dedicated special-provider detection + tests) GraphicAudio and Soundbooth Theater,
  plus Goodreads and Kindle via abs-tract. The untested ones only go through abs-agg's
  generic keyword search path, with no confirmation that every response shape
  normalises to the shared metadata schema without silent field drops.
- Chapter detection via speech recognition before M4B conversion.
- Unraid Community Apps package.

See [docs/features.md](docs/features.md) for the Suspicion Report, which superseded an
earlier local-LLM advisory review idea, and for the debug tracing already shipped today.

---

## Install

Requires Docker with the Compose plugin. Clone and start - no config needed:

```bash
git clone https://github.com/coconautilus17/LibraForge.git
cd LibraForge
make up
```

Then open **http://127.0.0.1:5056**. That's it - `make up` builds the image, creates the
first-boot data folders, and runs the container as your user so mounted files stay
writable. Without `make`, `docker compose up -d --build` works too (it falls back to a
repo-local `./data/` library and UID/GID `1000`).

**Point it at your library.** By default LibraForge mounts the empty `./data/audiobooks`
and `./data/auth` folders. To use your real library, copy the env file and set the paths:

```bash
cp .env.example .env      # then edit AUDIOBOOKS_PATH / AUDIBLE_AUTH_PATH, and UID/GID if not 1000
make up                   # re-run to apply
```

Connect an Audible account from **Settings → Accounts**, or skip Audible and use
Audiobookshelf / abs-agg as providers. For HTTPS, attach to your reverse proxy network
via `docker-compose.override.yml` (git-ignored).

Common commands: `make up`, `make down`, `make logs`, `make restart`, `make test`
(run `make help` for the full list).

### Run the published image (no clone)

The image on GitHub Container Registry is self-contained - the only thing you
provide is the path to your library. Audible auth and run reports persist in
named volumes, so there is nothing else to set up:

```bash
docker run -d --name libraforge \
  --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:5056:5056 \
  -v /path/to/your/audiobooks:/audiobooks \
  -v libraforge-auth:/auth \
  -v libraforge-reports:/app/reports \
  ghcr.io/coconautilus17/libraforge:latest
```

Or with Compose - download [`docker-compose.dist.yml`](docker-compose.dist.yml) and run:

```bash
AUDIOBOOKS_PATH=/path/to/your/audiobooks \
  docker compose -f docker-compose.dist.yml up -d
```

Then open **http://127.0.0.1:5056** and connect an Audible account under
Settings → Accounts (or skip it and use Audiobookshelf / abs-agg). Upgrade later with
`docker pull ghcr.io/coconautilus17/libraforge:latest`.

### Optional companion services

| Service | Purpose | Required? |
|---|---|---|
| [Audiobookshelf](https://www.audiobookshelf.org/) | Metadata provider via ABS's built-in search API. Create a dedicated API key in ABS Settings → Users → API Keys and add it under Settings → Accounts. | No |
| [abs-agg](https://github.com/Vito0912/abs-agg) | Aggregates metadata from LibriVox, Storytel, BookBeat, Big Finish, and others. Deploy on the same Docker network; set the URL in provider settings. | No |
| [abs-tract](https://github.com/ahobsonsayers/abs-tract) | Goodreads/Kindle metadata fallback for no-match, series-only, or low-score books. Deploy on the same Docker network; set its URL in provider settings. | No |

### Container paths

| Purpose | Path |
|---|---|
| Audiobook library | `/audiobooks` |
| Audible auth directory | `/auth` - active account `/auth/audible-metadata.json`; saved accounts `/auth/accounts/` |
| Scripts | `/app/scripts` |
| Reports and caches | `/app/reports` |

---

## Safety

- All operations default to dry-run. Review before applying, and back up media before
  the first write.
- A dedicated, empty Audible account is recommended for metadata lookups; use a
  real-library account for the downloader.
- The `/auth` directory is mounted **read-write** so the app can add, switch, and
  disconnect accounts. Point `AUDIBLE_AUTH_PATH` at a dedicated directory - not your
  primary audible-cli config - and keep it off untrusted networks.

**Do not expose LibraForge to an untrusted network.** It can write file metadata, move
files, launch conversions, and access your Audible account. There is no built-in
authentication - anyone who can reach the port has full access. Run it behind
[Tailscale](https://tailscale.com/), a VPN, or a reverse proxy with authentication
(e.g. Caddy `basicauth`, Authelia). The default `127.0.0.1` binding keeps it
localhost-only; do not change this without adding access control.

---

## Reporting issues

Found a bug? See [docs/reporting-issues.md](docs/reporting-issues.md): enable debug,
reproduce, attach the JSON report + debug log, and point out the specific failure.

## Development

See [docs/development.md](docs/development.md) for running tests, restarting after
backend changes, and other local-dev notes. Static files (`app/static`, `scripts/`) are
bind-mounted - HTML, CSS, and JS edits are live without a restart.

---

## Credits

LibraForge wraps and builds on:

- **[FastAPI](https://fastapi.tiangolo.com/)** and **[Uvicorn](https://www.uvicorn.org/)**
  - the web framework and ASGI server the whole app runs on.
- **[audible](https://github.com/mkb79/Audible)** (mkb79) - the Audible API client
  behind account sign-in, catalog search, and the Library Downloader's decryption.
- **[mutagen](https://github.com/quodlibet/mutagen)** (quodlibet) - reads and writes
  every audio tag format LibraForge touches.
- **[FFmpeg](https://ffmpeg.org/)** - powers conversion and merging in the M4B Tool.
- **[Audiobookshelf](https://www.audiobookshelf.org/)** - the library server LibraForge
  is designed to complement; the ABS metadata provider, owned-book detection, and
  Enrichment Forge all integrate with it directly.
- **[abs-agg](https://github.com/Vito0912/abs-agg)** (Vito0912) - the optional companion
  service behind the LibriVox / Storytel / BookBeat / Big Finish and other providers.
- **[abs-tract](https://github.com/ahobsonsayers/abs-tract)** (ahobsonsayers) - the
  optional companion service behind the Goodreads/Kindle metadata fallback.

Full dependency list and license details: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

LibraForge itself is licensed under [AGPL-3.0-or-later](LICENSE).
