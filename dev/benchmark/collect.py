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

The output holds your library's titles, tags and paths: it stays in data/,
which is gitignored. Never commit it.
"""
import argparse
import json
import os
import random
import re

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/mnt/audiobooks")
    ap.add_argument("--out", default=os.path.join(HERE, "data", "full.json"))
    ap.add_argument("--sample", type=int, default=0, help="also write a random sample of N scored books")
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--sample-out", default=os.path.join(HERE, "data", "sample.json"))
    args = ap.parse_args()

    books = collect(args.root)
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
