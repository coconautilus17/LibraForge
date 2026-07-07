# Manual Review: Multi-file Visibility, Direct Edit, Cover Swap

Date: 2026-07-07
Status: Implemented

## What changed

Three additions to Manual Review, all built on infrastructure that already
existed:

1. **Multi-file/grouped-book visibility.** `is_grouped` (already computed
   everywhere via `clues["group_search"]["applied"]`) is now on match report
   items (`_build_report_item`), in a new `group:multi-file` browse-by-category
   entry (a new "Grouped: N files" log line, parsed the same way every other
   category already is), and shown as a badge on the active target card and
   match report cards, with a matching filter option in the match report.

2. **Direct field editing.** A new "Edit Book" button opens a dedicated
   dialog (`app/static/manual-review-edit.js`, not a reuse of the
   match-apply dialog) pre-filled from the book's current tags/sidecar
   (already loaded, no new fetch). A single Save button always uses
   `field_policy="overwrite"` -- a blank field always clears that tag, since
   there's no match value to fall back to. `POST /api/manual-review/edit`
   handles it, sharing the exact write sequence
   (`_write_book_metadata`, extracted from `apply_manual_review_result`) the
   existing match-apply flow already uses, so grouped books correctly write
   the JSON sidecar only, exactly like the existing apply flow.

3. **Cover tab.** Two ways to pick a cover: search (reuses the same
   provider search dispatch the main search flow uses, factored into
   `runManualProviderSearch` in `app.js`, showing only thumbnails), or a
   direct URL/upload. An uploaded file goes through the new
   `POST /api/manual-review/cover-upload` endpoint, which stores it as a
   temp file and returns a `file://` URL -- `download_cover_bytes` already
   fetches arbitrary URLs via `urllib`, which handles `file://` natively, so
   no new embed code path was needed.

## Why `_write_book_metadata` was extracted

Before this change, `apply_manual_review_result` had the entire
tags-or-sidecar + metadata.json + marker write sequence inline. Duplicating
that for the new edit endpoint would have created two copies of the exact
class of logic that caused this session's earlier grouped-book ASIN bug
(two write paths silently drifting apart). The extraction has zero behavior
change for the existing apply flow (proven by the pre-refactor test suite
passing unmodified against the post-refactor code).

## Conformance

| Scenario | Behavior |
|---|---|
| Edit a single-file book, leave a field blank | Tag is cleared (`field_policy="overwrite"` always) |
| Edit a grouped/multi-file book | Only the JSON sidecar is written, no per-chapter tags -- same as the existing match-apply flow |
| Edit a book whose file falls back to the ffmpeg writer | Save succeeds, response includes a `warning` that blank fields could not be cleared |
| Pick a cover via search | `cover_url` set from the picked result, `replace_cover=True` on save |
| Pick a cover via upload | File stored under a temp dir, `cover_url` is its `file://` URI |
| Cover tab left untouched | `cover_url=""`, `replace_cover=False` -- existing cover is never re-downloaded/re-embedded |

## Known follow-up (not fixed here)

The Cover tab's search only covers Audible/Goodreads/Kindle -- a library
relying solely on abs-agg or GraphicAudio/SoundBoothTheater for metadata has
no cover-search path in the Edit dialog (it does still support direct
URL/upload). A true reuse of `runManualProviderSearch` would need the Cover
tab to expose the main form's abs-agg-specific fields too; deferred as a
follow-up rather than done here since the Cover tab's compact 3-option
dropdown didn't have room for those without redesigning the tab.
