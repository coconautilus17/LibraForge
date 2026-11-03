# Architecture

How LibraForge is put together. This page is for people changing the code; the
[feature guide](../features.md) describes what each tool does for a user.

## The shape of it

One FastAPI application (`app/main.py`) serves a vanilla-JS front end and a JSON API, and
starts long-running work in the background. There is no database: state is plain files on
the mounted volumes plus a few in-memory structures that are rebuilt on start.

```
browser ──HTTP──> app/main.py (FastAPI, uvicorn)
                    │  serves app/static/*.html + *.js (one page per tool)
                    │  /api/* handlers
                    │
                    ├── starts a worker thread per run ──> RunState (in memory)
                    │        │
                    │        ├── subprocess: scripts/audible-metadata-fixer-v5.py   (Metadata Forge)
                    │        ├── subprocess: scripts/organize-audiobooks-by-metadata-v3_13.py (Folder Forge)
                    │        ├── subprocess: scripts/review-libraforge-report.py     (Suspicion Report)
                    │        ├── subprocess: m4b-tool / ffmpeg                       (M4B Tool)
                    │        ├── subprocess: python -m app.chaptering_runner         (Chapter Forge: Hybrid, Full)
                    │        ├── in-process thread: one Audible API lookup           (Chapter Forge: Audible chapters)
                    │        └── in-process thread: downloads                        (Library Downloader)
                    │
                    └── reads and writes files: audio tags, libraforge.json sidecars,
                        reports/, settings/, Audiobookshelf over its HTTP API
```

## Code layout

| Path | What lives there |
|---|---|
| `app/main.py` | Every route, request model and run worker (about 9,600 lines, 107 handlers). Also the report parser that turns script output into progress and stats. |
| `app/static/` | One HTML file and one JS file per tool (`index.html` + `app.js` is Metadata Forge; `organizer.*`, `m4b-tool.*`, `chapter-forge.*`, `enrichment-forge.*`, `downloader.html`, `settings.html`, `start-here.html`), plus shared `ui-common.js`, `ui-preferences.js`, `pattern-settings.js` and `style.css`. No build step and no framework. |
| `scripts/` | The standalone programs the UI runs as subprocesses, and one-off maintenance scripts (see below). |
| `app/fixer/` | Logic extracted from the Metadata Forge script so it can be unit-tested: `parsing` (text and number parsing), `clues` (search clue building), `scoring` (candidate scoring and metadata assembly), `search` (Audible / ABS / abs-agg / abs-tract clients), `tagging` (tag-writing primitives). |
| `app/chaptering.py`, `chaptering_runner.py` | Chapter Forge detection (silence, keyword and speech-recognition passes) and the subprocess entry point. |
| `app/enrichment*.py`, `genre_*.py`, `goodreads_shelves.py`, `explicit_evidence.py`, `source_matching.py` | Enrichment Forge: source lookups, the genre vocabulary, voting, collections, explicit evidence. |
| `app/audiobook_guild.py` | Metadata Forge's Audiobook Guild source: the store's authors, search and runtimes. |
| `app/abs_client.py` | Direct Audiobookshelf API sync (used by the fixer and by Enrichment Forge). |
| `app/*_policy.py`, `author_names.py` | User-editable pattern sets (title noise, publishers, author-name scheme) and the code that applies them. |
| `app/library_index.py`, `folder_scan_cache.py`, `conversion_*.py` | Library walking and the caches built on it. |
| `app/debug_trace.py` | Opt-in tracing decorators for code that chooses, alters or scores data. |
| `app/json_files.py` | `write_json_atomic`: every cache, policy and state file is saved through it (a temporary file swapped into place). |

## The two big scripts

`audible-metadata-fixer-v5.py` (about 6,600 lines) and
`organize-audiobooks-by-metadata-v3_13.py` (about 6,400 lines) predate the `app/` modules
and are still the engines of Metadata Forge and Folder Forge. They run as separate
processes: `app/main.py` builds the command line, streams stdout into a log file, and
parses it line by line into a `RunState`. The scripts are named by version, and the app
picks the alphabetically latest `audible-metadata-fixer*.py` and `organize-audiobooks*.py`
in `SCRIPTS_DIR` (`discover_scripts()` and `default_fixer_script()`). The fixer's major
version (`-vN` in the name) gates which flags the app passes.

The scripts import from `app/` (the fixer from `app.fixer.*`, `app.abs_client`,
`app.publisher_policy` and more; the organizer from `app.title_noise_policy`,
`app.sidecar_ownership`, `app.epub_metadata`, `app.abs_client` and others). A script has to
work both inside the container, where `app` is importable, and when run on its own, so
shared modules keep that constraint and the scripts add the repo root to `sys.path` as a
fallback. A change to a shared module therefore changes both the web app and the scripts.

Because the scripts have hyphens in their names they are not importable; tests load them
by path (see [testing](testing.md)).

## A run, end to end

1. The page POSTs a request model (for example `RunRequest` to `/api/runs`).
2. `start_run` allocates a run id, creates a `RunState` in the in-memory registry and starts a
   daemon thread (`run_script_worker`).
3. The worker calls `build_command`, then `stream_process_output`: it starts the subprocess,
   writes `reports/<id>.log.txt`, and feeds each output line to a parser that updates the
   `RunState` (current file, percent, phase, stats, per-category file lists).
4. The page polls `/api/runs/<id>` for progress.
5. When the process ends, the worker writes `reports/<id>.report.json` (schema version 2)
   and prunes old reports according to the retention policy.

Runs live in memory only; after a restart the report and log files are what remain. Chapter
Forge and the downloader follow the same pattern with their own workers; the
Enrichment Forge whole-library run keeps its own resumable state (see
[data and files](data-and-files.md)).

## Dry run is the default

Request models default to the safe choice: `dry_run=True` on `SidecarCleanupRequest`,
`apply=False` on `RunRequest` (Metadata Forge) and `OrganizerRunRequest` (Folder Forge). Keep
that when adding a write path (the same rule is in [CONTRIBUTING](../../CONTRIBUTING.md)).

## Providers

Search providers sit behind `app/fixer/search.py` and `app/manual_candidates.py` (the shape
every Manual Review result row shares). Audible is queried directly: `get_catalog_client()`
returns the logged-in `audible.Client` when an auth file exists, else `PublicAudibleClient`,
which calls the same catalog endpoints with no login. The "Audible public catalog" provider
forces the public client for one marketplace (`PUBLIC_AUDIBLE_DOMAINS`): the UI sends
`audible_region`, and runs pass `--audible-public-region` to the fixer. Audiobookshelf,
abs-agg and abs-tract are HTTP services whose responses are normalised to one metadata
shape. Special publishers (GraphicAudio, SoundBooth Theater) are recognised by
`detect_special_provider()` in `app/fixer/search.py`, using the catalog in
`app/publisher_policy.py`, and routed to the matching abs-agg endpoint. Some abs-agg
providers need a path parameter (`ABS_AGG_REQUIRED_PARAMS` in `main.py`).

Goodreads is read directly from its public XML (`app/goodreads_shelves.py`, shared with
Enrichment Forge's shelves): `abs_tract_search` routes the `goodreads` provider to its
`search_books` (search, then up to 3 book pages) and only Kindle still goes through
abs-tract. Goodreads is rate-limited upstream, so `abs_tract_search` wraps both in a
circuit breaker (`_ABS_TRACT_BREAKER*` in `app/fixer/search.py`): after repeated failures it stops
calling for a cooldown instead of hammering a blocked service.

The order inside `search_item` (scripts/audible-metadata-fixer-v5.py): Audiobook Guild
for its authors (`audiobook_guild_search`, final when full), the special publishers through
abs-agg (`detect_special_provider`), the embedded ASIN (`lookup_asin`, final only when the
runtime agrees), the Audible title+author search and keyword queries (`audible_searches`,
or `abs_search` in ABS mode), then the fallbacks below while the match isn't full, and
last the review gates (min score, ambiguity, missing title or author). Audible's
`catalog/products` search is filtered by where the request comes from (and, signed in, by
the account), while every lookup by ASIN (`catalog/products/{asin}`, `?asins=`) is not;
the two fallbacks exist to turn a hidden book into an ASIN.

The first fallback, `find_series_member_match`, reads the book's own series: `series_asins_for_book`
picks the series ASIN from any result naming the file's series (or the one its title names;
with none, one search for that series name), `audible_series_members` reads the series'
listing (`catalog/products/{series_asin}?response_groups=relationships`, cached per run) and
`audible_lookup_many` fetches the members (`catalog/products?asins=`, 50 a request). Lookups
by ASIN aren't limited by the requester's country the way search is.

AudioSilo's community database is the second fallback, after the series and before Goodreads
(`find_audiosilo_match` in the fixer, `audiosilo_search` in `app/fixer/search.py`). It is
searched through its Audiobookshelf-provider endpoint (`/abs/search`) at the URL from
`audiosilo.json` (Settings → AudioSilo; meta.audiosilo.app by default), which every run
passes as `--audiosilo-url`. The pick's ASIN is looked up on Audible (`lookup_asin`, the
embedded-ASIN step's lookup), because Audible's search hides listings that can't be sold
in the requester's country while its ASIN lookup does not. `AUDIOSILO_PACER` paces and
pauses every AudioSilo call, the fallback's and Enrichment Forge's alike.

Audiobook Guild, a store selling a short list of self-published authors, is read from its
public Shopify storefront (`app/audiobook_guild.py`). Its whole catalog (about 800 books,
1.3 MB) ships with LibraForge in `app/data/audiobook-guild-catalog.json`, every book with
its runtime (rebuilt with `dev/tools/build_guild_catalog.py`). It is refreshed from
`products.json` in four requests at most weekly and kept as `audiobook-guild-catalog.json`
in the reports folder, whichever of the two is newer being used; the author list comes from it, and
a book is searched there locally (its author's books, ranked with the matcher's
`title_evidence_score`, its own number first). A book the store added or changed since
needs its product page read once for its runtime, which is then kept in the same file. A book by
one of those authors is matched there before any other source (`audiobook_guild_search`
in `app/fixer/search.py`, scored like any candidate), and a full match there skips the
ASIN lookup and Audible search, with the file's own series name written once every
decision is made (`local_series_name` in `app/fixer/scoring.py`). Its requests go through
httpx: the store answers urllib with 429 "local_rate_limited" however paced. Even httpx
gets the odd 429, so a failed request is tried once more; a product page that still fails
fails the whole search (a candidate without its runtime can lose to the wrong book), and
the book goes on to Audible.

## Where decisions live

- Scoring a candidate against a local book: `app/fixer/scoring.py`.
- Parsing a folder or file name into clues: `app/fixer/parsing.py`, `app/fixer/clues.py`.
- Which genre wins in Enrichment Forge: `app/genre_voting.py` (source weights are in
  `SOURCE_WEIGHTS`; a main genre needs weight 2).
- What a destination path looks like: the naming-template functions in the organizer script
  (`NAMING_TOKEN_NAMES`, `render_naming_template`, `validate_naming_template`).
- Whose book a folder-level sidecar describes: `app/sidecar_ownership.py`, shared by the
  fixer and Folder Forge.
