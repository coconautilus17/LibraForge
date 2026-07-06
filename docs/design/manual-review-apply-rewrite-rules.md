# Manual Review Apply: Rewrite Rules

Date: 2026-07-06
Status: Fixed and enforced in code

## The bug

Loading a book into Manual Review, matching it against the wrong catalog
entry (e.g. a series where only book 1 is on Audible, while the local file is
book 8), clearing every dialog field except one, and applying — wrote the
wrong book's data into every field anyway. Clearing a field did nothing.

Root cause: the dialog's override-diff logic (`app/static/app.js`,
`applyManualMatch`) only sent an override to the backend when the box's value
was both non-blank *and* different from the match's pre-filled value:

```js
if (val && val !== String(chosen[key] ?? '').trim()) metadataOverride[key] = val;
```

Clearing a field makes `val` falsy, so its key was **never added to
`metadata_override` at all** — not sent as `""`, simply absent. The backend
(`app/main.py`, `apply_manual_review_result`) had nothing to merge for that
key, so it fell back to the match's own original value, silently ignoring
that the user cleared it. The backend's merge was already correct
(`"" is not None` → would apply a blank if one were ever sent); the entire
bug was that the frontend never sent one.

A second, independent problem sat underneath: the tag writer itself
(`mutagen_write_mp4_tags`/`mutagen_write_mp3_tags`,
`scripts/audible-metadata-fixer-v5.py`) had an inconsistent per-field policy
— title/author/series/sequence/narrator/year were always written (blank
clears the tag), while genre/subtitle/isbn/asin/publisher were only written
`if <field>:` (blank left the existing tag alone). So even with the frontend
fixed, "blank in the dialog" didn't mean the same thing for every field.

## The frontend signal contract

`applyManualMatch` now sends exactly one of three signals per field:

| Dialog state | Sent as | Meaning |
|---|---|---|
| Box still matches the match's pre-filled value, untouched | key absent from `metadata_override` | "I didn't touch this — use the match's own value" |
| Box cleared (was non-blank, now blank) | `metadata_override[key] = ""` | "I'm intentionally blanking this field" |
| Box holds a custom value | `metadata_override[key] = "<value>"` | "Use this instead of the match's value" |

```js
const original = String(chosen[key] ?? '').trim();
if (val !== original) metadataOverride[key] = val; // val may legitimately be ''
```

## The two write policies

Both buttons in the dialog resolve the same `metadata` dict (match value,
overridden per the table above) into a write, but apply one uniform policy
across all 11 editable fields (title, subtitle, author, narrator, series,
sequence, year, asin, isbn, publisher, genre) instead of the old inconsistent
6-unconditional/5-conditional split:

- **Apply Fill**: a non-blank resolved value is always written (overwriting
  whatever's there). A blank resolved value is **skipped entirely** — the
  file's existing tag for that field is left completely untouched, whatever
  it currently holds.
- **Full Overwrite**: a non-blank value is written; a blank value **clears**
  the tag (writes nothing / empty).

This is implemented via `field_policy: str` (values `"legacy"` / `"fill"` /
`"overwrite"`), threaded through `write_tags()` →
`mutagen_write_mp4_tags()`/`mutagen_write_mp3_tags()`
(`scripts/audible-metadata-fixer-v5.py`), and the small shared gate that
decides whether a setter is even called at all
(`app/fixer/tagging.py::should_write_field`):

```python
def should_write_field(value, field_policy, legacy_conditional):
    if value:
        return True
    if field_policy == "overwrite":
        return True
    if field_policy == "fill":
        return False
    return not legacy_conditional  # "legacy": reproduce the old per-field split
```

`"legacy"` is the implicit default for every CLI call site (they never pass
`field_policy`) and reproduces the writer's historical mixed behavior
byte-for-byte — this keeps the CLI's already-tested smart/overwrite/
fill-missing write-mode system (`decide_write()`, `compare_tags_for_write()`,
`merge_fill_missing_metadata()`) completely untouched. `"fill"`/`"overwrite"`
are used only by `apply_manual_review_result` (`app/main.py`), driven by the
dialog's two buttons.

The tag setters themselves (`mp4_set_text`/`mp4_set_freeform`/`id3_set_text`/
`id3_set_txxx`) already correctly implement "if value: set else: clear" and
needed no changes — the fix is entirely about whether the caller invokes the
setter at all when the value is blank.

## `marker.audible` and `clues["current"]` had to become policy-aware too

`write_marker()`'s survivor-fallback (recording what's *really* embedded when
a conditionally-written field was left untouched — see
[[comparison-card-data-source]]) previously only applied to the 5
legacy-conditional fields. Once all 11 fields can now be left untouched (under
`"fill"`), the marker must track the *same* decision for all 11, or it
misreports a "fill"-mode-untouched field as blank. `_marker_survivor_value()`
mirrors `should_write_field()`'s decision:

- `"fill"`: every field falls back to `clues["current"]` when blank in the
  decided metadata (the writer left it untouched, so the marker must say what
  survived).
- `"overwrite"`: no field falls back — a blank really is cleared, reporting
  the old value would be a stale lie.
- `"legacy"`: keep the original 6-plain/5-fallback split.

This surfaced a second, pre-existing bug specific to the manual-apply path:
`clues["current"]` was **never populated there at all**. `apply_manual_review_result`
built `clues` via `build_context_clues()`, which never sets `"current"` — so
the survivor-fallback for genre/subtitle/isbn/asin/publisher was a silent
no-op for every manual apply where the match didn't supply those fields,
even when the real tag survived on disk (the same bug class already fixed
for the CLI's automatic scan path in
[[comparison-card-data-source]], just never ported to this call site). Fixed
by adding, right after building `clues`:

```python
clues["current"] = dict(context["metadata"])
```

`context["metadata"]` (from `inspect_manual_review_target`) is already
exactly the right "current tag state" shape — it prefers the sidecar/marker
over a live probe, the same rule the CLI path follows.

## `metadata.json`: `skip_blank_fields` is not `fill_missing`

`write_audiobookshelf_metadata_json()` already had a `fill_missing: bool`
parameter — but its semantic doesn't match what Apply Fill needs, and the two
must not be conflated:

| | Keyed off | Behavior when new value is present but old value is also present |
|---|---|---|
| `fill_missing` (CLI's fill-missing write mode) | the **existing file's** blankness | keeps the **old** value (never overwrites a non-blank existing field) |
| `skip_blank_fields` (Manual Review's Apply Fill, new) | the **new** resolved value's blankness | the **new** value always wins when present; only a blank new value falls back to whatever's already there |

`apply_manual_review_result` always passes `fill_missing=False`, and passes
`skip_blank_fields=(write_policy == "fill")`. The two flags are independent
and could theoretically both be true for some future caller, but no current
call site does that.

`write_audiobookshelf_metadata_json()`'s `genres` array construction was also
fixed in the same pass (see below) — this is a separate, unrelated bug found
while tracing this feature.

## Genre: it must actually split into separate values

Independently discovered while tracing this feature: genre was never split
into separate values anywhere in the write path. Confirmed live before the
fix — `write_audiobookshelf_metadata_json(..., {"genre": "Fantasy, LitRPG"})`
produced `"genres": ["Fantasy, LitRPG"]`, one malformed combined entry, not
two. The embedded MP4/ID3 genre tag had the identical problem: mutagen
supports genre as a real multi-value list (`tags["\xa9gen"] = ["Fantasy",
"LitRPG"]` creates two independent values a scanner can show as two separate
genres), but the write path always collapsed to one joined string first.

The internal "genre" field stays a single comma-joined **display** string
everywhere it already was (clues, `marker.audible`, the Suspicion Report,
the dialog's own text input) — that representation is not being changed.
Only the two final write targets now split it, via
`app/fixer/scoring.py::split_genre_string()` (reuses `clean_provider_genres`
for blocklist/dedup after splitting on comma):

- `write_audiobookshelf_metadata_json()`'s `genres` array:
  `split_genre_string(metadata.get("genre", ""))` instead of wrapping the
  whole string as one list entry.
- The embedded tag, via new `mp4_set_genre_list()` / `id3_set_genre_list()`
  (`app/fixer/tagging.py`), which set the tag's value to the actual list, not
  a joined string — still gated by the same `should_write_field()` check as
  every other field.

The dialog's genre input also gained a placeholder (`"e.g. Fantasy,
LitRPG"`) and one line in the explanation text confirming the comma
convention, so a user typing multiple genres knows they'll be saved
separately, not as one combined genre.

## The ffmpeg-writer gap

`ffmpeg_write_tags()`/`build_metadata_args()` (`app/fixer/tagging.py`) only
ever emits `-metadata key=value` for truthy values and never clears a tag
(relies on `clear_existing_metadata=False`) — it already behaves like Apply
Fill for every field, unconditionally, with no way to force a clear. So Full
Overwrite cannot be honestly implemented for a file that falls back to this
writer (non-mp4/mp3, or a mutagen-writer exception fallback).

Chosen behavior: **don't reject, don't silently do something different than
asked without saying so.** `apply_manual_review_result` detects ahead of time
whether the target will use mutagen or fall back to ffmpeg
(`is_mutagen_mp4_candidate`/`is_mutagen_mp3_candidate`). If Full Overwrite was
requested but the file will use ffmpeg, it applies anyway (fill-like
behavior, since that's what the ffmpeg writer already does regardless) and
returns a `warning` string in the response, shown in the apply-result dialog:

> Full Overwrite requested, but this file type only supports the ffmpeg
> writer, which cannot force-clear a tag; blank fields were left untouched
> instead of cleared.

## Conformance checklist

| Site | Fill semantics | Overwrite semantics |
|---|---|---|
| `mutagen_write_mp4_tags`/`mutagen_write_mp3_tags` (11 fields) | `should_write_field()`, skip if blank | `should_write_field()`, clear if blank |
| `write_marker()`'s `marker.audible` (11 fields) | `_marker_survivor_value()`, fallback to `current` if blank | never falls back, blank stays blank |
| `write_audiobookshelf_metadata_json()` | `skip_blank_fields=True` | `skip_blank_fields=False` (default; no equivalent flag needed — payload already reflects the resolved metadata as-is) |
| ffmpeg fallback writer | already fill-like unconditionally | not honestly possible; applies as fill + surfaced `warning` |
| Genre (embedded tag + metadata.json) | split via `split_genre_string()` either way — orthogonal to fill/overwrite |

If a new manual-apply write target is added, it must accept `field_policy`
(or the metadata.json-style `skip_blank_fields`) and implement both
semantics — never assume "blank means clear" or "blank means leave alone"
unconditionally.
