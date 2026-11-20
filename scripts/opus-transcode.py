#!/usr/bin/env python3
"""Opus transcode (DEV / WIP): re-encode audiobooks to Opus-in-m4b in a staging folder, then verify each one.

Ported from the library-wide Opus conversion that was run by hand in Oct-Nov 2026
(3,487 books, 1,950 GB -> 626 GB). Sources are only ever READ. Output goes to
<staging>/<root folder name>/<path relative to the root>/ ; nothing in the library
changes and no original is deleted. Putting the result in place is a separate,
explicit step (not part of this script yet).

Without --apply this is a dry run: it plans every book (convert / leave alone / skip)
and prints the plan, encoding nothing.

Per book:
  1. book identity: where LibraForge keeps its sidecar (<folder>/libraforge.json = one
     book, <file>.libraforge.json = a single-file book); folders without one fall back
     to the fixer's multi-part grouping, the same answer the fixer gives.
  2. channel decision: a stereo source is encoded mono only when its side signal (L-R)
     stays inaudible in EVERY 1-second window of the WHOLE book (mid/side null test).
  3. encode: libopus VBR, mono/stereo target bitrate capped at a ratio of the source
     bitrate, CELT-only by default (see --mode), 60 ms frames, +faststart.
     Multi-file books become one file with one chapter per part.
  4. tags: MP4 sources copy every tag verbatim (freeform atoms, cover); other sources
     go through ffmpeg's metadata mapping plus an attached cover.
  5. verify: codec, channels, duration, chapters (count/offsets/titles), tags, cover,
     atom order (moov before mdat), full audio decode.
  6. sidecar: libraforge.json carried over with an `opus_conversion` block.

Machine-readable lines for the UI: OPUS_PLAN_JSON: {...}, OPUS_RESULT_JSON: {...},
OPUS_SUMMARY_JSON: {...}.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCRIPTS_DIR = Path(__file__).resolve().parent
APP_ROOT = SCRIPTS_DIR.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.library_index import DISC_RE, is_audio_file  # noqa: E402


def _load_fixer():
    """Reuse the fixer for audio sorting, multi-part grouping and sidecar audio summaries."""
    path = SCRIPTS_DIR / "audible-metadata-fixer-v5.py"
    spec = importlib.util.spec_from_file_location("fixer_v5_for_opus", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXER = None  # loaded in main(); tests import this module without it

# ---- settings (defaults = what the hand-run conversion settled on) ----------
MODES = {
    # value of ffmpeg's libopus -application
    "celt": "lowdelay",  # CELT-only. Same size at the same bitrate; keeps 4-8 kHz at the source level.
    "auto": "audio",     # libopus default: picks SILK / hybrid / CELT per frame; speech at <~56k gets hybrid.
    "voip": "voip",      # speech tuning (high-pass, formant emphasis): intelligibility over fidelity.
}
DEFAULTS = {
    "mono_kbps": 32,          # near-transparent for speech (Google MUSHRA 32k = 97.2/100); 24k was rejected by ear
    "stereo_kbps": 48,        # real-stereo books (chosen over 36k)
    "src_cap_ratio": 0.8,     # never ask for more than 80% of the source bitrate
    "leave_alone_kbps": 48,   # sources at or under this are left alone (lossy to lossy at low rates hurts)
    "max_size_ratio": 0.75,   # only convert when the predicted output is <= 75% of the source
    "mode": "celt",
    "frame_ms": 60,           # biggest Opus frame: least per-packet overhead for long files
    "side_margin_db": 30.0,   # a window passes if mid - side >= this ...
    "side_floor_db": -60.0,   # ... or the side itself is below this (inaudible)
}
SILENCE_DB = -60.0  # windows whose mid is below this carry no information
DUR_TOL_S = 0.5
CHAPTER_TOL_S = 0.15
BITRATE_MATCH_TOLERANCE = 0.15
COVER_NAMES = ("cover.jpg", "folder.jpg", "cover.png", "folder.png")
SCHEMA = 1

S = dict(DEFAULTS)  # active settings, replaced by main()
IN_FLIGHT: set[Path] = set()  # .part files being written; removed on cancel


def _handle_sigterm(signum, frame) -> None:
    """Cancel from the UI. Only staging files are ever written, so stop at once and
    remove the half-written ones. (Loading the fixer installs its own SIGTERM handler,
    which only the fixer's loop checks; this replaces it.)"""
    for part in list(IN_FLIGHT):
        for p in (part, part.with_name(part.name + ".chfix")):
            try:
                p.unlink()
            except OSError:
                pass
    print("\nCancelled: stopped; nothing outside the staging folder was touched.", flush=True)
    os._exit(143)


def policy_name(s: dict) -> str:
    """Identifies the settings a book was converted with; a different policy means 'convert again'."""
    return f"mono{s['mono_kbps']}-stereo{s['stereo_kbps']}-{s['mode']}-v2"


def opus_settings(s: dict) -> dict:
    return {"codec": "libopus", "application": MODES[s["mode"]], "vbr": "on",
            "frame_duration_ms": s["frame_ms"], "container": "m4b", "faststart": True}


# ---- small helpers -------------------------------------------------------------
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def ffprobe_json(path: Path, *args) -> dict:
    r = run(["ffprobe", "-v", "error", "-of", "json", *args, str(path)])
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def probe(path: Path) -> dict:
    j = ffprobe_json(path, "-select_streams", "a:0", "-show_entries",
                     "stream=codec_name,profile,channels,sample_rate,bit_rate:format=duration,bit_rate,size")
    try:
        s, fmt = j["streams"][0], j["format"]
        br = s.get("bit_rate") or fmt.get("bit_rate")
        return {"codec": s.get("codec_name"), "profile": s.get("profile"),
                "channels": int(s["channels"]), "sample_rate": int(s["sample_rate"]),
                "kbps": round(int(br) / 1000, 1) if br else None,
                "duration": float(fmt.get("duration") or 0), "size": int(fmt.get("size") or 0)}
    except (KeyError, IndexError, TypeError, ValueError):
        return {"codec": None}


def audio_info(path: Path) -> dict:
    p = probe(path)
    return {"codec": p.get("codec"), "channels": p.get("channels") or 0, "sample_rate": p.get("sample_rate") or 0,
            "duration": p.get("duration") or 0.0, "size": p.get("size") or 0}


def decoded_duration(path: Path) -> float:
    """Exact decoded length (container durations of VBR mp3 / raw aac are estimates)."""
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "null", "-", "-progress", "pipe:1"])
    last = 0.0
    for line in r.stdout.splitlines():
        if line.startswith("out_time_us=") and line.split("=")[1].lstrip("-").isdigit():
            last = max(last, int(line.split("=")[1]) / 1e6)
    return last


def side_check(path: Path, rate: int = 44100) -> dict:
    """Whole-book mid/side null test in 1-second windows."""
    import numpy as np

    p = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                          "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    win = rate * 2 * 4
    worst, worst_at, audible, total, bad = None, None, 0, 0, 0
    while True:
        buf = p.stdout.read(win)
        if len(buf) < win:
            break
        x = np.frombuffer(buf, dtype="<f4").reshape(-1, 2)
        mid, side = 0.5 * (x[:, 0] + x[:, 1]), 0.5 * (x[:, 0] - x[:, 1])
        m = float(10 * np.log10(np.mean(mid * mid) + 1e-20))
        s = float(10 * np.log10(np.mean(side * side) + 1e-20))
        total += 1
        if m > SILENCE_DB:
            audible += 1
            margin = m - s
            if margin < S["side_margin_db"] and s > S["side_floor_db"]:
                bad += 1
            if worst is None or margin < worst:
                worst, worst_at = margin, total - 1
    p.wait()
    return {"worst_margin_db": None if worst is None else round(worst, 1), "worst_at_s": worst_at,
            "audible_windows": audible, "failing_windows": bad, "total_windows": total,
            "passes": audible > 0 and bad == 0}


def tags_of(path: Path) -> dict:
    j = ffprobe_json(path, "-show_entries", "format_tags")
    return {k.lower(): v for k, v in (j.get("format", {}).get("tags") or {}).items()}


def has_picture(path: Path) -> bool:
    return bool(ffprobe_json(path, "-select_streams", "v", "-show_entries", "stream=codec_name").get("streams"))


def write_lf(path: Path, text: str) -> None:
    """LF endings on every OS (ffmpeg's ffmetadata parser does not accept CRLF)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def ffmeta_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")


def ffmeta_chapters(chapters) -> list[str]:
    lines = []
    for start, end, title in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(round(start * 1000))}",
                  f"END={int(round(end * 1000))}", "title=" + ffmeta_escape(title)]
    return lines


def part_title(path: Path, titles_unique: bool, tag_title: str | None) -> str:
    if titles_unique and tag_title:
        return tag_title.strip()
    return re.sub(r"\s+", " ", path.stem).strip()


def is_mp4(path: Path) -> bool:
    return path.suffix.lower() in (".m4b", ".m4a", ".mp4")


# ---- planning ------------------------------------------------------------------
def direct_audio(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and is_audio_file(p)),
                  key=FIXER.natural_audio_sort_key)


def collect_units(root: Path) -> list[dict]:
    """A book is where LibraForge keeps its sidecar (see module docstring). A disc/part-named
    subfolder folds into its parent only when it has no sidecar of its own."""
    units: list[dict] = []
    folders: dict[Path, list[Path]] = {}
    for dirpath, dirnames, _ in os.walk(str(root)):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith((".", "#", "@")))
        p = Path(dirpath)
        files = direct_audio(p)
        if files:
            folders[p] = files

    for folder in sorted(folders):
        if (DISC_RE.match(folder.name) and folder.parent != root
                and not (folder / "libraforge.json").exists()):
            folders.setdefault(folder.parent, [])
            folders[folder.parent] = sorted(folders[folder.parent] + folders.pop(folder),
                                            key=FIXER.natural_audio_sort_key)

    fallback: list[Path] = []
    for folder, files in folders.items():
        folder_lf = folder / "libraforge.json"
        if folder == root:
            for f in files:
                units.append({"kind": "single", "files": [f], "folder": folder,
                              "sidecar": folder_lf if (len(files) == 1 and folder_lf.exists())
                              else f.with_name(f.name + ".libraforge.json")})
            continue
        per_file = [f for f in files if f.with_name(f.name + ".libraforge.json").exists()]
        if len(files) == 1:
            units.append({"kind": "single", "files": files, "folder": folder,
                          "sidecar": folder_lf if folder_lf.exists()
                          else files[0].with_name(files[0].name + ".libraforge.json")})
        elif per_file:
            for f in files:
                units.append({"kind": "single", "files": [f], "folder": folder,
                              "sidecar": f.with_name(f.name + ".libraforge.json")})
        elif folder_lf.exists():
            units.append({"kind": "grouped", "files": files, "folder": folder, "sidecar": folder_lf})
        else:
            fallback.extend(files)

    if fallback:
        accepted = FIXER.build_multi_part_group_map(fallback)
        by_parent: dict[Path, list[Path]] = {}
        for f in fallback:
            by_parent.setdefault(f.parent, []).append(f)
        for parent, files in by_parent.items():
            if parent in accepted:
                units.append({"kind": "grouped", "files": accepted[parent], "folder": parent,
                              "sidecar": parent / "libraforge.json", "flag": "grouped by fixer heuristic, no sidecar"})
            else:
                for f in files:
                    units.append({"kind": "single", "files": [f], "folder": parent,
                                  "sidecar": f.with_name(f.name + ".libraforge.json"), "flag": "no sidecar"})
    for u in units:
        u["root"] = root
    return units


def load_sidecar(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def target_kbps(channels: int, src_kbps: float | None, s: dict) -> int:
    tier = s["mono_kbps"] if channels == 1 else s["stereo_kbps"]
    if src_kbps:
        tier = min(tier, int(src_kbps * s["src_cap_ratio"]))
    return max(tier, 8)


def decide(unit: dict, probes: list[dict], sidecar: dict, s: dict) -> tuple[str, str, dict]:
    """CONVERT, LEAVE-ALONE, SKIP-DONE, SKIP-SMALL-GAIN or REVIEW, with the reason and the numbers."""
    notes: dict = {}
    if any(not p.get("codec") for p in probes):
        return "REVIEW", "ffprobe could not read a file", notes
    if any("xHE" in str(p.get("profile") or "") or "USAC" in str(p.get("profile") or "").upper() for p in probes):
        return "REVIEW", "xHE-AAC source (ffmpeg decode support is limited)", notes

    total_size = sum(p["size"] for p in probes)
    total_dur = sum(p["duration"] for p in probes)
    notes["duration_h"] = round(total_dur / 3600, 2)
    notes["source_mb"] = round(total_size / 1e6)
    channels = max(p["channels"] for p in probes)
    if len({p["channels"] for p in probes}) > 1:
        notes["mixed_channels"] = sorted({p["channels"] for p in probes})
    src_kbps = round(total_size * 8 / total_dur / 1000, 1) if total_dur else None
    notes.update(src_kbps=src_kbps, src_codec=sorted({p["codec"] for p in probes}), channels=channels)
    # the planned stereo target; the null test at encode time may still move a stereo book to mono
    notes["target_kbps"] = target_kbps(channels, src_kbps, s)

    done = sidecar.get("opus_conversion") or {}
    if done.get("status") in ("verified", "replaced") and done.get("policy") == policy_name(s):
        return "SKIP-DONE", "already converted with these settings (opus_conversion in libraforge.json)", notes

    if all(p["codec"] == "opus" for p in probes):
        if len(probes) == 1 and is_mp4(unit["files"][0]):
            return "SKIP-DONE", f"already Opus in m4b (~{src_kbps} kbps)", notes
        return "REVIEW", "already Opus but not a single m4b: needs a stream-copy remux, not a re-encode", notes

    if src_kbps is not None and src_kbps <= s["leave_alone_kbps"]:
        return "LEAVE-ALONE", f"low-bitrate source ({src_kbps} kbps <= {s['leave_alone_kbps']}): a lossy re-encode would cost quality for little space", notes

    predicted = notes["target_kbps"] * 1000 / 8 * total_dur
    notes["predicted_mb"] = round(predicted / 1e6)
    if total_size and predicted > s["max_size_ratio"] * total_size:
        return "SKIP-SMALL-GAIN", f"predicted {notes['predicted_mb']} MB vs {notes['source_mb']} MB source", notes
    return "CONVERT", "", notes


def plan_unit(u: dict) -> dict:
    probes = [probe(f) for f in u["files"]]
    sidecar = load_sidecar(u["sidecar"])
    action, reason, notes = decide(u, probes, sidecar, S)
    flags = [u["flag"]] if u.get("flag") else ([] if sidecar else ["sidecar missing"])
    return {"root": str(u["root"]), "kind": u["kind"], "folder": str(u["folder"]),
            "files": [str(f) for f in u["files"]], "sidecar": str(u["sidecar"]),
            "action": action, "reason": reason, "flags": flags, **notes}


# ---- conversion ----------------------------------------------------------------
def final_name(unit: dict) -> str:
    if unit["kind"] == "grouped":
        return Path(unit["folder"]).name + ".m4b"
    return Path(unit["files"][0]).stem + ".m4b"


def out_path(unit: dict, staging: Path) -> Path:
    root = Path(unit["root"])
    rel = Path(unit["folder"]).relative_to(root)
    return staging.joinpath(root.name, *rel.parts) / final_name(unit)


def folder_cover(folder: Path) -> Path | None:
    return next((p for n in COVER_NAMES if (p := folder / n).exists()), None)


def build_encode_command(unit: dict, files: list[Path], infos: list[dict], mono: bool, tgt: int,
                         tmp: Path, meta_txt: Path) -> tuple[list[str], list[tuple[float, float, str]]]:
    """The ffmpeg command for one book (writes the ffmetadata file it needs). Returns (cmd, chapters)."""
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-stats"]
    chapters: list[tuple[float, float, str]] = []
    downmix = "pan=mono|c0=0.5*c0+0.5*c1"
    if len(files) == 1:
        src = files[0]
        src_ch = ffprobe_json(src, "-show_chapters").get("chapters", [])
        starts = [float(c["start_time"]) for c in src_ch]
        # out-of-order ID3 CHAP frames scramble in the mp4 muxer, and ffmpeg 9 collapses non-mp4
        # chapter lists: hand it explicit, sorted chapters for those
        explicit = starts != sorted(starts) or (not is_mp4(src) and len(src_ch) > 1)
        if explicit:
            ordered = sorted(src_ch, key=lambda c: float(c["start_time"]))
            write_lf(meta_txt, "\n".join([";FFMETADATA1", *ffmeta_chapters(
                (float(c["start_time"]), float(c["end_time"]), (c.get("tags") or {}).get("title", "")) for c in ordered)]) + "\n")
        cmd += ["-i", str(src)]
        if explicit:
            cmd += ["-i", str(meta_txt)]
        cmd += ["-map", "0:a:0"]
        if has_picture(src) and not is_mp4(src):
            cmd += ["-map", "0:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        if mono and infos[0]["channels"] == 2:
            cmd += ["-af", downmix]
        cmd += ["-map_metadata", "0", "-map_chapters", "1" if explicit else "0"]
    else:
        tags = [tags_of(f) for f in files]
        titles = [t.get("title") for t in tags]
        unique = all(titles) and len(set(titles)) == len(titles)
        pos = 0.0
        for i, f in enumerate(files):
            d = decoded_duration(f) if f.suffix.lower() in (".mp3", ".aac") else infos[i]["duration"]
            chapters.append((pos, pos + d, part_title(f, unique, titles[i])))
            pos += d
        first = tags[0]
        book_title = first.get("album") or Path(unit["folder"]).name
        lines = [";FFMETADATA1", f"title={book_title}"]
        lines += [f"{k}={first[k]}" for k in ("artist", "album_artist", "composer", "genre", "date", "comment") if first.get(k)]
        lines.append(f"album={book_title}")
        write_lf(meta_txt, "\n".join(lines + ffmeta_chapters(chapters)) + "\n")
        parts = []
        for i, f in enumerate(files):
            cmd += ["-i", str(f)]
            c = downmix if (mono and infos[i]["channels"] == 2) else ("aformat=channel_layouts=stereo" if not mono else "anull")
            parts.append(f"[{i}:a:0]aresample=48000,{c}[a{i}]")
        cover = folder_cover(Path(unit["folder"])) or next((f for f in files if has_picture(f)), None)
        n = len(files)
        cmd += ["-i", str(meta_txt)]
        if cover:
            cmd += ["-i", str(cover)]
        fc = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
        cmd += ["-filter_complex", fc, "-map", "[out]", "-map_metadata", str(n), "-map_chapters", str(n)]
        if cover:
            cmd += ["-map", f"{n + 1}:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    cmd += ["-c:a", "libopus", "-application", MODES[S["mode"]], "-vbr", "on", "-b:a", f"{tgt}k",
            "-frame_duration", str(S["frame_ms"]), "-movflags", "+faststart", "-f", "mp4", str(tmp)]
    return cmd, chapters


def convert_unit(unit: dict, staging: Path, write_sidecars: bool = True) -> dict:
    from mutagen.mp4 import MP4, MP4Cover

    t0 = time.time()
    files = [Path(f) for f in unit["files"]]
    out = out_path(unit, staging)
    out_dir = out.parent
    res = {"folder": str(unit["folder"]), "files": [str(f) for f in files], "out": str(out), "status": "failed"}
    infos = [audio_info(f) for f in files]
    src_chan = {i["channels"] for i in infos}
    res["src_channels"] = sorted(src_chan)

    # 1. channel decision: the whole-book stereo null test
    checks = [{"file": f.name, **side_check(f)} for f, i in zip(files, infos) if i["channels"] == 2]
    mono = all(c["passes"] for c in checks) if checks else True
    res["stereo_check"] = {"parts": len(checks), "all_pass": mono,
                           "worst_margin_db": min((c["worst_margin_db"] for c in checks if c["worst_margin_db"] is not None), default=None),
                           "failing_windows": sum(c["failing_windows"] for c in checks)}
    tgt = target_kbps(1 if mono else 2, unit.get("src_kbps"), S)
    res["target"] = {"channels": 1 if mono else 2, "bitrate_kbps": tgt}

    # 2. encode
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    meta_txt = out_dir / (out.stem + ".ffmeta.tmp")
    cmd, chapters = build_encode_command(unit, files, infos, mono, tgt, tmp, meta_txt)
    tmp.unlink(missing_ok=True)
    IN_FLIGHT.add(tmp)
    try:
        return _encode_and_finish(unit, files, infos, res, cmd, chapters, tmp, out, out_dir, meta_txt, t0, write_sidecars)
    finally:
        IN_FLIGHT.discard(tmp)


def _encode_and_finish(unit, files, infos, res, cmd, chapters, tmp, out, out_dir, meta_txt, t0, write_sidecars) -> dict:
    from mutagen.mp4 import MP4, MP4Cover

    r = run(cmd)
    meta_txt.unlink(missing_ok=True)
    if r.returncode != 0 or "partial file" in (r.stderr or "") or "Error during demuxing" in (r.stderr or ""):
        res["error"] = (r.stderr or "")[-600:]  # a dropped network read can end ffmpeg early with exit 0
        tmp.unlink(missing_ok=True)
        return res

    # 2b. the mp4 muxer can collapse chapters attached during the encode: compare and remux them in
    if len(files) == 1:
        want = sorted((float(c["start_time"]), float(c["end_time"]), (c.get("tags") or {}).get("title", ""))
                      for c in ffprobe_json(files[0], "-show_chapters").get("chapters", [])
                      if float(c["end_time"]) - float(c["start_time"]) >= 0.1)
    else:
        want = list(chapters)
    got = ffprobe_json(tmp, "-show_chapters").get("chapters", [])
    if want and (len(got) != len(want) or any(abs(float(g["start_time"]) - w[0]) > 0.5 for g, w in zip(got, want))):
        fixed = tmp.with_name(tmp.name + ".chfix")
        fix_meta = out_dir / (out.stem + ".chfix.tmp")
        write_lf(fix_meta, "\n".join([";FFMETADATA1", *ffmeta_chapters(want)]) + "\n")
        pic = ffprobe_json(tmp, "-select_streams", "v", "-show_entries", "stream=codec_name").get("streams") or []
        cover_file = tmp.with_name(tmp.name + (".chfix.png" if pic and pic[0].get("codec_name") == "png" else ".chfix.jpg"))
        if pic:
            run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(tmp), "-map", "0:v:0", "-c", "copy",
                 "-frames:v", "1", str(cover_file)])
        rr = run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(tmp), "-i", str(fix_meta),
                  "-map", "0:a", "-map_metadata", "0", "-map_chapters", "1", "-c", "copy",
                  "-movflags", "+faststart", "-f", "mp4", str(fixed)])
        fix_meta.unlink(missing_ok=True)
        if rr.returncode == 0 and fixed.exists():
            if pic and cover_file.exists() and cover_file.stat().st_size:
                m = MP4(str(fixed))
                if m.tags is None:
                    m.add_tags()
                fmt = MP4Cover.FORMAT_PNG if cover_file.suffix == ".png" else MP4Cover.FORMAT_JPEG
                m.tags["covr"] = [MP4Cover(cover_file.read_bytes(), imageformat=fmt)]
                m.save()
            os.replace(fixed, tmp)
            res["chapters_remuxed"] = True
        else:
            fixed.unlink(missing_ok=True)
            res["chapter_remux_error"] = (rr.stderr or "")[-300:]
        cover_file.unlink(missing_ok=True)

    # 2c. single non-mp4 file without embedded art but with a folder cover: embed it
    if len(files) == 1 and not is_mp4(files[0]) and not has_picture(tmp):
        fc = folder_cover(Path(unit["folder"]))
        if fc is not None:
            try:
                m = MP4(str(tmp))
                if m.tags is None:
                    m.add_tags()
                fmt = MP4Cover.FORMAT_PNG if fc.suffix.lower() == ".png" else MP4Cover.FORMAT_JPEG
                m.tags["covr"] = [MP4Cover(fc.read_bytes(), imageformat=fmt)]
                m.save()
            except Exception as exc:  # noqa: BLE001
                res["folder_cover_error"] = str(exc)

    # 3. verbatim tag copy for MP4 sources (freeform atoms, cover, everything)
    if len(files) == 1 and is_mp4(files[0]):
        try:
            srct, dst = MP4(str(files[0])), MP4(str(tmp))
            if dst.tags is None:
                dst.add_tags()
            for k, v in (srct.tags or {}).items():
                dst.tags[k] = v
            dst.save()
        except Exception as exc:  # noqa: BLE001
            res["tag_copy_error"] = str(exc)
    os.replace(tmp, out)

    # 4. verification
    res["verify"] = verify(files, infos, out, res["target"], unit)
    res["wall_s"] = round(time.time() - t0, 1)
    res["status"] = "verified" if res["verify"]["ok"] else "verify-failed"
    if res["status"] == "verified":
        res.update({"policy": policy_name(S), "settings": opus_settings(S),
                    "src_size": sum(f.stat().st_size for f in files), "out_size": out.stat().st_size})
        if write_sidecars:
            write_sidecar(unit, files, infos, out, res)
    return res


def read_atoms(path: Path) -> list[str]:
    names = []
    with open(path, "rb") as fh:
        while True:
            h = fh.read(8)
            if len(h) < 8:
                break
            size, typ = struct.unpack(">I4s", h)
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
                fh.seek(size - 16, 1)
            elif size == 0:
                break
            else:
                fh.seek(size - 8, 1)
            names.append(typ.decode("latin1"))
    return names


def expected_part_chapters(files, infos):
    tags = [tags_of(f) for f in files]
    titles = [t.get("title") for t in tags]
    unique = all(titles) and len(set(titles)) == len(titles)
    pos, out = 0.0, []
    for i, f in enumerate(files):
        d = decoded_duration(f) if f.suffix.lower() in (".mp3", ".aac") else infos[i]["duration"]
        out.append((pos, part_title(f, unique, titles[i])))
        pos += d
    return out


def verify(files, infos, out: Path, target, unit) -> dict:
    from mutagen.mp4 import MP4

    checks: dict = {}
    oi = audio_info(out)
    exp_dur = sum(decoded_duration(f) if f.suffix.lower() in (".mp3", ".aac") else i["duration"]
                  for f, i in zip(files, infos))
    checks["codec_opus"] = oi["codec"] == "opus"
    checks["channels"] = oi["channels"] == target["channels"]
    tol = DUR_TOL_S + 0.06 * (len(files) - 1)  # per-part codec padding
    if abs(oi["duration"] - exp_dur) > tol:  # a container header can be a little off; decoded length is the truth
        exp_dur = sum(decoded_duration(f) for f in files)
    checks["duration_diff_s"] = round(oi["duration"] - exp_dur, 3)
    checks["duration_ok"] = abs(oi["duration"] - exp_dur) <= tol
    atoms = read_atoms(out)
    checks["moov_before_mdat"] = "moov" in atoms and "mdat" in atoms and atoms.index("moov") < atoms.index("mdat")
    ch_out = ffprobe_json(out, "-show_chapters").get("chapters", [])
    if len(files) == 1:
        # a placeholder chapter under 0.1 s is dropped by the mp4 muxer and would shift every index
        exp = sorted((float(c["start_time"]), (c.get("tags") or {}).get("title", ""))
                     for c in ffprobe_json(files[0], "-show_chapters").get("chapters", [])
                     if float(c["end_time"]) - float(c["start_time"]) >= 0.1)
    else:
        exp = expected_part_chapters(files, infos)
    got = [(float(c["start_time"]), (c.get("tags") or {}).get("title", "")) for c in ch_out]
    checks["chapters_expected"], checks["chapters_found"] = len(exp), len(got)
    checks["chapter_count_ok"] = len(exp) == len(got)
    offs = [abs(a[0] - b[0]) for a, b in zip(exp, got)]
    checks["chapter_max_offset_s"] = round(max(offs), 3) if offs else 0.0
    checks["chapter_offsets_ok"] = all(o <= CHAPTER_TOL_S for o in offs)
    checks["chapter_titles_ok"] = all(a[1] == b[1] for a, b in zip(exp, got))
    if len(files) == 1 and is_mp4(files[0]):
        st, ot = MP4(str(files[0])).tags or {}, MP4(str(out)).tags or {}
        checks["tags_missing"] = [k for k in st.keys() if k not in ot]
        checks["tags_ok"] = not checks["tags_missing"]
        checks["cover_ok"] = ("covr" not in st) or ("covr" in ot)
    else:
        checks["tags_ok"] = bool(tags_of(out).get("title"))
        src_cover = any(has_picture(f) for f in files) or folder_cover(Path(unit["folder"])) is not None
        checks["cover_ok"] = (not src_cover) or has_picture(out)
    # full audio decode; ffmpeg decodes an unmapped cover while probing, so image-decoder lines do not count
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(out), "-map", "0:a:0", "-f", "null", "-"])
    errs = [ln for ln in (r.stderr or "").splitlines()
            if ln.strip() and not re.match(r"\[(png|mjpeg|jpeg\w*|bmp|webp|gif|tiff)\b", ln)]
    checks["decode_ok"] = r.returncode == 0 and not errs
    checks["ok"] = all(checks[k] for k in ("codec_opus", "channels", "duration_ok", "moov_before_mdat",
                                           "chapter_count_ok", "chapter_offsets_ok", "tags_ok", "cover_ok", "decode_ok"))
    return checks


def write_sidecar(unit, files, infos, out: Path, res: dict) -> None:
    src_sc = Path(unit["sidecar"])
    payload = load_sidecar(src_sc) if src_sc.exists() else {}
    final = Path(unit["folder"]) / out.name
    sc_out = out.parent / ("libraforge.json" if unit["kind"] == "grouped" or src_sc.name == "libraforge.json"
                           else out.name + ".libraforge.json")
    payload.setdefault("schema_version", 2)
    payload.setdefault("tool", "audible-metadata-fixer")
    now = datetime.now(timezone.utc).isoformat()
    oi = audio_info(out)
    payload["opus_conversion"] = {
        "schema": SCHEMA, "policy": policy_name(S), "status": "verified", "converted_at": now,
        "settings": {**opus_settings(S), "bitrate_kbps": res["target"]["bitrate_kbps"], "channels": res["target"]["channels"]},
        "stereo_check": res["stereo_check"],
        "source": [{"name": f.name, "size": f.stat().st_size, "mtime_ns": f.stat().st_mtime_ns,
                    "codec": i["codec"], "channels": i["channels"], "duration_s": round(i["duration"], 3)}
                   for f, i in zip(files, infos)],
        "output": {"name": out.name, "size": out.stat().st_size, "duration_s": round(oi["duration"], 3)},
        "verify": res["verify"],
    }
    marker = payload.get("marker")
    if isinstance(marker, dict) and marker.get("source_file"):
        marker["source_file"] = out.name
    sc = payload.get("sidecar")
    if isinstance(sc, dict):
        src_sec = sc.setdefault("source", {})
        if "chapter_files" in src_sec or unit["kind"] == "grouped":
            src_sec["chapter_files"] = [str(final)]
        gs = src_sec.get("group_search")
        if isinstance(gs, dict):
            gs["file_count"], gs["files"] = 1, [str(final)]
        sc["audio_summary"] = FIXER.summarize_audio_stream_properties([out])
        sc["audio_profile_updated_at"] = now
    if "file_cache" in payload:
        payload["file_cache"] = {str(final): {"format_tags": tags_of(out), "duration_minutes": oi["duration"] / 60}}
        payload["file_cache_updated_at"] = now
    sc_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = files[0].with_name(files[0].name + ".metadata.json")  # keep the Audible metadata cache next to the book
    if md.exists():
        shutil.copy2(md, out.parent / (out.name + ".metadata.json"))
    res["sidecar_out"] = str(sc_out)


def selftest(staging: Path) -> tuple[bool, str]:
    """Convert a synthetic 12-part mp3 book through the real code path and check its chapters.
    Some ffmpeg builds write broken multi-file chapter lists; then multi-file books are refused."""
    base = staging / "_selftest"
    folder = base / "book"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(1, 13):
        f = folder / f"Part {i}.mp3"
        r = run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + i * 100}:duration={6 + i}",
                 "-ac", "2", "-c:a", "libmp3lame", "-b:a", "64k", "-metadata", f"title=Part {i}; a=b #{i}", str(f)])
        if r.returncode:
            return False, "could not create test audio: " + (r.stderr or "")[-200:]
        files.append(f)
    unit = {"kind": "grouped", "folder": folder, "root": base, "files": files, "sidecar": folder / "libraforge.json"}
    try:
        res = convert_unit(unit, staging / "_selftest_out", write_sidecars=False)
    except Exception as exc:  # noqa: BLE001
        return False, f"exception {exc!r}"
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(staging / "_selftest_out", ignore_errors=True)
    v = res.get("verify") or {}
    ok = res.get("status") == "verified" and v.get("chapters_found") == 12 and v.get("chapter_offsets_ok") and v.get("chapter_titles_ok")
    return bool(ok), "ok" if ok else f"status={res.get('status')} chapters={v.get('chapters_found')} {str(res.get('error', ''))[-150:]}"


# ---- main ----------------------------------------------------------------------
def emit(tag: str, payload: dict) -> None:
    print(f"{tag}: {json.dumps(payload, ensure_ascii=False)}", flush=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Opus transcode (DEV / WIP). Dry run unless --apply.")
    ap.add_argument("root", type=Path, help="folder to scan for books")
    ap.add_argument("--staging", type=Path, required=True, help="where converted books are written (never the library)")
    ap.add_argument("--apply", action="store_true", help="encode (default: plan only)")
    ap.add_argument("--only", action="append", default=[], help="substring of a book's folder or file path (repeatable)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--mono-kbps", type=int, default=DEFAULTS["mono_kbps"])
    ap.add_argument("--stereo-kbps", type=int, default=DEFAULTS["stereo_kbps"])
    ap.add_argument("--src-cap-ratio", type=float, default=DEFAULTS["src_cap_ratio"])
    ap.add_argument("--leave-alone-kbps", type=float, default=DEFAULTS["leave_alone_kbps"])
    ap.add_argument("--max-size-ratio", type=float, default=DEFAULTS["max_size_ratio"])
    ap.add_argument("--mode", choices=sorted(MODES), default=DEFAULTS["mode"])
    ap.add_argument("--frame-ms", type=int, choices=[20, 40, 60], default=DEFAULTS["frame_ms"])
    ap.add_argument("--side-margin-db", type=float, default=DEFAULTS["side_margin_db"])
    ap.add_argument("--side-floor-db", type=float, default=DEFAULTS["side_floor_db"])
    ap.add_argument("--no-selftest", action="store_true", help="skip the multi-file chapter self-test")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    global FIXER
    args = parse_args(argv)
    S.update(mono_kbps=args.mono_kbps, stereo_kbps=args.stereo_kbps, src_cap_ratio=args.src_cap_ratio,
             leave_alone_kbps=args.leave_alone_kbps, max_size_ratio=args.max_size_ratio, mode=args.mode,
             frame_ms=args.frame_ms, side_margin_db=args.side_margin_db, side_floor_db=args.side_floor_db)
    root, staging = args.root.resolve(), args.staging.resolve()
    if not root.is_dir():
        print(f"ERROR: not a folder: {root}", flush=True)
        return 2
    if staging == root or root in staging.parents:
        print("ERROR: the staging folder must be outside the scanned folder", flush=True)
        return 2
    FIXER = _load_fixer()
    signal.signal(signal.SIGTERM, _handle_sigterm)
    print(f"Mode: {'APPLY (encode to staging)' if args.apply else 'DRY RUN (plan only)'}", flush=True)
    print(f"Policy: {policy_name(S)}  settings: {json.dumps(S)}", flush=True)
    print(f"Scanning: {root}", flush=True)
    units = collect_units(root)
    if args.only:
        units = [u for u in units if any(o in str(u["folder"]) or any(o in str(f) for f in u["files"]) for o in args.only)]
    print(f"Books found: {len(units)}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(plan_unit, units))
    for i, row in enumerate(rows):
        row["key"] = i  # ties a book's result line to its plan line
    for row in rows:
        emit("OPUS_PLAN_JSON", row)
        what = row["folder"] if row["kind"] == "grouped" else row["files"][0]
        size = f" {row.get('source_mb')} MB -> ~{row['predicted_mb']} MB" if row.get("predicted_mb") else ""
        print(f"PLAN {row['action']:<15} {what}{size}{'  (' + row['reason'] + ')' if row['reason'] else ''}", flush=True)
    conv = [r for r in rows if r["action"] == "CONVERT"]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    summary = {"books": len(rows), "by_action": counts, "convert_hours": round(sum(r.get("duration_h", 0) for r in conv), 1),
               "convert_source_mb": sum(r.get("source_mb", 0) for r in conv),
               "convert_predicted_mb": sum(r.get("predicted_mb", 0) for r in conv), "applied": args.apply}
    print(f"Plan: {counts}; convert {len(conv)} books, {summary['convert_hours']} h, "
          f"{summary['convert_source_mb']} MB -> ~{summary['convert_predicted_mb']} MB", flush=True)
    if not args.apply or not conv:
        emit("OPUS_SUMMARY_JSON", summary)
        return 0

    staging.mkdir(parents=True, exist_ok=True)
    if any(r["kind"] == "grouped" for r in conv) and not args.no_selftest:
        ok, detail = selftest(staging)
        print(f"Self-test (multi-file chapters): {'PASS' if ok else 'FAIL'} ({detail})", flush=True)
        if not ok:
            conv = [r for r in conv if r["kind"] != "grouped"]
            print("Multi-file books are skipped: this ffmpeg writes wrong merged chapters.", flush=True)
    by_folder = {(str(u["folder"]), tuple(str(f) for f in u["files"])): u for u in units}
    lock = threading.Lock()
    done = {"verified": 0, "failed": 0, "out_mb": 0, "src_mb": 0}

    def work(row):
        u = dict(by_folder[(row["folder"], tuple(row["files"]))], src_kbps=row.get("src_kbps"))
        print(f"Converting: {row['folder'] if u['kind'] == 'grouped' else row['files'][0]}", flush=True)
        try:
            res = convert_unit(u, staging)
        except Exception as exc:  # noqa: BLE001
            res = {"folder": row["folder"], "status": "failed", "error": repr(exc)}
        res["key"] = row["key"]
        with lock:
            if res["status"] == "verified":
                done["verified"] += 1
                done["out_mb"] += round(res["out_size"] / 1e6)
                done["src_mb"] += round(res["src_size"] / 1e6)
            else:
                done["failed"] += 1
        emit("OPUS_RESULT_JSON", res)
        if res["status"] == "verified":
            t = res["target"]
            print(f"VERIFIED {res['src_size'] / 1e6:.0f} MB -> {res['out_size'] / 1e6:.0f} MB "
                  f"({'mono' if t['channels'] == 1 else 'stereo'} {t['bitrate_kbps']}k, {res['wall_s']}s) {res['out']}", flush=True)
        else:
            bad = sorted(k for k, v in (res.get("verify") or {}).items() if v is False)
            print(f"FAILED {res['status']} {row['folder']} {bad or ''} {str(res.get('error', ''))[-200:]}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        list(ex.map(work, conv))
    summary.update(done)
    emit("OPUS_SUMMARY_JSON", summary)
    print(f"Done: {done['verified']} verified, {done['failed']} failed; {done['src_mb']} MB -> {done['out_mb']} MB. "
          f"Originals untouched; converted books are in {staging}", flush=True)
    return 0 if done["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
