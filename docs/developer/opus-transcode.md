# Opus transcode (DEV / WIP)

**Status: work in progress, dev only.** The section on the M4B Tool page is hidden unless the
server runs with `LIBRAFORGE_DEV_FEATURES=opus_transcode` (or `all`); the endpoint answers 404
otherwise. Settings, wording and behavior may still change, and it is not in the user guide.

It re-encodes audiobooks to Opus inside an `.m4b`, merging multi-file books into one file with one
chapter per part, and writes the result to a **staging folder**. Originals are only read. Putting
converted books in place of the originals is not built yet.

## Pieces

| File | Role |
|---|---|
| `scripts/opus-transcode.py` | The engine: plan, mono test, encode, verify, sidecar. Dry run unless `--apply`. Port of the hand-run library conversion of Oct to Nov 2026. |
| `app/opus_transcode.py` | Dev flag, request model and validation, command builder, parser for the script's `OPUS_*_JSON` lines. |
| `app/main.py` | `POST /api/opus/runs` and `run_opus_transcode_worker` (same `RunState` / `stream_process_output` path as the other runs; status through `GET /api/runs/{id}`). `/api/config` returns `dev_features`. |
| `app/static/opus-transcode.js` | The section: settings, command preview, plan/results table, live output. Self-contained, so it never touches the merge controls. |
| `app/tests/test_opus_transcode.py` | Flag, command, parsing and planning decisions. |

The script prints `OPUS_PLAN_JSON` (one per book), `OPUS_RESULT_JSON` (one per converted book) and
`OPUS_SUMMARY_JSON`, plus a readable line for each; the app folds the JSON into
`stats["opus"]` (`plan`, `results`, `summary`), so the saved report holds the whole run.

## What it decides

- **Book identity** comes from sidecars, as everywhere else: `<folder>/libraforge.json` is one
  book, `<file>.libraforge.json` a single-file book, other folders use the fixer's
  `build_multi_part_group_map`.
- **Plan actions**: `CONVERT`; `LEAVE-ALONE` (source at or below `--leave-alone-kbps`, 48 by
  default); `SKIP-SMALL-GAIN` (predicted output above `--max-size-ratio` of the source);
  `SKIP-DONE` (same `opus_conversion.policy`, or already Opus in an m4b); `REVIEW` (unreadable,
  xHE-AAC, or Opus outside a single m4b).
- **Mono test**: a stereo book goes mono only when the side signal (L-R) is at least
  `--side-margin-db` below the mid, or below `--side-floor-db`, in every audible 1-second window.
- **Bitrate**: mono 32k / stereo 48k by default, never above `--src-cap-ratio` (0.8) of the source.
- **Mode**: `celt` (`-application lowdelay`, CELT-only, the default), `auto` (`audio`, libopus picks
  hybrid for speech below about 56k), `voip`.

## Why these defaults

Measured on the same 5 minutes of a 127 kbps stereo AAC narration (identical channels): libopus's
default hybrid mode dips the 4 to 8 kHz band by 2.5 to 4.6 dB at 32k and still at 48k; CELT-only at
32k keeps every band within 0.1 dB of the source at the same file size (28.5 vs 28.6 kbps real).
CELT codes band energy explicitly, so the metric favors it; listening found no other difference.
VBR is on (packet sizes 8 to 240 bytes in real output), 60 ms frames, compression level 10. 32k
mono is near-transparent in Google's MUSHRA test (97.2/100); 24k was rejected by ear. The full
notes are in the section's "Test findings" panel.

## Planned pipeline

Transcode (first: it merges multi-file books) → Metadata Forge match → Folder Forge (destination is
explicit) → Audiobookshelf scan, only when ABS has exactly one library whose folder holds the
destination (with several, the right one cannot be chosen reliably, so the scan is skipped and
reported) → Enrichment Forge → one combined report listing only what needs review.

Known gap seen while testing: Folder Forge's saved structure cache can be stale and miss existing
series folders, so a converted book can land in a differently named sibling folder.

## Trying it

```
docker run ... -e LIBRAFORGE_DEV_FEATURES=opus_transcode -v <staging>:/staging libraforge-libraforge
```

Then M4B Tool → Opus transcode (dev). Use a staging folder outside the folder ABS scans.
Script on its own: `python3 scripts/opus-transcode.py <folder> --staging <dir>` (add `--apply`).
