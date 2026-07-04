# Start Here Legend/Guide - Design

Date: 2026-07-04
Status: Approved, pending implementation plan

## Purpose

New users (and returning ones) hit a wall of terminology across LibraForge's
four tools: write modes, edit modes, match-status badges, reason tags,
provider badges, report types, and metadata.json behavior. None of it is
explained in one place. This adds a single reference section to the Start
Here page (`/`) that explains all of it, so a user looking at a match report
can understand exactly what happened to a book and why, without digging
through Settings tooltips or asking.

## Placement and mechanics

- A new `<section>` on `app/static/start-here.html`, placed **after the hero,
  before the folder-path picker**, so it doesn't compete with the primary
  "scan a folder" action, but is seen before results/actions are relevant.
- Implemented as a single `<details class="start-here-guide">` block,
  collapsed by default, with a `<summary>` reading **"Guide: what the badges
  and modes mean"**.
- This is deliberately **separate from** the existing global
  `explanationsToggle` mechanism (`.action-explanation` /
  `.explanation-disclosure`, "Expand/Collapse explanations" in
  `ui-preferences.js`). That toggle is for per-page contextual hints someone
  re-reads each visit; this is static reference material opened once. It must
  not be swept into `initializeExplanations()`'s candidate selector, and must
  not be affected by the global toggle's expand/collapse state.
- Inside the outer `<details>`, the **Write modes** subsection is shown
  expanded by default (no further click needed) per explicit request; every
  other subsection is plain content within the already-open outer details
  (no additional nested collapse), **except** the Smart-mode explanation
  described below, which is its own nested `<details>` since it's
  meaningfully longer than the rest of that subsection.

## Content and order

Order matches priority discussed: shortest/most load-bearing first, main
content in the middle, supplementary context last.

### 1. Edit modes

Short. Two entries:

- **Full metadata**: writes everything the match provided (title, author,
  series, sequence, narrator, year, genre, ASIN).
- **Series only**: writes only series/sequence; leaves title and other
  fields untouched. Used when the match confirms series and author
  confidently but title identity is uncertain, so a possibly-correct local
  title is never clobbered.

### 2. Write modes

Shown expanded by default. Three entries, one line each:

- **Smart**: only writes if the current embedded tags differ from the match.
- **Fill missing fields only**: never touches a field that already has a
  value; only fills blanks.
- **Overwrite**: always writes every matched field, unconditionally.

**Nested explanation (Smart mode only, its own `<details>`, closed by
default):** "Smart" is the only mode whose skip/write decision isn't a
one-line fact, so it gets a deeper explanation of what "already matches"
actually checks, grounded in `compare_tags_for_write` in
`scripts/audible-metadata-fixer-v5.py`:

> Smart mode compares each field the match would write against what's
> already embedded in the file: title, author, series, genre, and ASIN, plus
> sequence, narrator, and year when the edit mode is Full. It only marks the
> book **Smart-skipped** (nothing written) when *every one* of those checked
> fields already matches. If even one differs, the file is written normally.

Fill-missing and Overwrite do **not** get this nested treatment. Their
behavior is a direct fact ("fills blanks" / "writes everything"), not a
multi-field decision worth unpacking.

**Force reprocess, and how it interacts with each write mode** (short
paragraph, still within the Write modes subsection, not nested): the "Force
reprocess" option (`--force`, "ignore existing marker files and process
again") only bypasses the *already-processed* check, so the book is
re-searched and re-matched from scratch. It does **not** override what the
write mode decides once a fresh match is found:

- **Smart + Force**: re-matches from scratch, but if the fresh match's
  fields are identical to what's already embedded, the book still shows
  `Smart-skipped`. Force restarts the search, not the write.
- **Fill missing + Force**: still only fills currently-blank fields either
  way; a no-op if nothing's blank.
- **Overwrite + Force**: the only combination that reliably rewrites
  everything, since Overwrite always writes the full fresh match regardless
  of what's already there.

### 3. Match badges (main section)

The centerpiece: every status/badge a book can show in a report, and what it
means for that file. Each entry pairs a small rendered badge sample with its
explanation (reuse the actual CSS classes: `match-status-badge`,
`match-manual-badge`, `match-score-badge`, `match-mode-badge`,
`match-provider-badge`, `match-write-badge`, `reason-badge` +
`danger`/`recommended` modifiers) so what's shown matches exactly what
appears in a real report.

Status badges (`matchStatusInfo` in `app.js`):
- **Matched** (green): a confident match was found; will write or wrote
  metadata per the active write/edit mode.
- **Smart-skipped**: write mode is Smart and every checked field already
  matched; nothing written.
- **Skipped, `<reason>`**: explicitly excluded before matching (skip
  pattern, ignored folder).
- **Not Matched**: no confident match found; needs Manual Review.
- **Error**: something failed while processing this file.

Flags/badges shown alongside status:
- **Manually Applied**: this book's metadata was set by hand via Manual
  Review, not the automatic run.
- **Score badge** (e.g. `87%`): match confidence.
- **Mode badge**: Full or Series only, whichever was used.
- **Provider badge**: which source produced the match. Audible, ABS,
  abs-agg (LibriVox, Storytel, Audioteka, BookBeat, Big Finish, ARD
  Audiothek, Die drei ???), GraphicAudio, Soundbooth Theater, Goodreads, or
  Kindle.
- **Write-action badge**: what actually happened on disk. Written,
  smart-skipped, no-op, skipped, or error.
- **Reason tags** (Manual Review list): red/`danger`: `no match`, `asin
  conflict`, `low score`, `missing metadata`, `unsafe match`, `no metadata`,
  `status:skipped`, `mode:none`, or an N% duration-diff tag. Green/
  `recommended`: `manually applied`.

### 4. metadata.json (its own section)

- What it is: an Audiobookshelf-native `metadata.json` sidecar, written for
  every matched book. LibraForge's one guaranteed, universal output,
  independent of audio format or whether embedded-tag writing is even
  possible/desired (`--metadata-json-only` skips tags entirely; metadata.json
  is written either way).
- On repeat runs it follows the same write-mode skip logic as tags (no
  needless rewrite once nothing's changed), but it is not the same file as
  `libraforge.json`, which sits right alongside it and holds LibraForge's own
  internal tracking (whether/how a book was processed, cached duration data,
  etc.).
- **Because they're separate files:** if you use Audiobookshelf's own "save
  metadata to file" feature (editing metadata inside ABS itself), ABS
  overwrites `metadata.json` with its version. This is safe. It never
  touches `libraforge.json`, so LibraForge still knows what it already did
  and won't reprocess or conflict on the next run.
- **Recommended metadata priority**, per Audiobookshelf's own documented
  scanning behavior: **metadata.json, then embedded tags, then
  folder/filename structure**. metadata.json wins, so it's the authoritative
  source for what Audiobookshelf displays; embedded tags matter mainly for
  portability outside ABS (playing the file elsewhere); folder structure is
  ABS's last resort when nothing else is present.

### 5. Report types

Short reference list: what each tool produces and where.
- **Metadata Forge report**: per-book match/write outcome (the badges
  above), downloadable after a run.
- **M4B Tool report**: conversion/merge outcomes.
- **Folder Forge report**: planned/applied moves.
- **Library Downloader report**: per-book download outcome.
- **Suspect Report**: generated on demand from an existing Metadata Forge
  report; re-checks `Matched` items for signs of a false-positive match
  (series/title confusion) without re-running the whole match pipeline.

### 6. Owned badge & duplicate handling (Library Downloader)

- **Owned** badge: this title's ASIN is already in your Audiobookshelf
  library (or, if ABS isn't connected, found via a local ASIN-tag scan
  fallback).
- Duplicate handling when downloading an Owned title: **Keep both copies**,
  **Replace the existing copy**, or **Choose per item**.

## Implementation notes

- Static HTML content. All of this terminology is fixed by the code, not
  runtime data, so no API calls or dynamic rendering are needed. Just markup
  plus the existing badge CSS classes for the sample chips.
- New CSS is limited to whatever's needed for the guide's own layout
  (spacing, maybe a two-column badge-sample-plus-description row); no changes
  to the badge classes themselves. They're reused as-is so samples are
  pixel-identical to real reports.
- No backend changes. No new API routes. No new JS state beyond whatever
  minimal script (if any) is needed to keep the nested Smart-mode `<details>`
  independent of the page's other disclosure toggles (likely none needed;
  native `<details>` behavior is sufficient).

## Out of scope

- Cleanup modes (Settings' danger-zone file cleanup options). Not part of
  this guide, different audience/context.
- M4B Tool's codec/bitrate options. Not part of this guide.
- Making this content dynamic/data-driven. It's reference material for
  fixed concepts, not something that needs to reflect live run state.
