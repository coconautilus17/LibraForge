"""Build the benchmark dataset from a library's original-tag backups.

Every audiobook folder whose libraforge.json kept the file's original tags
(backup.format_tags, captured before LibraForge first wrote anything) becomes
one mock book: those tags, the original duration, and the folder path. The
staging folder (_unorganized) is included; the NAS recycle bin and hidden
folders are not. A book whose marker holds an applied real ASIN gets it as the
reference answer; the rest are reported by outcome but not scored.

A multi-file folder is kept when its backup names one of its files: that is
the only file whose original tags were saved.

usage: collect.py [--root /mnt/audiobooks] [--out data/full.json]
                  [--sample N --seed S --sample-out data/sample.json]
       collect.py --import dump.json [--import ...] [--merge data/complete.json] --out data/x.json

--import takes an ffprobe tag dump instead of the library: a JSON list of {"path",
"filename", "duration" (seconds), "tags"} per file, e.g. another library's files before
matching (run overlap.py first to drop the books you already have). Those books have no
applied ASIN, so a file name in "Author; Series; Book NN; Title" form becomes the
reference: the audit checks that a pick is that book (author, plus series and number or
title), not which recording. --merge prepends an existing dataset.

The output holds your library's titles, tags and paths: it stays in data/,
which is gitignored. Never commit it.
"""
import argparse
import json
import os
import random
import re

BOOK_LABEL = r"(?:book|vol\.?|volume)"
AUDIO = (".m4b", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".flac", ".aac")
HERE = os.path.dirname(os.path.abspath(__file__))


def collect(root: str) -> list[dict]:
    books = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "#")) and d != "@eaDir"]
        if "libraforge.json" not in filenames:
            continue
        audio = [f for f in filenames if f.lower().endswith(AUDIO)]
        if not audio:
            continue
        try:
            with open(os.path.join(dirpath, "libraforge.json"), encoding="utf-8") as fh:
                sidecar = json.load(fh)
        except (OSError, ValueError):
            continue
        backup, marker = sidecar.get("backup") or {}, sidecar.get("marker") or {}
        tags = backup.get("format_tags") or {}
        if sidecar.get("media_type") == "ebook" or not tags or not backup.get("duration_minutes"):
            continue
        if len(audio) > 1:
            if backup.get("source_file") not in audio:
                continue
            audio = [backup["source_file"]]
        audible = marker.get("audible") or {}
        asin = str(audible.get("asin") or "").upper()
        if not (marker.get("applied") and re.fullmatch(r"[B0-9][0-9A-Z]{9}", asin)):
            asin = ""
        books.append({
            "folder": os.path.relpath(dirpath, root),
            "file": audio[0],
            "asin": asin,
            "manual": bool(marker.get("manually_applied")),
            "minutes": backup["duration_minutes"],
            "tags": tags,
            "final": {k: audible.get(k, "") for k in ("title", "author", "narrator", "series", "sequence")},
        })
    return books


def book_number(label: str) -> str:
    """"1", "1.5" or "1-3" from "Book 01", "Vol. 1.5", "Book 01-03"; "" otherwise."""
    m = re.fullmatch(rf"\s*{BOOK_LABEL}\s*0*(\d+(?:\.\d+)?(?:\s*-\s*0*\d+)?)\s*", label or "", re.I)
    return re.sub(r"(^|-)0+(?=\d)", r"\1", re.sub(r"\s", "", m.group(1))) if m else ""


def parse_dump_name(filename: str) -> tuple[str, str, str]:
    """(series, number, title) from "Author; Series; Book NN; Title.m4b"; blanks otherwise.

    "Author; Attached; The New Science of ..." has no number: its two parts are a title
    and subtitle in either order ("...; Why We Do What We Do...; The Power of Habit"),
    so both are the title, and a pick's title held in it names the book."""
    f = re.sub(r"\.[a-z0-9]+$", "", filename, flags=re.I).split("; ")
    if len(f) == 3 and not book_number(f[2]):
        return "", "", f"{f[1]} {f[2]}"
    series, number = (f[1], book_number(f[2])) if len(f) > 2 else ("", "")
    title = f[3] if len(f) > 3 else (f[1] if len(f) == 2 else "")
    return series, number, title


def import_dump(path: str) -> list[dict]:
    dump = json.load(open(path, encoding="utf-8"))
    root = os.path.commonpath([os.path.dirname(os.path.dirname(e["path"])) for e in dump])
    books = []
    for e in dump:
        tags = e.get("tags") or {}
        series, number, title = parse_dump_name(e["filename"])
        author = tags.get("artist") or tags.get("album_artist") or ""
        expect = {"title": title, "author": author, "narrator": "", "series": series, "sequence": number}
        books.append({
            "folder": os.path.relpath(os.path.dirname(e["path"]), root),
            "file": e["filename"],
            "asin": "",
            "manual": False,
            "minutes": float(e["duration"]) / 60,
            "tags": tags,
            "final": expect,
            "expect": expect if title or number else None,
            "source": os.path.basename(path),
        })
    return books


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/mnt/audiobooks")
    ap.add_argument("--out", default=os.path.join(HERE, "data", "full.json"))
    ap.add_argument("--sample", type=int, default=0, help="also write a random sample of N scored books")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--sample-out", default=os.path.join(HERE, "data", "sample.json"))
    ap.add_argument("--import", dest="imports", action="append", default=[], help="an ffprobe tag dump (repeatable)")
    ap.add_argument("--merge", help="an existing dataset to prepend")
    args = ap.parse_args()

    if args.imports:
        books = [b for path in args.imports for b in import_dump(path)]
        print(f"imported {len(books)} (with a file-name reference {sum(bool(b['expect']) for b in books)})")
    else:
        books = collect(args.root)
    if args.merge:
        base = json.load(open(args.merge, encoding="utf-8"))
        clash = {b["folder"] for b in base} & {b["folder"] for b in books}
        if clash:
            raise SystemExit(f"{len(clash)} folders already in {args.merge}, e.g. {sorted(clash)[0]}")
        books = base + books
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(books, fh, ensure_ascii=False)
    staged = sum(b["folder"].startswith("_unorganized") for b in books)
    print(f"books {len(books)} (with reference {sum(bool(b['asin']) for b in books)}, "
          f"_unorganized {staged}) -> {args.out}")

    if args.sample:
        scored = [b for b in books if b["asin"]]
        sample = random.Random(args.seed).sample(scored, min(args.sample, len(scored)))
        with open(args.sample_out, "w", encoding="utf-8") as fh:
            json.dump(sample, fh, ensure_ascii=False)
        print(f"sample {len(sample)} (seed {args.seed}) -> {args.sample_out}")


if __name__ == "__main__":
    main()
