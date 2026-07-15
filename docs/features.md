# Features

Full detail on every tool. See the [README](../README.md) for a quick overview and
install instructions.

## Start Here (`/`)
Pick a folder and get a one-glance scan summary: how many books need metadata, need
conversion, and are ready to organise. Links through to the right tool for each stage.
A collapsible guide explains Edit and Write modes, Match badges, `metadata.json` vs the
Audiobookshelf Scanner, Report types, the Owned badge, and a suggested end-to-end
workflow through Metadata Forge and Folder Forge.

## Metadata Forge (`/forge`)
Searches Audible (or another provider) and writes matched metadata to your files.

- **Dry-run first**, then enable **Apply** to write. **Backup and cache** on the first
  apply preserves originals and speeds up later runs.
- **Concurrent workers** (v5): parallel Audible search with a per-thread client pool,
  per-query de-duplication, and a persistent chapter-count cache that makes repeat
  discovery near-instant.
- **Write modes:** `smart` (skip the write when embedded tags already match),
  `fill-missing` (only write currently-empty fields), `overwrite` (always write).
- **ASIN aware:** the matched ASIN is embedded in every file; if a file already carries
  an ASIN (tags or `[B0XXXXXXXX]` in the name) it is looked up directly first, and an
  ASIN mismatch flags the book for manual review.
- **Manual Review:** load any book or folder, search Audible manually, and apply per
  book with an explicit `Full metadata` or `Series only` mode. A filesystem search index
  (built in the background, shown as a persistent "Search index: N books" marker) lets
  you jump straight to any book by name instead of browsing folders.
- **Match Report:** the run's results list - one card per book, with score, matched
  identity, and what would (or did) get written. Series-group suggestion cards surface
  here too, with a dedicated filter to view them on their own.
- **Fix Series:** a cross-book bulk-edit dialog for correcting series metadata (name,
  author, genre, narrator, explicit, language) across every book in a detected series
  group at once. Two detection passes group books either by title pattern (no series tag
  yet) or by normalizing existing series-tag variants (trailing space, ", Book N",
  reading-order qualifiers like "(Chronological Order)"), surfaced as group cards in both
  the Suspicion Report and Match Report.
- **Suspicion Report:** a rule-based script pass over completed write matches that flags
  likely-wrong ones (bitrate leaked into a title, duplicated title brackets, redundant
  series prefixes, generic omnibus titles, and more) for a quick second look - no LLM
  involved, cheap enough to run after every apply.
- **Providers:** Audible (direct), **Audiobookshelf** (via its own search API),
  **abs-agg** (LibriVox, Storytel, BookBeat, Big Finish, and others), and **Goodreads /
  Kindle** (via `abs-tract`) as an opt-in fallback for no-match, series-only, or
  low-score books. Goodreads rate-limits aggressively; a circuit breaker opens after
  repeated failures and skips Goodreads/Kindle lookups for a cooldown window rather than
  hammering a blocked upstream. Affected books are flagged with a **GR LIMITED** badge in
  the match report (skipped for rate-limiting, not counted as a genuine no-match), and a
  popup warns if you enabled the fallback with more than 5 search workers, since that's
  what usually trips it.

## M4B Tool (`/m4b-tool`)
Converts or merges audio into a single M4B. Loads existing fixer sidecars automatically,
scans for multipart / non-M4B conversion candidates, and exposes codec, bitrate, and job
count. `No conversion` is safe only when all source streams are AAC with matching sample
rate and channel layout.

Discovery results are cached on disk per (root, fixer script) and reused instantly when
nothing under that root has changed since the last search - a persistent "Discovery
index" marker shows whether that cache is ready, stale (the fixer script changed since
it was last built), or still being built. Editing a fixer script invalidates every
cached search keyed to it, since script logic changes can change how files get grouped.

## Folder Forge (`/organizer`)
Plans and applies `Author/Series/Book N - Title` destination moves with a dry-run
preview and structured review reasons. **Index library and exit** rebuilds the
destination-structure cache on its own. Shares the same Suspicion Report widget as
Metadata Forge (shown above the planned moves) to flag moves worth a second look.

- **Skip patterns:** one pattern per line, matched case-insensitively against the source
  path or inferred metadata; matching books are excluded from the plan entirely.
- **Per-move failure isolation:** a blocked path, permission error, or vanished source no
  longer aborts the whole run - each move fails independently, and a "Moves
  succeeded/failed" summary with a Failed Moves list shows exactly what didn't land.
- **No-sidecars warning:** if a scan finds zero fixer sidecars, Folder Forge asks
  "Fixer was not applied - Continue anyway?" before planning, since move quality for
  multi-file books leans on fixer-written sidecar metadata.
- **Naming template:** the destination path is built from a configurable token template
  (12 tokens, including an ASIN-detect flag and restatement cleanup) instead of a fixed
  scheme, so the folder layout can be adapted to match how you already organise books.

## Enrichment Forge (`/enrichment-forge`)
Finds a series already indexed in your Audiobookshelf library, then compiles genre and
narrator across every book in it from Audible and Goodreads at once, instead of fixing
each book one at a time.

- **Series lookup is ABS-native:** searches series already in your Audiobookshelf
  library index (not a provider search), with tag variants normalized into one entry.
- **Compiled, editable result:** genre is a deduped union across the series and both
  sources, shown as removable chips with a free-text add; narrator is a union you can
  edit if narrators changed mid-series; sequence range is shown for context.
- **Explicit content is a judgment call, not an auto-fill:** evidence from both
  providers is shown alongside the toggle, but never pre-checked - neither provider's
  signal is reliable proof a book is clean, only a hint it might not be. Checking it
  writes `explicit: true` for every included book.
- **Per-book include/exclude** before applying, and a heads-up that Apply only writes
  `metadata.json` - it never edits audio tags, and if Audiobookshelf's "Store metadata
  with item" setting is on, ABS will overwrite it on its next scan.

## Library Downloader (`/library`)
Browse your Audible library and download purchases straight into a mounted folder,
decrypted to standard **M4B** with chapters, metadata, embedded cover, and ASIN intact -
no external tooling. Supports AAX (`activation_bytes`) and AAXC (per-file voucher).
Books already in your library are flagged as **Owned**; a per-run or per-book rule
controls duplicate handling (Keep both / Replace), and an optional pass auto-organises
the downloads when finished.

> **Known issue:** downloads can currently fail due to a temporary issue with Amazon's
> activation API (`activation_bytes`). This is on Amazon's side, not LibraForge's - if a
> download fails, wait a bit and try again.

## Settings (`/settings`)
One consolidated page for everything global: Appearance, Title noise, Publishers,
Library, Reports (retention policy), Accounts, Audiobookshelf, Goodreads/Kindle,
Developer, and sidecar cleanup. The gear icon in the header links here from every page;
the old `/auth-setup` URL still works and redirects to the Accounts section.

**Accounts:** guided Audible OAuth sign-in - no CLI tools. Connect **multiple accounts**,
each with a recognisable name, and **switch between them in one click**, rename them, or
**disconnect** cleanly (deregisters the device with Audible, then removes the login;
offers retry or local-only delete if Audible is unreachable). The active account is
shared by every tool.

**Audiobookshelf / abs-agg:** paste an Audiobookshelf API key (create one in ABS
Settings → Users → API Keys) into the masked field and click **Save and verify**; the
key is stored server-side and never shown back in the browser. Use **Remove key** to
delete it with one click. ABS is also what makes the Library Downloader's "already
owned" detection instant. The key can alternatively be set once via the `ABS_API_KEY`
environment variable (an env-set key is managed by the operator and cannot be removed
from the UI).

## Container paths

| Purpose | Path |
|---|---|
| Audiobook library | `/audiobooks` |
| Audible auth directory | `/auth` - active account `/auth/audible-metadata.json`; saved accounts `/auth/accounts/` |
| Scripts | `/app/scripts` |
| Reports and caches | `/app/reports` |

## Debug tracing

Opt-in (`app/debug_trace.py`, toggleable in Settings), writes to a log file/stderr. A
raw log is the intended form for this, not a UI feature, so no further work is planned
there. See [reporting-issues.md](reporting-issues.md) for how to use it when filing a bug.
