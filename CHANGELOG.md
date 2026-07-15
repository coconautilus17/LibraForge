# Changelog

All notable changes, tracked by PR. This file wasn't kept in sync with the
GitHub Releases for v0.1.0-v0.2.1 (see the Releases page for those); v0.2.2
onward is tracked here going forward.

---

## v0.2.4 (2026-07-15)

### 2026-07-14 to 07-15 (PR #233-249)
- Unified library index: Manual Review's "Load any book" search, the M4B Tool's
  multipart/non-M4B discovery, and Folder Forge's dashboard scan now share one
  folder-existence + per-folder-signature index instead of three separate,
  inconsistent staleness checks. Fixed two real bugs this uncovered: Folder Forge's
  too-coarse fingerprint could keep serving stale dashboard tiles for up to an hour
  after a real change, and it was blind to a book added or changed in a deep
  subfolder; Folder Forge's scan results now also persist to disk across restarts.
  GraphicAudio/SoundBooth Theater matches losing publisher, or getting a fake
  placeholder ASIN, fixed on both the automated fixer path and interactive search,
  plus a separate copy of the same bug in the metadata comparison table.
  Release-review hardening pass: grouped-book sidecar writes losing their
  written_fields record under `--metadata-json-only`, the M4B discovery cache
  serving stale results for multi-disc books, Enrichment Forge's catalog fetch now
  cached (30s TTL) instead of re-fetched on every search keystroke, and internal
  de-duplication of the book-folder walk and the abs-agg provider fallback table.
  Manual Review search index: fixed a false "library change detected" report on
  every background walk cycle even when nothing changed, the persistent "Search
  index: N books" marker disappearing on every search (it read the wrong field
  from the response), and a cold-start race that could briefly report the index
  "ready" with 0 books before the first walk finished. Added a persistent
  discovery-cache status indicator (ready/stale/building) to the M4B Tool.
  Start Here's tool nav cards de-boxed and enlarged to match how the same icons
  look on their own tool pages.
- Docs: overhauled the README into a short overview plus `docs/features.md` and
  `docs/development.md`; fixed Enrichment Forge being entirely undocumented,
  "Suspect Report" being used throughout when the UI actually says "Suspicion
  Report," and Fix Series being unmentioned; added a Credits section; swapped in
  an optimized icon set.

### 2026-07-13 (PR #232)
- Organizer: shipped a customizable naming template (12 tokens including
  author/series/order/title/edition/narrator/publisher/year/ASIN, an ASIN-detect
  flag, and `{filename}`/`{original}` tokens for tidying a loose single-file name
  without a full scheme change), with a live preview and worked examples,
  defaulting to the existing ABS structure scheme unchanged.

### 2026-07-12 (PR #223-228)
- Settings redirect for a missing Audible/ABS connection now explains what's
  missing and auto-switches to whichever provider is actually connected when one
  exists as a fallback.
- Fixed Enrichment Forge's genre fallback (local genres union, removed a
  debug-mode bypass) and removed a "Show developer links" debug toggle that
  silently disabled connection/auth gating across the whole app.
- Manual Review: added a search box backed by a background-built filesystem
  index, so any book in the library can be found and opened by name instead of
  only the ones in the current report.

### 2026-07-11 (PR #207-222)
- Enrichment Forge: several rounds of mockup-parity and field-structure fixes
  (genre field click bug, narrator/sequence/explicit field grouping, sequence
  range, genre add, source-search progress, provider fallbacks, search-collapse
  and book ordering) bringing the page to its approved visual design.
- Style crispness pass: tightened border-radius, spacing, and type scale onto
  shared design tokens; recolored the default dark/light theme; added a "Wood"
  dark surface option; audited every theme x surface x accent combination for
  contrast.
- Collapsible advanced run settings on Metadata Forge and Folder Forge, and side
  navigation on the M4B Tool matching the other tool pages.
- Fixed Match Report's series-grouping cards vanishing after changing the status
  filter (added a dedicated "Series groups" filter), and reworked/completed the
  Start Here badge legend (fixed a stale cross-reference, added
  previously-undocumented badges, added missing "critical" severity styling).

### 2026-07-10 (PR #202-206)
- Patched known Alpine/Python CVEs.
- Added the Fix Series cross-book bulk-edit dialog (name, author, genre,
  narrator, explicit, language) with two series-detection passes (title-pattern
  and normalized-tag-variant grouping), surfaced in both the Suspicion Report and
  Match Report.
- Hardened file and URL handling: cover lookups restricted to the configured
  library, `file://` cover URLs only accepted from LibraForge-managed uploads,
  covers capped at 10 MiB and validated as real JPEG/PNG, service URLs must use
  `http://`/`https://`.
- Shipped the Enrichment Forge page: ABS series discovery, two-phase concurrent
  Audible/Goodreads search, genre/narrator union compilation with
  explicit-content evidence, and a partial-merge metadata.json writer.

### 2026-07-09 (PR #187-199)
- Fixed organizer title corruption from bracketed narrator/series annotations
  (3-segment bracketed filenames, redundant "(Series Book N)" parentheticals,
  nested parentheticals, bare "(Book N)"/"(Vol. N)" annotations) and a stray
  ampersand-truncation regression from the same pass.
- Fixed batch runs silently reprocessing manually-applied books (an incomplete
  written_fields list was trusted for grouped/JSON-sidecar books).
- Fixed grouped books' recovery flow resolving the wrong meta_target.
- Docs: fixed the v0.2.3 CHANGELOG format.

---

## v0.2.3 (2026-07-09)

### 2026-07-08 to 07-09 (PR #177-185)
- Fixer/Manual Review: the report's "local"/current display was still diverging from
  Manual Review after everything below - root cause was two independently-written
  lookups that only mostly agreed; the report now delegates to the exact same
  sidecar/marker lookup Manual Review uses, so they can't diverge again. Also fixed
  grouped multi-file books' representative file leaking a bonus track's own chapter
  title/track number as if they were the book's title/series sequence, and the Match
  Report card hardcoding blank "Local" values for Year/ASIN/ISBN since it was first
  built (unrelated bug, same visible symptom)
- Suspicion Report: added a search box + flag-type filter, shared by the fixer and
  organizer reports
- Manual Review: Edit dialog widened to 75% of viewport and given a settings-style
  side nav on the Metadata Forge page for jumping between sections; Edit dialog cover
  search simplified to a clickable cover + title (no more separate "use this cover"
  button), packed 4-7 covers per row instead of 2, and added Language/Explicit tag
  fields (written to metadata.json only, no existing tag convention covers them)
- Organizer: added a per-item "Exclude from organizer run" button on the moves
  report; fixed the real cause of run settings (e.g. "Progress every N items") being
  silently ignored - the Start button passed its own click event as the request body
  instead of the form's collected values; fixed a page-reload race that could
  silently swap in a stale prior run's progress/log after a fresh run was already
  started
- Library Downloader: added a status indicator for whether account activation bytes
  are cached, with a one-click-copy recovery command when they're not
- UI: added a settings-style side nav to the Metadata Forge page; fixed the sticky
  side-nav (Settings and Metadata Forge) rendering partly hidden behind the sticky
  header at every scroll position

### 2026-07-07 (PR #173-176)
- Manual Review: clearing an Edit dialog field was silently ignored on apply (wrote
  the old matched value back into every field instead of respecting the clear);
  added a uniform Fill/Overwrite field policy across all dialog fields; fixed
  multi-genre input collapsing into one malformed combined tag instead of separate
  values
- Library Downloader: fixed CloudFront-blocking downloads by preferring a per-book
  decryption voucher over account activation bytes (the account's activation bytes
  are blocked at the source; the voucher path never touches that endpoint);
  downloads now run 3-at-a-time like audible-cli instead of one at a time; the
  end-of-run report shows each item's actual decrypt method and outcome instead of
  just aggregate counts
- UI: sticky header, a release version tag linking to its GitHub notes, and a
  Settings About section

### 2026-07-05 to 07-06 (PR #158-172)
- Fixer/Manual Review: comparison-card "Current" data was partly built from
  matcher-only clues (title/series/author/book_number after path- and
  folder-name overrides meant only to help find the right catalog match), so a
  rejected or stale match could show a guessed identity instead of the file's real
  tags. Replaced with a pure tag-only reader used everywhere "current state" is
  displayed or persisted to the marker. Along the way: genre, subtitle, summary,
  isbn, asin, and publisher were silently dropped or misreported blank in the marker
  (genre alone was wrong on 85 of 99 real books tested) because the writer's own
  "leave tag alone if match has nothing" behavior wasn't mirrored when recording
  what got written; fill-missing mode also overwrote genre/subtitle instead of
  respecting existing values; and a cleanly-skipped file (already correctly matched
  by a prior run) showed stale pre-fix data as if it were current
- Suspicion Report: added missing-title/author/series flags (high severity) for a
  technically-correct match that's just missing that field; duplicate-identity
  (cross-item) cards now show real identifying titles/paths instead of an empty
  "(cross-item)" card; fixed a structural no-op that meant the "latest report"
  lookup could never actually exclude organizer reports from the fixer's own view,
  and a false error logged on every report load before its first Suspicion Report
  existed; added a Goodreads circuit-breaker badge and end-of-run warning when a run
  gets rate-limited
- Organizer: ported the fixer's part-sequence/leading-ordinal grouping so a folder
  holding both a chapter sequence and a leftover merged edition groups correctly
  instead of exploding every chapter into its own move
- Docs: expanded README, added an issue-reporting guide

---

## v0.2.2 (2026-07-05)

### 2026-07-04 to 07-05 (PR #150-154)
- Organizer: ported the fixer's skip-pattern matcher (matching UI, `--skip-pattern`);
  the apply loop had zero error handling - one bad move (blocked path, permission
  error, vanished source) crashed the whole run and silently dropped every remaining
  planned move. Now isolates per-move failures with a "Moves succeeded/failed"
  summary and a Failed Moves list; detects a scan with zero fixer sidecars and warns
  before planning ("Fixer was not applied - Continue anyway?"), since multi-file
  metadata quality leans on fixer-written sidecars; moved Suspicion Report above
  Planned Moves so it isn't buried after a real run
- Fixer: fixed several matcher regressions found via a real run against
  `_unorganized` - a candidate missing sequence data entirely could still reach
  auto-write confidence via title+duration+author agreement alone; a same-series
  numbering-scheme override ignored sequence disagreements regardless of gap size;
  a coincidental substring series name (same author, different series) let its raw
  similarity ratio carry the score past the write threshold; a common release
  naming convention (`001 Author - Book N - Chapter X.mp3`, bare space after the
  index) was never recognized as a multi-part group, and once combined with a
  merged single-file edition in the same folder, exploded every chapter into its
  own wrong match; a loose file sitting directly in the scan root could have its
  title corrupted into the literal scan-root folder name
- Docs: CHANGELOG and README brought up to date against current features

### 2026-07-04 (PR #133-149)
- Library Downloader: fixed the CloudFront/activation-bytes rate-limit bug at its root -
  account activation bytes are now fetched once per run instead of once per book, cached
  (including a failed fetch) and persisted to the auth file, so a batch of AAX titles no
  longer trips Audible's abuse protection; download-run leak fixed (runs now pop from the
  in-memory dict and write a final report like the other three workers); known-issue
  notice made visible, styled red, heading fixed
- Start Here: added a collapsible legend/guide covering Edit modes, Write modes, Match
  badges, `metadata.json` vs the Audiobookshelf Scanner (with a 6-source screenshot),
  Report types, the Owned badge, and a step-by-step Suggested Workflow through the full
  Metadata Forge + Organizer pipeline
- Settings: fixed `#accounts` (and every "Set up auth ->" link, plus the `/auth-setup`
  redirect) landing users deep in the Publishers list instead of the Accounts section -
  the native anchor scroll fired before the async Publishers/Title-noise lists finished
  rendering and growing the page; now re-applied after each list loads
- Fixer: dramatized-adaptation detection made title-aware, language penalty on
  non-English matches, ASIN search given priority, multi-part grouping now prefers
  explicit part markers over chapter count and no longer overrides a veto with the
  chapter-count heuristic
- Docs: README discloses WIP status and heavy AI involvement; Planned section corrected
  against verified current state

### 2026-07-02 to 07-03 (PR #130-132)
- Organizer/Fixer: fixed multi-file grouping to recognize part numbers embedded
  mid-filename, not just trailing ones; fixed metadata cross-contamination between
  distinct books sharing a folder-level `libraforge.json`
- Manual Review: cover extraction now reads the real embedded cover tag instead of
  ffmpeg's first video stream (fixes wrong covers on some files)

---

## Previously released (v0.1.0 - v0.2.1)

Everything below was already shipped in a tagged GitHub Release before this
file started tracking versions; kept for history. See the Releases page for
the actual per-version release notes.

### 2026-06-30 to 07-01 (PR #123-129)
- Suspect Report: new review-script pass (`review-libraforge-report.py`) that flags
  likely-wrong matches after a run - bitrate tokens leaked into titles, ABS-style
  duplicated title brackets, redundant series prefixes, generic omnibus titles, and more
  - surfaced through a shared UI widget on both Metadata Forge and Folder Forge
  (Organizer gets its own new detections on top); manual review performance improved via
  script filtering and caching
- Organizer: fixed several title-source bugs
- Manual Review: display fixes
- Settings: report retention (max age / max count) settings added

### 2026-06-29 to 06-30 (PR #95-122)
- Providers: Goodreads and Kindle (via `abs-tract`) added as opt-in fallback providers
  for no-match/series-only/low-score books, with request throttling and a shortened
  circuit-breaker cooldown after early rate-limiting; Goodreads results now surface
  correctly in reports
- Fixer: cross-series same-author match fix, genre field propagated through all
  candidate providers and the UI (filtering out the generic "Audiobook" label), smart-skip
  made provider-aware, fill-missing no longer preserves fraction series sequences (e.g.
  `1/1`), run paths fixed to be relative
- Match Report: new interactive widget with instant load, improved score badges, and a
  Goodreads filter
- Debug tracing (P1-P7): full `DebugTrace` infrastructure - ALTER/CHOOSE/SCORE decorators
  wired onto every normalization, clue-extraction, query-building, scoring, and
  write-path function; subject tracking; `--debug`/`--trace` CLI flags
- Fixer modularization (M1-M5): the ~9,000-line monolith split into importable
  `app/fixer/{parsing,clues,scoring,tagging,search}.py` modules, used by the script,
  `main.py`, and tests alike

### 2026-06-26 to 06-28 (PR #55-96)
- Settings: new consolidated `/settings` page - migrates the old slide-out global-settings
  panel, merges Accounts and the standalone `/auth-setup` page in (`/auth-setup` now
  302-redirects to `/settings#accounts`), and adds a Clean up sidecars UI
- Library Downloader: owned-ASIN detection no longer times out/crashes on large
  libraries and now checks Audiobookshelf first (near-instant); "download anyway" option
  removed; one-click removal of a stored Audiobookshelf API key
- Organizer: sidecar cleanup endpoint for a target folder; per-chapter `.ogg` books and
  leading-ordinal chapter splits now group into one multi-file book instead of many;
  no-series dramatized-book naming and canonical-author fixes
- Fixer: duplicate-ASIN library scans now resolve from cheap sources first; markers left
  by earlier partial runs now self-heal missing tags during fill-missing; scan gained
  core-field completeness checks; scanner now honors ignored folders and defers sidecar
  creation to the fixer (was creating non-conforming sidecars); publisher-learning no
  longer mistakes author/narrator names for publishers; "Title - Series, N" filenames
  with a bare book number now parse correctly
- Manual Review / Apply: sidecars now placed by alone/group like the rest of the
  pipeline; Owned detection explains its Audiobookshelf dependency

### 2026-06-22 to 06-25 (PR #36-51)
- Fixer: GraphicAudio/Soundbooth Theater promoted to first-class matching (6 bugs fixed:
  ASIN equal-score overwrite, series-number identity conflicts, "Dramatized Adaptation"
  narrator-tag detection, edit-mode ordering, composer-tag reading from both mutagen and
  ffprobe, and more); series book-number stripped before GA/SBT search to avoid false
  sequence conflicts; concurrent write phase
- M4B Tool: folder browser for source selection
- Metadata Forge: manual-apply edit screen for per-book review before applying; run
  safeguards (block new runs while cancelled workers drain, worker-count caps from
  stress testing); progress-bar and write-skip-counting fixes
- Organizer: edition-tag routing, ASIN-name guard, cross-author metadata fixes
- Runs: UI re-attaches to in-progress fixer/organizer runs after a page reload
- Docker: self-contained image + GHCR publish for pull-and-run deployment, no repo
  clone required

### 2026-06-22 (PR #21-22)
- Organizer: trusted-first title pipeline, folder-level sidecar discovery, consistent
  directory display, fix false duplicate-source warning, re-caching phase announcement
- Docs: replace all em dashes in README

### 2026-06-21 (PR #14-20)
- Forge: scan button beside browse field, persistent skip patterns (survive restarts),
  flag cluster cleanup, clearer force controls, action guide, auto-backup toggle
- Fixer: smart-skip count surfaced in summary and UI; smart-skip labelled explicitly
  in dry-run and apply output
- Sidecar: unified `.libraforge.json` per book (replaces separate fixer/organizer sidecars)
- Progress: fix progress counters, fixer PermissionError on read-only metadata.json,
  scan already-processed detection
- Install: zero-config first boot, `make up` one-command setup, `Makefile` with
  `up/down/logs/restart/rebuild/test` targets

### 2026-06-21 (PR #12-13)
- Fixer: scoring overhaul, always-on `metadata.json` export, report categories
  (exact/fill/smart-skip/manual-review), publisher policy (`publishers.default.json`,
  local override)
- Forge: browse and scan loose folders, compare-panel duration row, fill-category labels

### 2026-06-20 (PR #9-11)
- Library Downloader: browse Audible library, download AAX/AAXC purchases to M4B with
  chapters, embedded cover, and ASIN; optional post-download organize
- Accounts: multi-account Audible auth, account switcher, rename, switch, disconnect/
  deregister, retry/delete-anyway on deregister failure
- Providers: Audiobookshelf and abs-agg as metadata providers for batch runs and
  Manual Review; provider setup on Accounts page

### 2026-06-18-19 (PR #3-8)
- Smart scan cache (1hr TTL + fingerprint), larger covers, book list with organized
  category
- Smart write diff, write modes (`smart`/`fill-missing`/`overwrite`), ASIN embedding
  and extraction (fixer v5)
- Horizontal site nav, page descriptors, Start Here landing page with folder scan and
  NAS path support
- Studio exclusions, genre subtitle preservation, false-positive book-number review fix

### 2026-06-17 (PR #2)
- Fix CI test failures: env vars, import errors, stale script refs
- Organizer metadata review improvements

### 2026-06-16 (initial release)
- Initial public release: Metadata Forge, M4B Tool, Folder Forge, Docker setup,
  MIT license, CI, health endpoint, dry-run-first defaults
