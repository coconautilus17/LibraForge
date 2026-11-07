"""Build BookOrbit mockup files: 1 s of silence carrying each book's original tags,
at its real Author/Title path. BookOrbit never reads duration when matching.

usage: bo_mock.py <books.json> <out_root> [--itunes] [--runtime]   (out_root under data/, e.g. data/bo_books)

M4B tags are written as custom keys by default, which ffprobe-based readers (BookOrbit,
Audiobookshelf) see whatever their name. --itunes writes the standard iTunes atoms
instead, for mutagen-based readers (beets): ffmpeg then keeps only the keys it maps.
--runtime makes each file as long as the book (its "minutes"), for a tool that reads
the runtime when matching (AudioSilo): an hour of 8 kbps silence, built once next to
out_root and repeated without re-encoding, about 0.23 MB per hour.

Mount out_root read-only into the BookOrbit container and add it as a library.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sample, out_root = json.load(open(sys.argv[1])), sys.argv[2]
itunes = "--itunes" in sys.argv[3:]
runtime = "--runtime" in sys.argv[3:]
# Container/encoder bookkeeping, not book metadata.
SKIP = {"major_brand", "minor_version", "compatible_brands", "encoder", "gapless_playback",
        "media_type", "creation_time", "handler_name", "vendor_id", "itunsmpb", "itunnorm"}

silence = {}
if runtime:
    for kind, codec in (("m4a", ["-c:a", "aac", "-b:a", "8k", "-f", "mp4"]),
                        ("mp3", ["-c:a", "libmp3lame", "-b:a", "8k"])):
        silence[kind] = f"{out_root.rstrip('/')}.silence-1h.{kind}"
        if not os.path.exists(silence[kind]):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                            "-t", "3600", *codec, silence[kind]], check=True)


def build(book):
    """True when the book's file is there (built now or before), else False."""
    stem, ext = os.path.splitext(book["file"])
    mp3 = ext.lower() == ".mp3"
    dst = os.path.join(out_root, book["folder"], stem + (".mp3" if mp3 else ".m4b"))
    if os.path.exists(dst):
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if runtime:
        seconds = str(round(float(book["minutes"]) * 60))
        cmd = ["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", silence["mp3" if mp3 else "m4a"],
               "-t", seconds, "-map_metadata", "-1", "-c:a", "copy"]
    else:
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "1"]
        cmd += ["-c:a", "libmp3lame", "-b:a", "32k"] if mp3 else ["-c:a", "aac", "-b:a", "16k"]
    cmd += ["-id3v2_version", "3", "-f", "mp3"] if mp3 else \
           [*([] if itunes else ["-movflags", "use_metadata_tags"]), "-f", "mp4"]
    for key, value in book["tags"].items():
        if key.lower() not in SKIP and value not in (None, ""):
            cmd += ["-metadata", f"{key}={value}"]
    r = subprocess.run(cmd + [dst + ".part"], capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL", book["folder"], r.stderr[:200], flush=True)
        return False
    os.replace(dst + ".part", dst)  # a stopped build leaves no half-written book
    return True


with ThreadPoolExecutor(8) as pool:  # ffmpeg is one process per book
    built = list(pool.map(build, sample))
ok, failed = built.count(True), built.count(False)
print("built", ok, "failed", failed)
