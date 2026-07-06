# Comparison Card Data Source

Date: 2026-07-06
Status: Confirmed invariant, enforced in code

## The rule

Any "comparison card" — Manual Review's Current/Match display, or the
Suspicion Report's `local`/`match` sections — shows two things: what the book
currently has, and what we think it should have. The second half (`match`)
always comes from a stored decision (a marker or a fresh probe result). This
doc is about the first half (`local` / "Current").

**Once a book has been processed at least one time, its `local`/"Current"
side must be read from a durable on-disk cache. It must never come from a
fresh re-probe of the file's tags, and it must never come from a
before-the-last-write snapshot.**

The cache is written every time we write to the file, so it is guaranteed to
mirror the file's actual embedded tags. Re-probing to populate a comparison
card is redundant work that also risks re-introducing path/folder-derived
noise into a field meant to show clean, embedded truth (see
`tag_series` history below). Skipping the probe is not a performance
shortcut we tolerate — it is the correct design once the cache exists.

## The two caches, and which one code should read

Every successful write updates two files together, from the same
`effective_metadata` dict, in the same code path
(`scripts/audible-metadata-fixer-v5.py`, main gather loop ~line 5404-5466):

| Cache | Written by | Schema | Consumed by |
|---|---|---|---|
| `metadata.json` (Audiobookshelf-facing) | `write_audiobookshelf_metadata_json()` | ABS external shape: `authors`/`narrators`/`series` as lists, `series` combines name+`#seq` as one string, no `duration_minutes`, no `raw_title` | Audiobookshelf itself; not read back by LibraForge's own comparison code today |
| `libraforge.json` → `marker.audible` (single-file) or `sidecar.book` (grouped) | `write_marker()` / `write_m4b_tool_metadata_sidecar()` | Internal shape: flat `title`/`author`/`narrator`/`series`/`sequence`/`genre`/`subtitle`/`summary`/`isbn`/`asin`/`cover_url` | `metadata_from_marker()`, `_read_sidecar_book()`, `_build_report_item()` |

Both files hold the same underlying truth in two serializations. **LibraForge's
own code (Manual Review, the Suspicion Report) reads the `libraforge.json`
side** (`marker.audible` / `sidecar.book`), not `metadata.json` directly,
because its schema already matches the shape the UI and report need field for
field — reading `metadata.json` instead would mean parsing `"Series #3"` back
apart, rejoining author lists, and losing `duration_minutes`/`raw_title`
entirely, for no benefit, since the two files are written in lockstep and are
never allowed to diverge. If that guarantee is ever weakened (e.g. one write
path updates one file but not the other), this doc's invariant breaks and
needs re-auditing.

## The mistake this doc corrects: `local_before` is not "current"

`marker.local_before` is a snapshot taken **immediately before** a write, of
what `clues` looked like at probe time that run. It answers "what did this
book look like before we fixed it," which is audit/history information.

It is **not** the same thing as "what does this book currently have," except
in the instant right after that write completes. The moment a *later* write
happens, `local_before` is overwritten with a new pre-write snapshot and the
old one is gone — but even before that, semantically, the file's actual
current tags equal whatever was written last, i.e. `marker.audible`, not
`local_before`.

Concretely: book has messy embedded tags (e.g. series `"Pocket Dungeon 4"`,
an album-fallback artifact). Run 1 processes it, decides the correct series
is `"Pocket Dungeon"`, writes the tags, and stores:
- `marker.audible.series = "Pocket Dungeon"` (what's now embedded in the file)
- `marker.local_before.series = ""` (tag_series was empty pre-fix — see
  below; the raw pre-fix clue was the contaminated `"Pocket Dungeon 4"`)

Run 2 is a clean skip (`marker_skip_is_clean()` is true — nothing changed, no
fresh probe happens). A comparison card for this book must show
**`"Pocket Dungeon"`** as "Current," because that is what is actually
embedded in the file right now. Showing `local_before` here would surface
stale, already-fixed data as if it were the book's present state — exactly
the kind of contamination this whole effort has been about eliminating.

**Fix applied:** `_build_report_item()` in
`scripts/audible-metadata-fixer-v5.py` previously built the clean-skip
fallback for `"local"` from `marker.local_before`. It now builds `"local"`
from the same `meta = metadata_from_marker(stored)` dict already used to
build `"match"` — i.e. from `marker.audible`. For a genuinely clean skip,
`local` and `match` end up identical, which is correct: that equality *is*
the definition of clean (nothing left to reconcile). The report still shows
both columns so a reviewer can eyeball recent history without needing to know
this internally — but they now report the same, correct, currently-embedded
truth instead of one column silently regressing to pre-fix data.

`local_before` remains useful for its actual purpose — audit/history, "what
did we change this book from" — but must never again be used to answer
"what does this book currently have."

## Where the fresh probe still legitimately happens

This rule is scoped to the **comparison-card display fields**
(`title`/`subtitle`/`author`/`narrator`/`series`/`sequence`/`year`/`genre`/
`summary`/`isbn`/`asin`/`cover_url`). It does not forbid every read of the
file's tags forever:

- **First-ever processing of a book** has no cache yet, so a probe is
  required — that probe's result is what gets written into the caches for
  every future run to reuse.
- **Actively processing/matching a book this run** (status `matched`, not a
  skip) necessarily reads tags as part of finding/scoring a candidate match.
  `_build_report_item()` uses that already-fresh `clues` for `"local"` in
  this case — this is not a redundant extra probe, it's the same probe that
  drove the match, reused for display.
- **Manual Review** (`inspect_manual_review_target()` /
  `_read_sidecar_book()`) still calls `build_search_context()` every load, but
  only uses its output (`clues`) for fields that are genuinely absent from
  the cache: `publisher` (not part of the write schema — its own subsystem,
  see `reference_abs_packages` memory), `local_duration_minutes` (audio
  itself could change independent of tag writes), `raw_title`, and
  `book_number_source` (search-query plumbing, not display truth). Every
  cache-covered field (`title`/`subtitle`/`author`/`narrator`/`series`/
  `sequence`/`year`/`summary`/`genre`/`isbn`/`asin`) is overridden by
  `sidecar_book` when present — see `app/main.py` `inspect_manual_review_target()`,
  the `sidecar_book` branch (~line 2583-2597). This already conforms to the
  rule; nothing to fix here, but it's documented so the exceptions aren't
  mistaken for a violation later.
- **`use_backup_tags=True`** (an explicit "show me the original backup, not
  the applied state" request) intentionally bypasses the cache — that's the
  point of the flag, not a violation.

## Conformance checklist (audit this doc against the code when either changes)

| Site | Reads for "local"/"Current" | Conforms? |
|---|---|---|
| `_build_report_item()` (fixer report, clean-skip case) | `marker.audible` via `metadata_from_marker()` | Yes (fixed 2026-07-06) |
| `_build_report_item()` (fixer report, fresh-match case) | `clues` from this run's own probe | Yes (probe already happened for matching, not redundant) |
| `inspect_manual_review_target()` / `_read_sidecar_book()` | `sidecar.book` / `marker.audible`, with narrow named exceptions above | Yes |
| `write_marker()` / `write_audiobookshelf_metadata_json()` | N/A (write side) | Both updated together from the same `effective_metadata`, every actual write — this is what makes the caches trustworthy |

If a new comparison surface is added, it must read from `marker.audible` /
`sidecar.book` (or, for external ABS consumption, `metadata.json` — same
truth, different shape), and must not add a new tag re-probe to populate a
"current state" field once a book has been processed once.

## Validated against 100 real books (2026-07-06)

Ran a dry-run scan (`--max-files 140`, no `--apply`, no Goodreads) over
`/audiobooks/_unorganized`, took the first 100 `REPORT_ITEM_JSON` items (99
single-file "tags"-output books, 1 grouped sidecar book), and independently
verified each one: a from-scratch mutagen probe (no import of any app
matching/parsing code — just the raw MP4 atom / ID3 frame names documented in
`mutagen_write_mp4_tags`/`mutagen_write_mp3_tags`) compared field-by-field
against the report's `local` section.

- **title/author/series/sequence: 99/99 exact matches** once the marker
  reader correctly handled both libraforge.json naming conventions (per-file
  `<name>.libraforge.json` for loose files sharing a folder vs. folder-level
  `libraforge.json` for a lone file). These fields are written
  unconditionally on every apply (blank clears the tag), so marker.audible
  always equals the file's real current tag — no drift possible.
- **genre: only 13/99 exact matches, 85/99 wrong.** Root cause: the tag
  writers only touch the genre atom/frame `if genre:` — when the decided
  match had no genre, the file's pre-existing genre tag (real values like
  `"Science Fiction & Fantasy:Fantasy:Epic"`, or junk like `"Audiobook"`) is
  left completely untouched, but `write_marker()` was recording plain
  `metadata.get("genre", "")`, i.e. blank, ignoring that the file's actual
  resulting genre is whatever was already there. **Fixed:** `write_marker()`
  now records `metadata.get("genre") or clues.get("genre", "")`, mirroring
  the writer's own preserve-if-absent behavior so the persisted (and
  therefore displayed) genre always matches what's truly embedded. Verified
  end-to-end by re-deriving real clues from three of the mismatching real
  files (read-only, no mutation) and confirming `write_marker()` now persists
  the real genre instead of `""` (see git history for
  `test_genre_falls_back_to_clues_when_match_has_none`).
- **1 narrower, separate finding (not fixed here):** one low-score-rejected
  match (`Ruth Kinna - Anarchism...`) showed `local.title`/`local.narrator`
  diverging from the file's real tags. Root cause is different and lives
  upstream in `read_tags_and_duration()`/`apply_structured_path_override()`
  (search-clue construction prefers a cached metadata backup and a
  filename-derived title override over a live probe) — a search/matching
  concern, not a marker-persistence concern, and out of scope for this fix.
  Flagged for awareness; revisit if it recurs at higher frequency.
- **subtitle/isbn have the same theoretical "preserve if absent" write
  policy as genre**, but `parse_title_series_number_from_metadata()` doesn't
  currently extract them as clue keys at all, so there's no clue value to
  fall back to yet. Not fixed here (would require adding new clue fields,
  a larger change); noted for a future audit pass.
