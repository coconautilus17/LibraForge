"""One inspection per media file, shared by everything in LibraForge that reads one.

A file's container tags, first audio stream's tags, duration, stream properties and
chapter count all come from a single read, and that read answers every later question
about the same unchanged file (same path, size and nanosecond mtime) for the life of the
process. Two threads asking about the same file wait for one read instead of starting two.

The reader is ffprobe: one call collects every field, so asking for the chapter count
after the tags costs nothing more. A failed read is never remembered, and a field it
could not establish stays unknown (None), never zero.
"""
from __future__ import annotations

import json
import subprocess
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
            return _read_and_remember(path, key, signature, remembered)
    finally:
        with _memo_lock:
            _key_locks.pop(key, None)


def _read_and_remember(path: Path, key: str, signature: tuple[int, int] | None, remembered) -> MediaFacts:
    with _memo_lock:
        facts = remembered()  # another thread may have just read it
        if facts:
            _stats["memo_hits"] += 1
            return facts
    facts = _read_ffprobe(path)
    if not facts.fields:
        _count("failures")
        return facts
    after = _signature(path)
    if signature is None or after != signature:
        return facts  # changed (or unstattable) while being read: true now, not worth remembering
    facts = MediaFacts(**{**facts.__dict__, "size": signature[0], "mtime_ns": signature[1]})
    with _memo_lock:
        _memo[key] = facts
        _memo.move_to_end(key)
        while len(_memo) > MEMO_SIZE:
            _memo.popitem(last=False)
    return facts


def forget(path: Path | str) -> None:
    """Drop what is remembered about a file LibraForge just rewrote (its mtime would also tell)."""
    with _memo_lock:
        _memo.pop(str(path), None)


def duration_seconds(path: Path | str) -> float | None:
    return inspect(path, {"duration"}).duration_seconds


def chapter_count(path: Path | str) -> int | None:
    facts = inspect(path, {"chapters"})
    return facts.chapter_count if "chapters" in facts.fields else None


def audio_properties_of(path: Path | str) -> dict[str, Any]:
    facts = inspect(path, {"audio"})
    return facts.audio if facts.audio is not None else {"probed": False}
