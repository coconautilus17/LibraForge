"""Which Audible listing is this audio? Compare chapter layouts.

Two listings of one book (a US and a UK recording) can share title, author
and nearly the runtime, but their chapter lengths differ. This compares the
file's embedded chapters (ffprobe) with each ASIN's chapter list from
Audible's public catalog (no login) and counts the chapters whose lengths
agree within a tolerance.

usage: chapter_match.py <audio file> <ASIN> [<ASIN> ...] [--tolerance 3] [--region us]

Example (the Jack Reacher check): 47/48 chapters matched B07DK1BBS6 (Scott
Brick), 1/47 matched B079Y7KRKL (Jeff Harding), so the file is the Brick
recording whatever its tags claim.
"""
import argparse
import json
import subprocess
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("/dev/", 1)[0])
from app.fixer.search import PUBLIC_AUDIBLE_DOMAINS  # noqa: E402


def file_chapters(path: str) -> list[float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", path],
        capture_output=True, text=True, check=True,
    ).stdout
    return [float(c["end_time"]) - float(c["start_time"]) for c in json.loads(out).get("chapters", [])]


def audible_chapters(asin: str, region: str) -> list[float]:
    domain = PUBLIC_AUDIBLE_DOMAINS.get(region, "audible.com")
    url = (f"https://api.{domain}/1.0/content/{asin}/metadata"
           "?response_groups=chapter_info&chapter_titles_type=Flat")
    with urllib.request.urlopen(url, timeout=30) as resp:
        chapters = json.load(resp)["content_metadata"]["chapter_info"]["chapters"]
    return [c["length_ms"] / 1000 for c in chapters]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("asins", nargs="+")
    ap.add_argument("--tolerance", type=float, default=3.0, help="seconds")
    ap.add_argument("--region", default="us")
    args = ap.parse_args()

    local = file_chapters(args.file)
    print(f"file: {len(local)} chapters, {sum(local) / 60:.0f} min")
    for asin in args.asins:
        try:
            remote = audible_chapters(asin, args.region)
        except Exception as exc:  # one bad ASIN shouldn't stop the rest
            print(f"{asin}: no chapter list ({exc})")
            continue
        close = sum(1 for a, b in zip(local, remote) if abs(a - b) <= args.tolerance)
        print(f"{asin}: {len(remote)} chapters, {sum(remote) / 60:.0f} min, "
              f"{close}/{min(len(local), len(remote))} lengths within {args.tolerance:g} s")


if __name__ == "__main__":
    main()
