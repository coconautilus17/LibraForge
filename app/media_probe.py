"""One inspection per media file, shared by everything in LibraForge that reads one.

A file's container tags, first audio stream's tags, duration, stream properties and
chapter count all come from a single read, and that read answers every later question
about the same unchanged file (same path, size and nanosecond mtime): for the life of
the process, and across processes once configure_store() names the shared store. Two
threads asking about the same file wait for one read instead of starting two.

MP4/M4B/M4A files are read in-process (app/mp4_native.py) when the file has nothing that
reader does not reproduce exactly as ffprobe would; everything else is read once with
FFmpeg's libraries inside the process (PyAV), or one ffprobe call when PyAV is missing or
can't open it, collecting every field, so asking for the chapter count after the tags
costs nothing more. A failed read is never remembered, and a field it could not establish stays
unknown (None), never zero.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from struct import error as struct_error
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import mp4_native
from app.media_facts_store import MediaFactsStore

try:
    import av
except ImportError:  # optional: without it every non-native read is an ffprobe run
    av = None

# Bump when what a read reports changes, so stored facts from the old reader are dropped.
READER_VERSION = 2
NATIVE_SUFFIXES = {".m4b", ".m4a", ".mp4"}
FIELDS = frozenset({"tags", "duration", "audio", "chapters"})
# A big file whose index sits at its end can take long to read over a network
# share under load; a timeout means slow, not untagged, so one retry gets more time.
PROBE_TIMEOUTS_SECONDS = (30, 180)
MEMO_SIZE = 20000


@dataclass(frozen=True)
class MediaFacts:
    path: str
    size: int | None = None
    mtime_ns: int | None = None
    backend: str = "none"
    # The fields this inspection actually established. An empty tag dict inside a
    # covered "tags" is a file with no tags; outside it, nothing was read.
    fields: frozenset[str] = frozenset()
    format_tags: dict[str, str] = field(default_factory=dict)
    stream_tags: dict[str, str] = field(default_factory=dict)
    duration_seconds: float | None = None
    audio: dict[str, Any] | None = None
    chapter_count: int | None = None
    error: str = ""

    def merged_tags(self) -> dict[str, str]:
        """Container tags over the first audio stream's (Opus/OGG keep theirs on the stream)."""
        return {**self.stream_tags, **self.format_tags}

    def covers(self, wanted: frozenset[str]) -> bool:
        return wanted <= self.fields


_memo: OrderedDict[str, MediaFacts] = OrderedDict()
_memo_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_stats: Counter[str] = Counter()
_store: MediaFactsStore | None = None
native_enabled = True
_release: list[str | None] = []


def ffprobe_release() -> str | None:
    """The installed ffprobe's major.minor release ("9.0"), read once per process; None if it can't be read."""
    if not _release:
        try:
            out = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"ffprobe version n?(\d+)\.(\d+)", out)
            _release.append(f"{m.group(1)}.{m.group(2)}" if m else None)
        except (OSError, subprocess.SubprocessError):
            _release.append(None)
    return _release[0]


def reader_identity() -> str:
    """What a stored fact was read with: a different reader, ffprobe release or FFmpeg
    library in PyAV may report it differently."""
    libav = ".".join(map(str, av.library_versions["libavformat"])) if av else "none"
    return f"{READER_VERSION}:{ffprobe_release() or 'none'}:{libav}"


def native_allowed() -> bool:
    """The in-process MP4 reader follows one FFmpeg release's rules; with any other ffprobe, ffprobe reads everything."""
    return native_enabled and ffprobe_release() == mp4_native.FFMPEG_RELEASE


def configure_store(path: Path | str | None) -> None:
    """Keep facts in this SQLite file, shared with every process that names it; None keeps them in memory only."""
    global _store
    try:
        _store = MediaFactsStore(Path(path), reader_identity()) if path else None
    except Exception:
        _store = None


def stats() -> dict[str, int]:
    """Counts since the last reset: requests, memo hits, ffprobe runs, failures."""
    with _memo_lock:
        return dict(_stats)


def reset(clear_memo: bool = True) -> None:
    with _memo_lock:
        _stats.clear()
        if clear_memo:
            _memo.clear()


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _clean_tags(tags: Any) -> dict[str, str]:
    return {
        str(key).lower(): str(value).strip()
        for key, value in (tags or {}).items()
        if str(value).strip()
    }


def audio_properties(stream: dict[str, Any], format_info: dict[str, Any]) -> dict[str, Any]:
    """The stream properties stream-copy advice reads, from ffprobe's stream and format entries."""
    bitrate = stream.get("bit_rate") or format_info.get("bit_rate")
    codec = str(stream.get("codec_name", "") or "").lower()
    codec_label = str(stream.get("codec_long_name", "") or codec.upper())
    profile = str(stream.get("profile", "") or "")
    if profile and profile.lower() not in codec_label.lower():
        codec_label = f"{codec_label} ({profile})"
    return {
        "probed": bool(stream),
        "codec": codec,
        "codec_label": codec_label,
        "container": str(format_info.get("format_long_name", "") or format_info.get("format_name", "") or ""),
        "bitrate_kbps": round(int(bitrate) / 1000) if bitrate else None,
        "channels": int(stream["channels"]) if stream.get("channels") else None,
        "sample_rate_hz": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
    }


def _read_ffprobe(path: Path) -> MediaFacts:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", "-select_streams", "a:0", "-show_chapters",
        str(path),
    ]
    result = None
    for timeout in PROBE_TIMEOUTS_SECONDS:
        try:
            result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=False, timeout=timeout)
            break
        except subprocess.TimeoutExpired:
            _count("ffprobe_timeouts")
        except (OSError, subprocess.SubprocessError) as exc:
            return MediaFacts(path=str(path), backend="ffprobe", error=f"ffprobe could not run: {exc}")
    _count("ffprobe_runs")
    if result is None:
        return MediaFacts(path=str(path), backend="ffprobe", error=f"ffprobe timed out after {PROBE_TIMEOUTS_SECONDS[-1]}s")
    if result.returncode != 0:
        return MediaFacts(path=str(path), backend="ffprobe", error="ffprobe failed")
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return MediaFacts(path=str(path), backend="ffprobe", error="ffprobe returned invalid JSON")
    fmt = data.get("format") or {}
    stream = (data.get("streams") or [{}])[0] or {}
    try:
        seconds = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    return MediaFacts(
        path=str(path),
        backend="ffprobe",
        fields=FIELDS,
        format_tags=_clean_tags(fmt.get("tags")),
        stream_tags=_clean_tags(stream.get("tags")),
        duration_seconds=seconds if seconds > 0 else None,
        audio=audio_properties(stream, fmt),
        chapter_count=len(data.get("chapters") or []),
    )


def _count(name: str, n: int = 1) -> None:
    with _memo_lock:
        _stats[name] += n


def inspect(path: Path | str, fields: frozenset[str] | set[str] | tuple[str, ...] = FIELDS) -> MediaFacts:
    """What is known about one file: from memory while the file is unchanged, else one read."""
    path = Path(path)
    wanted = frozenset(fields) & FIELDS
    key = str(path)
    _count("requests")
    signature = _signature(path)

    def remembered() -> MediaFacts | None:
        facts = _memo.get(key)
        if facts and signature and (facts.size, facts.mtime_ns) == signature and facts.covers(wanted):
            _memo.move_to_end(key)
            return facts
        return None

    with _memo_lock:
        facts = remembered()
        if facts:
            _stats["memo_hits"] += 1
            return facts
        key_lock = _key_locks.setdefault(key, threading.Lock())
    try:
        with key_lock:
            return _read_and_remember(path, key, signature, remembered, wanted)
    finally:
        with _memo_lock:
            _key_locks.pop(key, None)


def _read_and_remember(path: Path, key: str, signature: tuple[int, int] | None, remembered,
                       wanted: frozenset[str] = FIELDS) -> MediaFacts:
    with _memo_lock:
        facts = remembered()  # another thread may have just read it
        if facts:
            _stats["memo_hits"] += 1
            return facts
    store = _store
    stored = store.get(key, *signature) if store and signature else None
    if stored and wanted <= frozenset(stored.get("fields") or ()):
        _count("store_hits")
        facts = MediaFacts(path=key, size=signature[0], mtime_ns=signature[1], **_from_payload(stored))
        _remember(key, facts)
        return facts
    facts = _read(path, wanted)
    if not facts.fields:
        _count("failures")
        return facts
    after = _signature(path)
    if signature is None or after != signature:
        return facts  # changed (or unstattable) while being read: true now, not worth remembering
    facts = MediaFacts(**{**facts.__dict__, "size": signature[0], "mtime_ns": signature[1]})
    _remember(key, facts)
    if store:
        store.put(key, *signature, _to_payload(facts))
    return facts


def _remember(key: str, facts: MediaFacts) -> None:
    with _memo_lock:
        _memo[key] = facts
        _memo.move_to_end(key)
        while len(_memo) > MEMO_SIZE:
            _memo.popitem(last=False)


def _to_payload(facts: MediaFacts) -> dict[str, Any]:
    return {"backend": facts.backend, "fields": sorted(facts.fields), "format_tags": facts.format_tags,
            "stream_tags": facts.stream_tags, "duration_seconds": facts.duration_seconds,
            "audio": facts.audio, "chapter_count": facts.chapter_count}


def _from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "fields": frozenset(payload.get("fields") or ())}


def _read(path: Path, wanted: frozenset[str] = FIELDS) -> MediaFacts:
    """In-process for MP4 files the native reader fully reproduces, else ffprobe.

    Without "audio" wanted, the native reader skips the sample tables (most of a
    long book's index) and establishes every field but "audio"; asking for audio
    later reads the file again in full."""
    if path.suffix.lower() in NATIVE_SUFFIXES and native_allowed():
        light = "audio" not in wanted
        try:
            native = mp4_native.read(path, light=light)
        except mp4_native.Unsupported:
            _count("native_fallbacks")
        except (OSError, ValueError, IndexError, struct_error):
            _count("native_errors")
        else:
            _count("native_light_reads" if light else "native_reads")
            return MediaFacts(
                path=str(path),
                backend="native",
                fields=FIELDS - {"audio"} if light else FIELDS,
                format_tags=_clean_tags(native["format_tags"]),
                stream_tags=_clean_tags(native["stream_tags"]),
                duration_seconds=native["duration_seconds"],
                audio=None if light else audio_properties(native["stream"], native["format"]),
                chapter_count=native["chapter_count"],
            )
    return _read_av(path) or _read_ffprobe(path)


def _read_av(path: Path) -> MediaFacts | None:
    """Every field from FFmpeg's own libraries inside this process (PyAV), the same
    answers ffprobe gives without starting a program per file, which is most of an
    ffprobe run's time. None when PyAV is missing or can't open the file, which then
    goes to ffprobe."""
    if av is None:
        return None
    try:
        with av.open(str(path), timeout=PROBE_TIMEOUTS_SECONDS[-1]) as container:
            stream = container.streams.audio[0] if container.streams.audio else None
            fmt = {"format_name": container.format.name, "format_long_name": container.format.long_name,
                   "bit_rate": container.bit_rate or None}
            probed: dict[str, Any] = {}
            if stream is not None:
                context = stream.codec_context
                codec = context.codec
                probed = {"codec_name": codec.canonical_name, "codec_long_name": codec.long_name,
                          "profile": stream.profile, "bit_rate": context.bit_rate or None,
                          "channels": context.channels, "sample_rate": context.sample_rate}
            seconds = container.duration / av.time_base if container.duration else 0.0
            facts = MediaFacts(
                path=str(path),
                backend="av",
                fields=FIELDS,
                format_tags=_clean_tags(container.metadata),
                stream_tags=_clean_tags(stream.metadata if stream is not None else {}),
                duration_seconds=seconds if seconds > 0 else None,
                audio=audio_properties(probed, fmt),
                chapter_count=len(container.chapters()),
            )
    except Exception:
        _count("av_fallbacks")
        return None
    _count("av_reads")
    return facts


def forget(path: Path | str) -> None:
    """Drop what is remembered about a file LibraForge just rewrote (its mtime would also tell)."""
    with _memo_lock:
        _memo.pop(str(path), None)
    if _store:
        _store.forget(str(path))


def prune_missing(root: Path | str) -> int:
    """Forget stored facts for files under root that no longer exist. Does nothing when
    root is missing, can't be listed or is empty: an unmounted share looks just like
    that, and pruning then would throw away every stored fact."""
    store, root = _store, Path(root)
    if store is None:
        return 0
    try:
        with os.scandir(root) as entries:
            if next(entries, None) is None:
                return 0
    except OSError:
        return 0
    gone = [path for path in store.paths_under(str(root)) if not os.path.exists(path)]
    for path in gone:
        store.forget(path)
    return len(gone)


def duration_seconds(path: Path | str) -> float | None:
    return inspect(path, {"duration"}).duration_seconds


def chapter_count(path: Path | str) -> int | None:
    facts = inspect(path, {"chapters"})
    return facts.chapter_count if "chapters" in facts.fields else None


def audio_properties_of(path: Path | str) -> dict[str, Any]:
    facts = inspect(path, {"audio"})
    return facts.audio if facts.audio is not None else {"probed": False}
