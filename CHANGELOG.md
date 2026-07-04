# Changelog

All notable changes. No tagged releases yet - tracking by PR.

---

## Unreleased

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

### 2026-07-01 to 07-03 (PR #123-132)
- Suspect Report: new review-script pass (`review-libraforge-report.py`) that flags
  likely-wrong matches after a run - bitrate tokens leaked into titles, ABS-style
  duplicated title brackets, redundant series prefixes, generic omnibus titles, and more
  - surfaced through a shared UI widget on both Metadata Forge and Folder Forge
  (Organizer gets its own new detections on top); manual review performance improved via
  script filtering and caching
- Organizer: fixed several title-source bugs; report retention (max age / max count)
  settings added to Settings; fixed multi-file grouping to recognize part numbers
  embedded mid-filename, not just trailing ones; fixed cross-contamination between books
  sharing a folder in `libraforge.json`
- Manual Review: display fixes; cover extraction now reads the real embedded cover tag
  instead of ffmpeg's first video stream (fixes wrong covers on some files)

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
