"""Build BookOrbit mockup files: 1 s of silence carrying each book's original tags,
at its real Author/Title path. BookOrbit never reads duration when matching.

usage: bo_mock.py <books.json> <out_root> [--itunes]   (out_root under data/, e.g. data/bo_books)

M4B tags are written as custom keys by default, which ffprobe-based readers (BookOrbit,
Audiobookshelf) see whatever their name. --itunes writes the standard iTunes atoms
instead, for mutagen-based readers (beets): ffmpeg then keeps only the keys it maps.

Mount out_root read-only into the BookOrbit container and add it as a library.
"""
import json
import os
import subprocess
import sys

sample, out_root = json.load(open(sys.argv[1])), sys.argv[2]
itunes = "--itunes" in sys.argv[3:]
# Container/encoder bookkeeping, not book metadata.
SKIP = {"major_brand", "minor_version", "compatible_brands", "encoder", "gapless_playback",
        "media_type", "creation_time", "handler_name", "vendor_id", "itunsmpb", "itunnorm"}

ok = failed = 0
for book in sample:
    stem, ext = os.path.splitext(book["file"])
    mp3 = ext.lower() == ".mp3"
    dst = os.path.join(out_root, book["folder"], stem + (".mp3" if mp3 else ".m4b"))
    if os.path.exists(dst):
        ok += 1
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "1"]
    cmd += ["-c:a", "libmp3lame", "-b:a", "32k", "-id3v2_version", "3"] if mp3 else \
           ["-c:a", "aac", "-b:a", "16k", *([] if itunes else ["-movflags", "use_metadata_tags"]), "-f", "mp4"]
    for key, value in book["tags"].items():
        if key.lower() not in SKIP and value not in (None, ""):
            cmd += ["-metadata", f"{key}={value}"]
    r = subprocess.run(cmd + [dst], capture_output=True, text=True)
    if r.returncode == 0:
        ok += 1
    else:
        failed += 1
        print("FAIL", book["folder"], r.stderr[:200], flush=True)
print("built", ok, "failed", failed)
