from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CACHE_VERSION = 3


def search_cache_key(path: Path, script_name: str) -> str:
    value = json.dumps(
        {"path": str(path), "script_name": script_name},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_discovery_cache(cache_path: Path) -> dict[str, Any]:
    """Load the M4B discovery cache. A version mismatch (including cache
    files written before CACHE_VERSION 3, which lack folder_signatures on
    each search entry) is treated as no cache at all, forcing a fresh
    build rather than crashing on a missing field.
    """
    if not cache_path.is_file():
        return {"version": CACHE_VERSION, "searches": {}}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": CACHE_VERSION, "searches": {}}
    if data.get("version") != CACHE_VERSION or not isinstance(data.get("searches"), dict):
        return {"version": CACHE_VERSION, "searches": {}}
    return data


def save_discovery_cache(cache_path: Path, cache: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    temporary.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_signature(file_path: Path) -> dict[str, int]:
    stat = file_path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class CachedChapterCountReader:
    def __init__(
        self,
        *,
        probe: Callable[[Path], int | None],
        entries: dict[str, Any] | None = None,
    ) -> None:
        self.probe = getattr(probe, "__wrapped__", probe)
        self.entries = entries if isinstance(entries, dict) else {}
        self.seen: set[str] = set()
        self.reused = 0
        self.probed = 0

    def __call__(self, file_path: Path) -> int | None:
        path = str(file_path)
        signature = file_signature(file_path)
        cached = self.entries.get(path, {})
        self.seen.add(path)
        if (
            cached.get("size") == signature["size"]
            and cached.get("mtime_ns") == signature["mtime_ns"]
            and "chapter_count" in cached
        ):
            self.reused += 1
            return cached["chapter_count"]

        chapter_count = self.probe(file_path)
        self.entries[path] = {
            **signature,
            "chapter_count": chapter_count,
        }
        self.probed += 1
        return chapter_count

    def pruned_entries(self) -> dict[str, Any]:
        return {
            path: self.entries[path]
            for path in sorted(self.seen)
            if path in self.entries
        }


class CachedAudioProbeReader:
    def __init__(
        self,
        *,
        probe: Callable[[Path], dict[str, Any]],
        entries: dict[str, Any] | None = None,
    ) -> None:
        self.probe = probe
        self.entries = entries if isinstance(entries, dict) else {}
        self.seen: set[str] = set()
        self.reused = 0
        self.probed = 0

    def __call__(self, file_path: Path) -> dict[str, Any]:
        path = str(file_path)
        signature = file_signature(file_path)
        cached = self.entries.get(path, {})
        self.seen.add(path)
        if (
            cached.get("size") == signature["size"]
            and cached.get("mtime_ns") == signature["mtime_ns"]
            and isinstance(cached.get("audio"), dict)
        ):
            self.reused += 1
            return cached["audio"]

        audio = self.probe(file_path)
        self.entries[path] = {
            **signature,
            "audio": audio,
        }
        self.probed += 1
        return audio

    def pruned_entries(self) -> dict[str, Any]:
        return {
            path: self.entries[path]
            for path in sorted(self.seen)
            if path in self.entries
        }
