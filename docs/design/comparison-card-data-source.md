# Comparison Card Data Source

Date: 2026-07-06
Status: Confirmed invariant, enforced in code

## The rule

Any "comparison card" — Manual Review's Current/Match display, or the
Suspicion Report's `local`/`match` sections — shows two things: what the book
currently has, and what we think it should have. The second half (`match`)
always comes from a stored decision (a marker or a fresh probe result). This
doc is about the first half (`local` / "Current").

**"Local"/"Current" must be an exact, complete, field-for-field reflection of
what the file's own tags actually say — every field, not just the ones that
happen to be easy. If a tag is empty, the display is empty. Nothing else is
acceptable.** Two independent contamination sources can break this, and both
are guarded against below:

1. **Re-deriving it from search-clue machinery.** `clues` (built by
   `build_search_clues_from_file()`/`build_multi_file_search_context()`) is a
   **matcher-only** construct. Several of its fields — `title`, `series`,
   `author`, `book_number` — are deliberately overwritten by path/folder-name
   heuristics (`apply_structured_path_override`, `descriptive_path_meta`,
   hierarchy-folder series inference, the whole folder-identity pass for
   grouped books) whose only job is helping find the right catalog match.
   None of that describes what is actually embedded in the file, and it must
   never be used for comparison-card display. This class of bug is guarded
   against by `read_current_book_metadata()` (see below), which is built
   from raw tags only, before any such heuristic runs.
2. **Reading a stale or incomplete cache.** Once a book has been processed,
   display must come from the durable on-disk cache (never a fresh re-probe,
   for performance) — but that cache must (a) actually be a live probe when it
   was captured, not a stale backup/synthesized snapshot, and (b) actually
   carry every field, including ones the tag *writer* only conditionally
   touches (genre, subtitle, isbn, asin, publisher).

## `clues["current"]`: the one true source

`read_current_book_metadata(tags)` (`app/fixer/clues.py`) is a **pure**
function: raw tags in, a flat dict out — `title`, `subtitle`, `author`,
`narrator`, `series`, `sequence`, `genre`, `year`, `isbn`, `asin`,
`publisher`, `summary`, `raw_title`. Every field is exactly what the tag
says, or `""` if absent. It reuses `parse_title_series_number_from_metadata()`
for the fields that legitimately need tag-*text* interpretation (e.g. a
series name embedded in the title tag itself, like `"Foo: Bar Book 1"` — that
is still 100% sourced from the tag, not the path) — but it is never touched
by anything that looks at `file_path`.

`build_search_context()` and `build_multi_file_search_context()` attach this
as `clues["current"]`, built from a **genuine live tag probe**, alongside
(but never mixed into) the matcher-oriented `clues` fields:

- Single-file path: `read_tags_and_duration()` returns `(tags, duration,
  is_live_probe)`. When `is_live_probe` is `False` (tags came from a cached
  backup/sidecar snapshot — deliberately fine for the matcher, which doesn't
  need a fresh read every run), one more cheap, targeted `read_file_tags()`
  call is made specifically to build `current`, so display is never built
  from a stale or field-incomplete cache. When `is_live_probe` is `True`
  (the common case — no backup yet), the same tags are reused, no extra
  probe.
- Grouped/multi-part path: `current` comes from the **representative file's
  own tags** (first file, natural sort) via the same live-probe guarantee —
  never from the group's folder-name-driven identity resolution (title/
  series/author there are deliberately parsed from the *folder name*, which
  is correct for matching a chapter-split book but describes the folder, not
  any one file).

Every consumer of "what does this book currently have" — `_build_report_item()`
(both the fresh-probe and clean-skip-fallback branches), `write_marker()`'s
`audible` and `local_before` dicts, `build_m4b_tool_metadata_payload()`'s
equivalents — reads `clues.get("current")`, never a top-level `clues` field.

## Matcher clue-gathering is completely unchanged — `clues` and `clues["current"]` are parallel, not competing

A question worth re-confirming any time this doc is in doubt: **did adding
`clues["current"]` change how the matcher recovers information from
filenames/folder paths when tags are missing or wrong?** No — and this is
verified by diff, not just design intent. `parse_title_series_number_from_metadata()`
(the tag-text parser in `app/fixer/parsing.py`), `apply_structured_path_override()`,
the descriptive/structured path parsers, `infer_group_identity_from_path()`,
and `build_search_clues_from_file()`'s own body all have **zero changed
lines** across the commits that introduced `clues["current"]`.
`clues["current"]` is appended as a new, separate dict key *after* `clues`
has already gone through its full existing resolution (tag parse → path
override → hierarchy inference → filename ASIN recovery), from the exact
same underlying raw tag read — it doesn't feed back into, replace, or weaken
any of that. The matcher still finds books from whatever combination of
tags/filename/path is available, exactly as before.

**Concrete example** (this is a real, passing test:
`test_fixer_v5_current_metadata.py::test_path_override_changes_clues_but_not_current`,
so if this invariant is ever broken by a future change, that test fails
immediately):

A ripper mis-tagged this book — the title tag actually holds the narrator's
name, and the real title only lives in the folder name (the series tag,
however, happens to be tagged correctly):

```
Folder:   Manipulation - Magic Eater, Book 1 - Sean Oswald/
File:     Manipulation - Magic Eater, Book 1 - Sean Oswald.m4b
Raw tags: title="Sean Oswald", album="Sean Oswald",
          album_artist="Sean Oswald", grouping="Magic Eater"
```

The matcher still needs the real title to find the right catalog match, so
`clues` (completely unchanged behavior) recovers it from the folder name:

| | value | source |
|---|---|---|
| `clues["title"]` | `"Manipulation"` | path override — the title tag was useless for matching |
| `clues["series"]` | `"Magic Eater"` | the `grouping` tag — this one was tagged correctly |

Meanwhile `clues["current"]` reports exactly what the file's own tags say
right now, mis-tag and all — nothing recovered, nothing guessed:

| | value | source |
|---|---|---|
| `clues["current"]["title"]` | `"Sean Oswald"` | the raw (wrong) title tag, verbatim |
| `clues["current"]["series"]` | `"Magic Eater"` | the same `grouping` tag — agrees with `clues["series"]` here only because that particular tag wasn't mis-tagged |

Both are correct for their own job: `clues["title"]` is what lets the
matcher find "Manipulation" in the catalog despite the bad tag;
`clues["current"]["title"]` is what a comparison card must show as this
file's actual current metadata — which is genuinely wrong (it's the
narrator's name) until the book is matched and its tags get rewritten.
Title disagrees between the two because the tag was bad; series happens to
agree because that tag wasn't. Neither function ever reads the other's
output, so there's no path by which fixing/improving one could silently
change the other.

## The persisted cache: `marker.audible` / `sidecar.book`

Once written, `clues["current"]` becomes the source for two persisted
things, both from `write_marker()` (which runs on every write, single-file or
grouped):

- **`marker.audible`** — the "match" record. For **unconditionally-written**
  fields (title, author, series, sequence, narrator, year — the tag writer
  always sets or clears these) this is simply the decided `metadata` value.
  For **conditionally-written** fields (genre, subtitle, isbn, asin,
  publisher — the writer only touches these `if <field>:`, otherwise leaving
  whatever tag was already there untouched), the persisted value must be
  `metadata.get(field) or current.get(field)` — the decided value if we have
  one, else whatever the file already had, because that is what the write
  policy actually leaves embedded. Getting this wrong was the exact bug
  found in the 100-book validation below.
- **`marker.local_before`** — a pre-write historical snapshot, built entirely
  from `current` (never top-level `clues`). This is audit/history data
  ("what did this book look like right before this write"), **not** a
  current-state source — see the dedicated pitfall below.

Both `metadata.json` (Audiobookshelf-facing) and `marker.audible` are written
together from the same `effective_metadata` in the same code path (main
gather loop, `scripts/audible-metadata-fixer-v5.py` ~line 5404-5466).
LibraForge's own comparison code reads the `libraforge.json` side
(`marker.audible` / `sidecar.book`) rather than `metadata.json` directly,
because its schema already matches field-for-field what the UI/report need —
`metadata.json`'s ABS-external shape (author/narrator/series as lists,
`"Series #3"` as one string) would need lossy reparsing for no benefit, since
the two files are guaranteed to never diverge.

## Pitfall already found once: `local_before` is not "current"

`marker.local_before` is a snapshot taken **immediately before** a write. It
answers "what did this book look like before we fixed it" — audit/history
information, not current state. The moment a write completes, the file's
real current tags equal `marker.audible`, not `local_before` — and the
*next* write makes even that stale, since `local_before` gets overwritten
with a new pre-write snapshot referring to a different moment in time.

`_build_report_item()`'s clean-skip fallback previously read `local_before`
for `"local"`. It now reads `marker.audible` (via `metadata_from_marker()`),
the same source used for `"match"` — for a genuinely clean skip the two
columns end up identical, which is correct: that equality *is* the
definition of clean (nothing left to reconcile).

## Where a fresh probe still legitimately happens

- **First-ever processing of a book** has no cache yet, so a probe is
  required — its result seeds `clues["current"]`, which then seeds the
  persisted caches for every future run to reuse.
- **Actively processing/matching a book this run** (status `matched`, not a
  skip) necessarily reads tags to find/score a candidate — `current` reuses
  that same read (or the one extra live read described above when the
  matcher's own tags came from a cache). Never a redundant second probe in
  the common case.
- **Manual Review** (`inspect_manual_review_target()` / `_read_sidecar_book()`)
  still calls `build_search_context()` every load, but only uses `clues`
  (not `current`) for fields genuinely absent from the persisted cache today:
  `local_duration_minutes` (audio itself could change independent of tag
  writes) and `book_number_source` (search-query plumbing, not display
  truth). Every cache-covered field is overridden by `sidecar_book` when
  present.
- **`use_backup_tags=True`** (an explicit "show me the original backup, not
  the applied state" request) intentionally bypasses the cache.

## Validated against 100 real books (2026-07-06)

Ran a dry-run scan (`--max-files 140`, no `--apply`, no Goodreads) over
`/audiobooks/_unorganized`, took the first 100 `REPORT_ITEM_JSON` items, and
independently verified each one: a from-scratch mutagen probe (no import of
any app matching/parsing code — just the raw MP4 atom / ID3 frame names
documented in `mutagen_write_mp4_tags`/`mutagen_write_mp3_tags`) compared
field-by-field against the report's `local` section.

**Round 1** (before the fixes in this section): title/author/series/sequence
matched exactly on all 99 single-file books. **Genre matched on only 13/99.**
Root cause: `write_marker()` recorded `metadata.get("genre", "")` — blank
whenever the match had no genre — even though the writer itself leaves a
pre-existing genre tag untouched in that case (real values like
`"Science Fiction & Fantasy:Fantasy:Epic"`, or junk like `"Audiobook"`,
silently survived on disk while being reported as absent). One further,
narrower case (`Ruth Kinna - Anarchism...`) showed `local.title`/
`local.narrator` diverging from the real tags — traced to `clues["title"]`
being a path/filename-derived override, i.e. exactly the matcher-only
contamination this doc's rule #1 exists to prevent, and to `read_tags_and_duration`
preferring a cached backup snapshot over a live probe (rule #2).

**Fix:** introduced `clues["current"]` (`read_current_book_metadata()`) as
described above, and re-routed every "local"/current-state consumer
(`_build_report_item()`, `write_marker()`, `build_m4b_tool_metadata_payload()`,
`metadata_from_marker()`) to read it exclusively.

**Round 2** (after the fix, re-verified against real files, read-only):
- Genre preservation re-confirmed against the same real files under the new
  architecture (`write_marker()` now records `metadata.get("genre") or
  current.get("genre", "")`).
- The Anarchism book's `current.title`/`current.narrator` now correctly show
  the real tag values (`"Anarchism"` / `"Miranda Nation"`) instead of the
  filename-derived override / blank.
- A live re-run of the same 100-book scan shows the previously-broken item's
  `"local"` section fully populated and correct — title, subtitle, author,
  narrator, summary, asin all present where the file has them, blank only
  where it doesn't.

**Known remaining gap, not yet exercised against real data:** subtitle and
isbn now use the same `metadata.get(field) or current.get(field)` fallback
as genre, and `current` now extracts both from raw tags — but the 100-book
sample didn't happen to include a book where the match had no subtitle/isbn
but the file already had one, so this specific fallback path is covered by
unit tests (`test_fixer_v5_current_metadata.py`,
`test_fixer_v5_marker_recovery.py`) but not yet by a real-book spot check.

**Important caveat on already-written markers:** this fix changes what
`write_marker()` records on the **next** write. It does not retroactively
repair `libraforge.json` files already on disk from prior runs — a
clean-skipped book's `marker.audible` still reflects whatever was recorded
under the old (buggy) logic until that book is actually reprocessed (e.g.
via `--force`). Healing the existing library's markers immediately would
require a `--force --apply` run, which is a real write action and out of
scope for this (read-only validation) pass.

## Conformance checklist (audit this doc against the code when either changes)

| Site | Reads for "local"/"Current" | Conforms? |
|---|---|---|
| `_build_report_item()` (fresh-probe case) | `clues["current"]` | Yes |
| `_build_report_item()` (clean-skip case) | `marker.audible` via `metadata_from_marker()` | Yes |
| `write_marker()` audible dict (conditional fields) | `metadata.get(field) or current.get(field)` | Yes |
| `write_marker()` / `build_m4b_tool_metadata_payload()` `local_before` | `clues["current"]` exclusively | Yes |
| `inspect_manual_review_target()` / `_read_sidecar_book()` | `sidecar.book` / `marker.audible`, narrow named exceptions above | Yes |
| `write_marker()` / `write_audiobookshelf_metadata_json()` (write side) | N/A | Both updated together from the same `effective_metadata` every actual write — this is what makes the caches trustworthy |

If a new comparison surface is added, it must read `clues["current"]`
(fresh-probe case) or `marker.audible`/`sidecar.book` (cached case) — never a
top-level `clues` field, never `local_before`, and must not add a redundant
tag re-probe once a book has been processed once.
