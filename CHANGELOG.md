# Changelog

All notable changes, tracked by PR. This file wasn't kept in sync with the
GitHub Releases for v0.1.0-v0.2.1 (see the Releases page for those); v0.2.2
onward is tracked here going forward.

---

## v0.2.3 (2026-07-09)

### 2026-07-05 to 07-09 (PR #158-185)
- Fixer/Manual Review: comparison-card "Current" data is now consistent everywhere
  it's shown (Suspicion Report, Match Report, Manual Review) - this was fixed
  incrementally over several days as each remaining gap surfaced:
  - "Current" was partly built from matcher-only clues (title/series/author/book_number
    after path- and folder-name overrides meant only to help find the right catalog
    match), so a rejected or stale match could show a guessed identity instead of the
    file's real tags. Replaced with a pure tag-only reader used everywhere "current
    state" is displayed or persisted to the marker.
  - Genre, subtitle, summary, isbn, asin, and publisher were silently dropped or
    misreported blank in the marker (genre alone was wrong on 85 of 99 real books
    tested) because the writer's own "leave tag alone if match has nothing" behavior
    wasn't mirrored when recording what got written; fill-missing mode also
    overwrote genre/subtitle instead of respecting existing values.
  - A cleanly-skipped file (already correctly matched by a prior run) showed stale
    pre-fix data as if it were current, and grouped multi-file books' representative
    file could be a bonus non-content track (e.g. "Opening Credits"), leaking its own
    chapter title and track number as if they were the book's title and series
    sequence.
  - Root cause of the last remaining inconsistency: the report and Manual Review read
    through two independently-written lookups that happened to mostly agree. The
    report now delegates to the exact same sidecar/marker lookup Manual Review uses,
    so they can't diverge again.
  - Separately, the Match Report card had hardcoded blank "Local" values for
    Year/ASIN/ISBN specifically since the card was first built - unrelated bug, same
    visible symptom, now wired to the real data like every other field.
- Suspicion Report: added missing-title/author/series flags (high severity) for a
  technically-correct match that's just missing that field; duplicate-identity
  (cross-item) cards now show real identifying titles/paths instead of an empty
  "(cross-item)" card; added a search box + flag-type filter, shared by the fixer and
  organizer reports; fixed a structural no-op that meant the "latest report" lookup
  could never actually exclude organizer reports from the fixer's own view, and a
  false error logged on every report load before its first Suspicion Report existed
- Manual Review: Edit dialog widened to 75% of viewport and given a settings-style
  side nav on the Metadata Forge page for jumping between sections; Edit dialog cover
  search simplified to a clickable cover + title (no more separate "use this cover"
  button), packed 4-7 covers per row instead of 2, and added Language/Explicit tag
  fields (written to metadata.json only, no existing tag convention covers them);
  fixed clearing a dialog field being silently ignored on apply (wrote the old
  matched value back into every field instead of respecting the clear); added a
  uniform Fill/Overwrite field policy across all dialog fields; fixed multi-genre
  input collapsing into one malformed combined tag instead of separate values;
  fixed grouped-book ASIN recovery reading only the folder-level sidecar, missing
  the per-file one a shared "dumping ground" folder actually uses
- Organizer: ported the fixer's part-sequence/leading-ordinal grouping so a folder
  holding both a chapter sequence and a leftover merged edition groups correctly
  instead of exploding every chapter into its own move; added a per-item "Exclude
  from organizer run" button on the moves report; fixed the real cause of run
  settings (e.g. "Progress every N items") being silently ignored - the Start button
  passed its own click event as the request body instead of the form's collected
  values; fixed a page-reload race that could silently swap in a stale prior run's
  progress/log after a fresh run was already started
- Library Downloader: fixed CloudFront-blocking downloads by preferring a per-book
  decryption voucher over account activation bytes (the account's activation bytes
  are blocked at the source; the voucher path never touches that endpoint), added a
  status indicator for whether activation bytes are cached with a one-click-copy
  recovery command when they're not, downloads now run 3-at-a-time like audible-cli
  instead of one at a time, and the end-of-run report shows each item's actual
  decrypt method and outcome instead of just aggregate counts
- UI: sticky header, a release version tag linking to its GitHub notes, and a
  Settings About section; fixed the sticky side-nav (Settings and Metadata Forge)
  rendering partly hidden behind the sticky header at every scroll position
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
