# Manual Review: multi-file visibility, direct-edit dialog, cover swap

Date: 2026-07-07
Status: Approved, not yet implemented

## Motivation

Three related Manual Review gaps surfaced while working the same area this session:

1. Whether a book is a multi-file/grouped book (chapter-split audio) is only
   visible in one place today (the discovery/browse list badge, `app.js:416`).
   It matters for review because grouped books are written differently (JSON
   sidecar only, no per-chapter embedded tags -- see
   `docs/design/manual-review-apply-rewrite-rules.md`), so knowing this up
   front changes what you expect editing it to do.
2. Fixing a book's fields today always requires going through the
   search/match flow, even when you already know exactly what the fields
   should be and just want to type them in directly.
3. There's no way to search for and swap just the cover in isolation --
   cover selection today is bundled inside a full metadata match.

## Part A: surface "multi-file book" everywhere a book can be inspected

### Backend

- `_build_report_item()` (`scripts/audible-metadata-fixer-v5.py`): add
  `"is_grouped": bool((clues.get("group_search") or {}).get("applied"))` to
  the returned item dict. Same source of truth already used by
  `discover_manual_review_targets` (`app/main.py:2119`) and
  `inspect_manual_review_target` (`app/main.py:2629`) -- just missing here.
- New log line during per-item processing (e.g. `"  Grouped: N files"`,
  right after `build_search_context` resolves `group_search`), parsed by a
  new regex in `parse_line()` that calls
  `add_category(state, "group", "multi-file", state.current_file)`. This is
  the same mechanism every other category (`mode`, `duration`, `status`,
  `provider`, `fill`) already uses, so it appears in the existing "browse by
  category" dropdown (`app/main.py` `categorySelect`/`files_by_category`)
  with no separate frontend plumbing.

### Frontend (`app/static/app.js`, reusing existing badge CSS)

1. **Active/loaded target card**: badge near `manualTargetPath` when
   `manualContext.is_grouped` is true (data already returned by
   `/api/manual-review/load` today -- no new backend call needed for this
   one).
2. **Match report cards** (`buildMatchCard`): badge in the existing
   `mrep-badges` row when `item.is_grouped`.
3. **Match report filter** (`matchReportFilter` dropdown, `buildMatchReportCards`
   filter logic): new "Multi-file books" option, filters on `item.is_grouped`.
4. **Category browse dropdown**: populated automatically once the backend
   emits the new `group:multi-file` category (existing generic rendering).

## Part B: standalone "Edit" dialog (direct field editing, no match required)

### Trigger

New button "Edit Book" in the Manual Review actions bar
(`app/static/index.html`, next to `manualReloadCoverBtn`), enabled once a
target is loaded via `loadManualTarget`.

### Dialog

A new, dedicated `<dialog>` element (own markup and JS, not a reuse of the
existing match-apply dialog's HTML/IDs) with two tabs: **Fields** (default)
and **Cover** (Part C).

**Fields tab**: same 11 fields as the match-apply dialog (title, subtitle,
author, narrator, series, sequence, year, asin, isbn, publisher, genre,
summary), pre-filled directly from `manualContext.metadata` -- the current
tags/sidecar data already loaded in memory. No search/match step.

**Save**: single button, not the Fill/Overwrite pair. A blank field always
clears that tag. Internally this is exactly the existing `field_policy =
"overwrite"` write semantics (`should_write_field`,
`_marker_survivor_value`) -- no new write-policy value needs inventing, this
endpoint just always uses `"overwrite"`.

### Backend

New endpoint `POST /api/manual-review/edit`:
- Request: `path`, `script_name`, and the 11 field values directly (no
  `selected_result`/`metadata_override` diffing -- these values ARE the
  resolved metadata, not an override layered on a match).
- Validation: same minimum bar as apply (title + author required).
- Internally calls the new shared `_write_book_metadata()` helper (see
  Architecture below) with `field_policy="overwrite"` always and
  `score=1.0` (there's no match to carry a confidence score from -- a
  direct user edit is definitionally full-confidence).
- Cover: `replace_cover=True` only if the request's `cover_url` differs from
  what was already loaded (i.e. the user actually picked something new in
  the Cover tab); otherwise `cover_if_missing=False, replace_cover=False` so
  an untouched Cover tab never re-downloads/re-embeds the existing cover.
- For grouped books, this naturally writes only the JSON sidecar (via the
  existing `should_write_json_sidecar` check) -- consistent with today's
  grouped-book behavior, no per-chapter tag writes.
- Same ffmpeg-writer warning surfaced if applicable (Full Overwrite can't
  truly clear a tag on a file that falls back to the ffmpeg writer).

## Part C: Cover tab

Two ways to pick a cover, both landing in the same live preview + a single
pending `cover_url` for the dialog:

1. **Search**: reuses the existing provider search pattern already in
   Manual Review (same query field + provider dropdown, same search
   endpoint) -- but this tab renders only each result's cover thumbnail
   (click to select), not full metadata match cards.
2. **URL or Upload**: a text input for a direct image URL, plus a file
   picker.
   - A pasted URL is used as-is.
   - An uploaded file goes to a new endpoint
     `POST /api/manual-review/cover-upload` (multipart), which stores it in
     a short-lived server-side temp location and returns a locally-servable
     URL. That URL then flows through the exact same `cover_url` field the
     writer already knows how to embed
     (`download_cover_bytes` already fetches arbitrary URLs, including ones
     served by this app itself) -- no new embed code path needed.

Selecting a cover from either method just updates the tab's preview image
and the dialog's pending `cover_url`. The actual write happens once,
together with whatever is in the Fields tab, when **Save** is clicked --
one button, one write, regardless of which tab was last active.

## Architecture: shared write helper

`apply_manual_review_result` (`app/main.py`) already has the full write
sequence the new edit endpoint needs: resolve grouped/alone placement, write
tags or JSON sidecar, write `metadata.json`, write the marker (with
`written_fields` and `field_policy` threaded through, per this session's
earlier fixes). Duplicating that ~120-line sequence for a second endpoint
would immediately create two copies that can drift (exactly the class of
bug fixed earlier this session in the grouped-book ASIN path).

Extract a shared internal helper:

```python
def _write_book_metadata(
    *, source_path: Path, metadata: dict, clues: dict, score: float,
    fixer_module, write_policy: str, writer: str = "auto",
    cover_if_missing: bool = False, replace_cover: bool = False,
    backup: bool = False,
) -> dict:
    """Resolves alone/grouped placement and writes tags-or-sidecar +
    metadata.json + marker. Returns {output_kind, output_path,
    metadata_json_path, warning}. Shared by apply_manual_review_result and
    the new edit endpoint so the two flows can never diverge."""
```

`apply_manual_review_result` keeps its own match-diffing logic (building
`metadata` from `selected_result` + `metadata_override`) and then calls this
helper. The new edit endpoint builds `metadata` directly from the request
body and calls the same helper with `write_policy="overwrite"`.

## Out of scope / explicitly not doing

- No per-chapter embedded tag writes for grouped books from either the
  match-apply or the new edit flow (matches existing behavior, confirmed by
  your answer to Part B's clarifying question).
- No new "Fill vs Overwrite" choice in the Edit dialog -- single Save,
  blank always clears (confirmed by your answer).
- Not reusing the match-apply dialog's HTML/IDs for the new Edit dialog --
  built as a separate, dedicated dialog (confirmed by your answer).

## Testing

- Backend: unit tests for `_build_report_item`'s new `is_grouped` field;
  the new `group:multi-file` category regex/parsing; `_write_book_metadata`
  extraction (regression-test that `apply_manual_review_result`'s existing
  behavior is unchanged post-refactor); the new `/api/manual-review/edit`
  endpoint (single-file and grouped-book cases, blank-clears-tag,
  ffmpeg-writer warning); the new `/api/manual-review/cover-upload`
  endpoint.
- Frontend: manual verification in-browser (badges render in all 4
  surfaces, filter works, Edit dialog pre-fills correctly for both a
  single-file and a grouped book, Cover tab search/URL/upload all populate
  the same preview, Save applies both fields and cover together).
