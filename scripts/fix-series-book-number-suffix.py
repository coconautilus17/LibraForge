#!/usr/bin/env python3
"""One-time backfill for a series name that already has its book number baked
into the text (dry run by default). See app/fixer/scoring.py's
split_series_trailing_number() -- the fixer now applies that rule to every
fresh Audible match automatically; this script is only for data written
before that existed.

Scans libraforge.json's marker.audible.series by default, and -- with
--tags -- also the embedded series tag (MP4 freeform ----:com.apple.iTunes:mvnm
/mvin, or ID3 TXXX:mvnm / TXXX:mvin / TXXX:series-part), using the exact same
tag names app/fixer/tagging.py writes so a fix here round-trips cleanly
through the same code path a fresh match would use.

NEVER touches metadata.json's own "series" field, which is Audiobookshelf's
own format and is *supposed* to look like "Name #N" (ABS has no separate
sequence field there; it parses the number back out of the string itself).
Stripping the suffix there would be a real regression, not a fix.

Two patterns:
  A) "<Series>, Book #N" / ", Vol. N" / ", Volume N" (case-insensitive) --
     unambiguous wording, the same rule the live fixer now applies. Always
     safe to clean; the captured number only fills an empty sequence field,
     never overwrites one that disagrees (see CONFLICT below).
  B) A trailing number set off from the base by "#", "," or "-"
     ("Ard's Oath #3", "Dragon Heart #18") -- one of those characters right
     before the number is a real signal that it was appended as metadata,
     not typed as part of the title. A number with nothing but a space
     before it ("Ultimate Level 1", "Beacon 23", "Azarinth Healer 4") is
     deliberately NOT matched at all, not even as UNCERTAIN: nothing at a
     single-book level can tell a duplicated book number apart from a real
     title/series that just ends in a digit, and guessing wrong is exactly
     what happened here -- an earlier version of this script "confirmed"
     11 real "Ultimate Level 1" books as safe to clean to "Ultimate Level"
     using only sibling evidence, before Audiobookshelf's own independently-
     sourced metadata.json proved "Ultimate Level 1" was the real series
     name all along. Even with the "#"/","/"-" separator required, Pattern B
     still requires the one signal that actually distinguishes "duplicated
     book number" from "the series is just named that": a SEPARATE record,
     same author, whose series is the bare base with NO number at all
     ("Ard's Oath", not "Ard's Oath 3") -- proof the number-free form is a
     thing that really exists for this series. Multiple books sharing the
     identical numbered text with different real sequences is NOT that
     signal by itself -- that is exactly what a normal, correctly-numbered
     series looks like, so it can never earn CLEAN_ONLY/FILL_SEQUENCE/
     SAME_TEXT_DIFFERENT_BOOKS on its own.

Every match lands in one of four buckets:
  CLEAN_ONLY      -- existing sequence already agrees with the captured number.
  FILL_SEQUENCE   -- existing sequence is empty; fills it from the captured number.
  SAME_TEXT_DIFFERENT_BOOKS -- (Pattern B, WITH a plain-sibling) the identical
                     (wrong) series text appears on 2+ books with *different*
                     real sequence numbers -- proof the text is a copy-pasted
                     title, not a per-book number. The text is cleaned; each
                     book's own existing sequence is left untouched (the
                     captured number is discarded, not written).
  CONFLICT        -- a single book's own captured number disagrees with its own
                     existing sequence, with no corroborating evidence either
                     way. Left alone; printed for a human to decide.
Pattern B with no plain-sibling evidence at all -- including the
same-text-recurs-with-different-sequences case -- is left alone too, printed
separately as UNCERTAIN.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    from app.fixer.scoring import SERIES_TRAILING_NUMBER_RE, split_series_trailing_number
    from app.fixer.tagging import id3_set_txxx, mp4_set_freeform
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.fixer.scoring import SERIES_TRAILING_NUMBER_RE, split_series_trailing_number
    from app.fixer.tagging import id3_set_txxx, mp4_set_freeform

SERVICE_PREFIXES = ("_", "#", "@", ".")
AUDIO_EXTENSIONS = {".m4b": "mp4", ".m4a": "mp4", ".mp3": "id3"}
# A trailing number set off by "#", "," or "-" (not just a space -- see the
# module docstring for why a bare-space number is never matched at all).
# 1-3 digits only, so a 4-digit year ("Foundation 1965") is never mistaken
# for a sequence.
_BARE_NUMBER_RE = re.compile(r"^(?P<base>.+?)\s*[#,-]\s*(?P<num>\d{1,3})$")


_NUMERIC_RANGE_RE = re.compile(r"\d+\s*-\s*\d+$")


def _bare_number_split(series: str) -> tuple[str, str] | None:
    series = series.strip()
    if _NUMERIC_RANGE_RE.search(series):
        # "Book #1-5" is an omnibus/bundle description (books 1 through 5
        # collected), not a duplicated book number -- the "-" here is a
        # range, not Pattern B's separator. Real case: "Beacon 23, Book
        # #1-5" was otherwise mis-split into base "Beacon 23, Book #1" / "5".
        return None
    match = _BARE_NUMBER_RE.match(series)
    if not match:
        return None
    base = match.group("base").strip().rstrip(",-").strip()
    if len(base) < 3 or not any(c.isalpha() for c in base):
        return None
    return base, match.group("num")


def _iter_libraforge_json(root: Path):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(SERVICE_PREFIXES)]
        if "libraforge.json" not in files:
            continue
        path = Path(dirpath) / "libraforge.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        marker = (data.get("marker") or {}).get("audible")
        if not isinstance(marker, dict):
            continue
        series = marker.get("series")
        if isinstance(series, str) and series:
            author_dir = path.relative_to(root).parts[0]
            yield path, series, marker.get("sequence"), author_dir, "json"


def _mp4_freeform_str(tags, name: str) -> str:
    values = tags.get(f"----:com.apple.iTunes:{name}") or []
    if not values:
        return ""
    value = values[0]
    return bytes(value).decode("utf-8", "replace") if value else ""


def _iter_embedded_tags(root: Path):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(SERVICE_PREFIXES)]
        rel_parts = Path(dirpath).relative_to(root).parts
        author_dir = rel_parts[0] if rel_parts else ""
        for name in files:
            kind = AUDIO_EXTENSIONS.get(Path(name).suffix.lower())
            if not kind:
                continue
            path = Path(dirpath) / name
            try:
                if kind == "mp4":
                    from mutagen.mp4 import MP4
                    tags = MP4(path).tags or {}
                    series = _mp4_freeform_str(tags, "mvnm")
                    sequence = _mp4_freeform_str(tags, "mvin") or None
                else:
                    from mutagen.id3 import ID3
                    tags = ID3(path)
                    series = str(tags["TXXX:mvnm"].text[0]) if "TXXX:mvnm" in tags else ""
                    sequence = None
                    if "TXXX:mvin" in tags:
                        sequence = str(tags["TXXX:mvin"].text[0])
                    elif "TXXX:series-part" in tags:
                        sequence = str(tags["TXXX:series-part"].text[0])
            except Exception:
                continue
            if series:
                yield path, series, sequence, author_dir, kind


def _num_matches(a: str, b: str) -> bool:
    return a.lstrip("0") == b.lstrip("0")


def plan_series_number_changes(root: Path, include_tags: bool = False) -> list[dict]:
    """Every series value (libraforge.json's marker.audible.series, plus the
    embedded series tag when include_tags is set) with a book number baked
    into the text, classified per the module docstring."""
    records = list(_iter_libraforge_json(root))
    if include_tags:
        records += list(_iter_embedded_tags(root))

    # Bases seen as a genuinely plain series (no suffix at all) -- sibling
    # evidence pattern B needs to fire at all on a single occurrence.
    plain_by_author: dict[str, set[str]] = defaultdict(set)
    # For a bare-number match, the literal text is always "<base> <num>" --
    # identical text recurring on different real books (different existing
    # sequence values) is proof the number is a copy-pasted title fragment,
    # not that book's own position. Grouped by the exact (base, num) the text
    # itself encodes, tracking every existing_seq seen for it.
    existing_seqs_by_author_base_num: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for _path, series, seq, author_dir, _kind in records:
        if split_series_trailing_number(series, "")[0] == series and not _bare_number_split(series):
            plain_by_author[author_dir].add(series.strip().lower())
        bare = _bare_number_split(series)
        if bare:
            existing = str(seq).strip() if seq not in (None, "") else ""
            existing_seqs_by_author_base_num[(author_dir, bare[0].strip().lower(), bare[1])].add(existing)

    changes = []
    for path, series, sequence, author_dir, kind in records:
        existing_seq = str(sequence).strip() if sequence not in (None, "") else ""

        book_match = SERIES_TRAILING_NUMBER_RE.search(series)
        if book_match:
            cleaned = SERIES_TRAILING_NUMBER_RE.sub("", series).strip()
            captured = book_match.group("num")
            if not existing_seq:
                status, new_seq = "FILL_SEQUENCE", captured
            elif _num_matches(existing_seq, captured):
                status, new_seq = "CLEAN_ONLY", existing_seq
            else:
                status, new_seq = "CONFLICT", None
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": cleaned,
                             "old_sequence": existing_seq, "new_sequence": new_seq, "status": status})
            continue

        bare = _bare_number_split(series)
        if not bare:
            continue
        base, num = bare
        base_key = base.strip().lower()
        seen_for_this_text = existing_seqs_by_author_base_num[(author_dir, base_key, num)]
        recurs_with_different_books = len(seen_for_this_text) > 1
        # A number-free sibling record is the only real evidence the number
        # is a duplicated book-position rather than just how this series is
        # named -- see the module docstring for why recurs_with_different_books
        # can never stand in for it.
        has_plain_sibling = base_key in plain_by_author[author_dir]

        if not has_plain_sibling:
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": base,
                             "old_sequence": existing_seq, "new_sequence": None, "status": "UNCERTAIN"})
        elif recurs_with_different_books:
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": base,
                             "old_sequence": existing_seq, "new_sequence": None, "status": "SAME_TEXT_DIFFERENT_BOOKS"})
        elif not existing_seq:
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": base,
                             "old_sequence": existing_seq, "new_sequence": num, "status": "FILL_SEQUENCE"})
        elif _num_matches(existing_seq, num):
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": base,
                             "old_sequence": existing_seq, "new_sequence": num, "status": "CLEAN_ONLY"})
        else:
            changes.append({"path": str(path), "kind": kind, "old_series": series, "new_series": base,
                             "old_sequence": existing_seq, "new_sequence": None, "status": "CONFLICT"})
    return changes


def _apply_json(path: Path, series: str, sequence: str | None) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    marker = data["marker"]["audible"]
    marker["series"] = series
    if sequence is not None:
        marker["sequence"] = sequence
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _apply_mp4(path: Path, series: str, sequence: str | None) -> None:
    from mutagen.mp4 import MP4
    audio = MP4(path)
    mp4_set_freeform(audio.tags, "mvnm", series)
    if sequence is not None:
        mp4_set_freeform(audio.tags, "mvin", sequence)
    audio.save()


def _apply_id3(path: Path, series: str, sequence: str | None) -> None:
    from mutagen.id3 import ID3
    audio = ID3(path)
    id3_set_txxx(audio, "mvnm", series)
    if sequence is not None:
        id3_set_txxx(audio, "mvin", sequence)
        id3_set_txxx(audio, "series-part", sequence)
    audio.save()


_APPLY_BY_KIND = {"json": _apply_json, "mp4": _apply_mp4, "id3": _apply_id3}


def sync_metadata_json_series(book_folder: Path) -> None:
    """Keep metadata.json's own "Name #N" series field (Audiobookshelf's
    format, see the module docstring) in sync with marker.audible.series +
    sequence -- it's *derived* from those, not edited directly by this
    script's plan/apply, but nothing else regenerates it either. Real
    books fixed here still showed the old dirty text afterward (some of it
    doubled, "Name, Book #N #N", from the write-time formula appending
    "#{sequence}" onto an already-dirty series name) simply because
    metadata.json had baked that text in before the marker was ever fixed.
    Called after every apply_change/revert so it never drifts again.
    """
    libraforge_json = book_folder / "libraforge.json"
    metadata_json = book_folder / "metadata.json"
    if not libraforge_json.exists() or not metadata_json.exists():
        return
    marker = (json.loads(libraforge_json.read_text(encoding="utf-8")).get("marker") or {}).get("audible") or {}
    series = marker.get("series")
    if not series:
        return
    sequence = marker.get("sequence")
    expected = f"{series} #{sequence}" if sequence else series
    data = json.loads(metadata_json.read_text(encoding="utf-8"))
    current = (data.get("series") or [None])[0]
    if current == expected:
        return
    data["series"] = [expected]
    tmp = metadata_json.with_suffix(metadata_json.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, metadata_json)


def apply_change(change: dict) -> None:
    path = Path(change["path"])
    _APPLY_BY_KIND[change["kind"]](path, change["new_series"], change["new_sequence"])
    sync_metadata_json_series(path.parent)


def revert(log_path: Path) -> None:
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for entry in reversed(entries):
        old_sequence = entry["old_sequence"] if entry["new_sequence"] is not None else None
        path = Path(entry["path"])
        _APPLY_BY_KIND[entry["kind"]](path, entry["old_series"], old_sequence)
        sync_metadata_json_series(path.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", type=Path, help="Library root, e.g. /audiobooks")
    parser.add_argument("--tags", action="store_true", help="Also scan/fix the embedded series tag, not just libraforge.json")
    parser.add_argument("--apply", action="store_true", help="Make the changes (default: dry run)")
    parser.add_argument("--log", type=Path, help="JSONL change log (default: reports/series-booknum-fix-<time>.jsonl)")
    parser.add_argument("--revert", type=Path, help="Undo the changes recorded in this log")
    args = parser.parse_args()

    if args.revert:
        revert(args.revert)
        print(f"Reverted changes from {args.revert}")
        return 0

    changes = plan_series_number_changes(args.root, include_tags=args.tags)
    by_status: dict[str, list[dict]] = defaultdict(list)
    for change in changes:
        by_status[change["status"]].append(change)

    safe = by_status["CLEAN_ONLY"] + by_status["FILL_SEQUENCE"] + by_status["SAME_TEXT_DIFFERENT_BOOKS"]
    for status in ("CLEAN_ONLY", "FILL_SEQUENCE", "SAME_TEXT_DIFFERENT_BOOKS"):
        for change in by_status[status]:
            print(f"  {status:26} [{change['kind']}] {change['old_series']!r} -> {change['new_series']!r}  ({change['path']})")
    print(f"\nSafe to fix automatically: {len(safe)}")
    for status in ("CONFLICT", "UNCERTAIN"):
        rows = by_status[status]
        if not rows:
            continue
        print(f"\n{status}, needs a human decision ({len(rows)}):")
        for change in rows:
            print(f"  [{change['kind']}] {change['old_series']!r} (existing sequence: {change['old_sequence']!r})  ({change['path']})")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to make the safe changes.")
        return 0

    log_path = args.log or Path("reports") / f"series-booknum-fix-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for change in safe:
            apply_change(change)
            log.write(json.dumps(change, ensure_ascii=False) + "\n")
    print(f"\nDone. {len(safe)} entries fixed. Change log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
