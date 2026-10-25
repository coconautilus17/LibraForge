# Data and files

LibraForge has no database. Everything it remembers is a file, either next to your audio, in
the reports folder, or in the settings folder. This page lists what writes each file, so you
can tell state from cache and know what is safe to delete.

## Next to the audio

| File | Written by | Purpose |
|---|---|---|
| `libraforge.json` | Metadata Forge, Manual Review, Chapter Forge | Folder-level sidecar for a grouped book or a file alone in its folder. |
| `<file>.libraforge.json` | the same | Per-file sidecar for a loose file that shares its folder with other books. |
| `metadata.json` / `<file>.metadata.json` | Metadata Forge, Manual Review | Audiobookshelf's own metadata file. Same folder-level vs per-file rule as above. Enrichment Forge no longer writes it when Audiobookshelf is configured and removes old copies it finds. |
| `<folder name>.chapter-count-cache.json` (inside the book folder) | Metadata Forge | Persistent chapter-count probe cache (see `CHAPTER_COUNT_CACHE_SUFFIX` in the fixer). |
| `*.libraforge-chapters.cue`, `.srt`, `*.libraforge-transcript.txt`, `*.libraforge-ai-review.md` | Chapter Forge | Saved chapter output. |

The sidecar path rule is `get_libraforge_path()` in the fixer: folder-level
`libraforge.json` when the book is a group or alone in its folder, otherwise the per-file
form (`LIBRAFORGE_SUFFIX = ".libraforge.json"`). A folder-level file must only be read or
written for the book it describes; `app/sidecar_ownership.py` decides that and is shared by
the fixer and Folder Forge, because a shared "unsorted" folder can hold several books.

### What a sidecar contains

A JSON object with `schema_version` (currently 2 for fixer-written files) and these sections,
each written by the step that owns it:

- `marker`: that the book was processed and how (`processed_at`, `applied`, `mode`,
  `edit_mode`, `score`, `source_file`, the matched `audible` block, `local_before`,
  `restored_at`). The fixer uses it to skip already-applied books, except a
  `series_only` apply (matched only to another book of the series) and a
  `different_edition` apply with no real ASIN of its own: both are searched again.
- `backup`: the original tags (`format_tags`) captured before the first write, with
  `created_at`, `source_file` and `duration_minutes`. `--restore-metadata` reads this.
- `sidecar`: the metadata plan for an M4B conversion (`book`, `audible`, source file list,
  audio stream summary).
- `scan_cache`: the ASIN the Start Here scan found for the book (`scan_cache.asin`), kept in its own key so the organizer's fields are untouched.
- `chapter_forge`: the chapter list Chapter Forge saved, with the settings that produced it.

Older versions kept `marker` and `backup` in separate files; the fixer migrates those into the
sidecar the first time it reads them.

## In the reports folder (`REPORTS_DIR`, `/app/reports`)

| File | Purpose |
|---|---|
| `<run id>.log.txt` | Raw output of one run. |
| `<run id>.report.json` | Structured result of one run (`schema_version` 2): status, phases, stats, per-file items, categories, manual-review items. |
| `m4b-discovery-cache.json` | M4B Tool discovery results, keyed by (root path, fixer script name) and invalidated when the script file's modification time changes. |
| `folder-scan-cache.json` | Start Here scan results, keyed by path and ignored folders (`FOLDER_SCAN_CACHE_VERSION`). |
| `audible-store-genres.json` | Audible's foreign-store genre names with their English names and top-level category (`app/store_genres.py`), built from each store's category tree and refetched monthly by Enrichment Forge. Safe to delete. |
| `organizer-structure-cache.json` | Folder Forge's picture of the destination library (`DEFAULT_STRUCTURE_CACHE`). It is stamped with the naming template that built it. |
| `.disk-asin-cache.json` | Each file's embedded ASIN, keyed by path and modification time, so the library-wide duplicate-ASIN guard only re-probes new or changed files. Override the path with `DISK_ASIN_CACHE_PATH`. |
| `enrichment-batch.json` | Enrichment Forge whole-library run: compiled results, saved after every unit so it can be resumed. |
| `chapter-preview-cache/` | Audio clips for the Chapter Forge preview player. |
| `.install-state.json` | First-run state: fresh install or upgrade, and whether the author-names notice was seen (`app/install_state.py`; path from `LIBRAFORGE_STATE_FILE`). It is a dotfile so report pruning never touches it. |

Report files are pruned by the retention policy in `retention.json` (maximum age and/or
maximum count; both off by default). Everything in this folder except `.install-state.json`
can be deleted: caches rebuild, and reports are only history.

## In the settings folder

Settings live in `LIBRAFORGE_SETTINGS_DIR` (`/app/settings`, a named volume, in the
published image), or in `config/` next to the shipped defaults when it is not set
(`app/settings_paths.py`).

| File | Purpose |
|---|---|
| `abs.json`, `abs-agg.json`, `abs-tract.json` | Connection settings for Audiobookshelf, abs-agg and abs-tract. The Audiobookshelf key is stored server-side and never sent back to the browser. |
| `retention.json` | Report retention policy. |
| `title-noise.local.json`, `publishers.local.json`, `author-names.local.json` | Your custom patterns and which shipped patterns you switched off. |

The shipped defaults (`config/title-noise.default.json`, `publishers.default.json`,
`author-names.default.json`) are part of the image and are replaced on upgrade, which is why
user changes go in separate `.local.json` files.

## Audible accounts

`/auth/audible-metadata.json` is the active account's auth file; saved accounts are one
`<user_id>.json` each under `/auth/accounts/`. The directory is mounted read-write because
the app adds, switches and deregisters accounts. Never commit these.

## In memory only

- The run registry (`RunState`). A restart loses running state; the log and report files
  remain.
- The shared library index (`app/library_index.py`): a background walk of the library that
  records, per book folder, a signature of its direct children (`folder_listing_signature`)
  so other features can tell what changed. The M4B discovery cache compares these
  signatures to decide whether a cached search is still fresh.
- The Manual Review search index, rebuilt in the background and shown as "Search index: N
  books".

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `SCRIPTS_DIR` | `app/main.py` | Where the fixer and organizer scripts are (default `/app/scripts`). |
| `REPORTS_DIR` | `app/main.py` | Reports and caches (default `/app/reports`). |
| `AUDIOBOOKS_ROOT` | `app/main.py` | Library root inside the container (default `/audiobooks`); path checks keep requests under it. |
| `LIBRAFORGE_SETTINGS_DIR` | `app/settings_paths.py` | Settings folder; falls back to `config/`. |
| `ABS_URL`, `ABS_API_KEY` | `app/main.py`, scripts | Default Audiobookshelf connection; a key set this way cannot be removed from the UI. |
| `DISK_ASIN_CACHE_PATH` | fixer script | Location of `.disk-asin-cache.json`. |
| `LIBRAFORGE_STATE_FILE` | `app/author_names.py` | Location of `.install-state.json`. |
| `LIBRAFORGE_DEBUG`, `LIBRAFORGE_DEBUG_FILE`, `LIBRAFORGE_DEBUG_CATEGORIES` | `app/debug_trace.py` | Turn tracing on, set its log file and categories without the UI. |
| `AUDIOBOOKS_PATH`, `AUDIBLE_AUTH_PATH`, `UID`, `GID` | compose files | Host paths and the user the container runs as. |
| `LIBRAFORGE_IMAGE_TAG`, `LIBRAFORGE_PORT` | `docker-compose.dist.yml` | Which published image and which host port. |
